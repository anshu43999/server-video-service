# 服务端视频流联调协议

版本：`v2`（输出面按 [ADR-002](adr-002-production-transport.md) 重构；`v1` 的控制面语义保持不变）
状态：生效
适用对象：移动端视频推送客户端、移动端播放客户端、服务端视频处理服务、管理控制台
历史：`v1`（M01-T01）冻结于 2026-09-02，输出面为 MJPEG/WebSocket JPEG

## 1. 协议范围

本协议覆盖视频流链路和运行时控制，不改变移动端图片分析和本地相机分析。移动端在推流侧负责采集、编码、推送；服务端负责接收、可选 YOLO 推理、可选叠加、H.264 编码和分发；移动端在播放侧只负责播放，**不在接收到的远程流上做推理**。

输入面仍使用 JPEG 帧。输出面从 v1 的 JPEG 序列改为 **H.264，由媒体服务器（MediaMTX）分发**：WebRTC/WHEP 是生产播放路径，LL-HLS 是回退，RTSP 只给诊断工具，MJPEG/WebSocket JPEG 降级为测试与诊断通道。检测结果不再只烧进画面，而是以 JSON 走独立 WebSocket 旁路。

`stream_id`、会话状态和 YOLO 控制语义在 v1 与 v2 之间保持一致。

## 2. 连接与鉴权占位

- HTTP 基础地址（控制面）：`http(s)://<server-host>:8080`
- WebSocket 基础地址（推流与元数据）：`ws(s)://<server-host>:8080`
- 媒体基础地址（播放）：WHEP `http(s)://<media-host>:8889`、LL-HLS `http(s)://<media-host>:8888`、RTSP `rtsp://<media-host>:8554`
- 移动端业务接口预留请求头：`X-Video-Service-Token: <device-token>`
- 管理员接口预留：`Authorization: Bearer <admin-token>`
- 设置 `ADMIN_TOKEN` 和/或 `MOBILE_TOKEN` 后服务端启用对应鉴权；留空时保持兼容模式。
- 令牌不得出现在 URL、日志或视频帧中。

## 3. 编码、尺寸和帧率

### 3.1 输入帧

| 项目 | 冻结值 |
|---|---|
| WebSocket 消息 | binary，一条消息一张完整图片 |
| 接受格式 | JPEG（推荐）或 PNG |
| 推荐编码 | JPEG Baseline，质量 75–85 |
| 最大消息大小 | 5 MiB |
| 最大有效尺寸 | 1920×1080 |
| 推荐尺寸 | 1280×720 或 1920×1080 |
| 最大输入帧率 | 30 FPS |
| 时间戳 | 输入图片不嵌入时间戳；服务端为每帧分配递增 `frame_seq` 和接收时间，用于元数据对齐 |

服务端不保证保留输入图片的原始压缩字节，会解码后重新编码输出。移动端必须把每条图片消息视为独立帧，不得拆分或拼接 JPEG 数据。

### 3.2 输出视频（生产）

每路流只做一次 H.264 编码，编码参数为播放端硬解码能力定死：

| 项目 | 冻结值 |
|---|---|
| 编码 | H.264（AVC） |
| Profile | Baseline 或 Main |
| Level | ≤ 4.0 |
| B 帧 | 不使用（`bf=0`） |
| GOP | 1–2 秒（25fps 下 25–50 帧） |
| 调优 | `tune=zerolatency` |
| 码率控制 | CBR，或 CRF + `maxrate`/`bufsize` |
| 目标档位 | 720p @ 15–25 fps，2–3 Mbps |
| 音频 | 无 |

分发协议与地址（`{path}` 默认取 `stream_id`）：

| 用途 | 协议 | 地址 |
|---|---|---|
| 生产播放 | WebRTC / WHEP | `http(s)://<media-host>:8889/{path}/whep` |
| 回退 | LL-HLS | `http(s)://<media-host>:8888/{path}/index.m3u8` |
| 诊断 | RTSP | `rtsp://<media-host>:8554/{path}` |

- 输出尺寸默认跟随输入有效尺寸，但必须满足编码器对齐要求；
- 输出 FPS 不高于会话 `max_fps`；
- YOLO 关闭时输出原始画面的编码结果；YOLO 开启且叠加打开时输出带框画面；
- 播放端不得假设首帧就是关键帧之外的帧，也不得假设存在 B 帧；
- 客户端必须先尝试 WHEP，失败后按 §6.3 回退到 LL-HLS，回退必须对用户和日志可见。

### 3.3 输出帧（测试与诊断，非生产）

- MJPEG：`multipart/x-mixed-replace; boundary=frame`，每个 part `Content-Type: image/jpeg` 并带 `Content-Length`；
- WebSocket 输出：binary，一条消息一张 JPEG；
- 这两条通道只用于管理页预览、自动化测试和联调探针，不得作为 App 的播放路径，也不承诺带宽和延迟指标。

## 4. 会话生命周期

```text
created → ingesting → outputting
              │              │
              └──────→ error ┘
                         │
                       closed
```

| 状态 | 含义 |
|---|---|
| `created` | 已创建，尚未收到有效帧 |
| `ingesting` | 正在接收或拉取输入 |
| `outputting` | 至少一帧已编码，可被订阅者读取 |
| `error` | 最近一次输入、解码、推理或编码失败，会话仍可恢复 |
| `closed` | 已删除或服务关闭，不再接受输入 |

YOLO 模式独立于会话状态：`off` 或 `on`。模型不可用时，开启请求响应会返回 `model_error`，但不应让会话进入 `closed`。

## 5. HTTP API

### 5.1 创建会话

`POST /api/streams`

请求：

```json
{"stream_id":"inspection-001","display_name":"North Gate","source_type":"rtsp","source_url":null,"enabled":true}
```

`stream_id` 必须为 1–128 个 ASCII 字母、数字、点、下划线或连字符，且以字母或数字开头。`display_name`、`source_type` 和 `enabled` 可省略；`source_url=null` 表示等待移动端 WebSocket 推帧，提供 URL 时服务端主动拉流。

创建成功后，控制面配置写入 `stream_configs`，包括来源、模型绑定、YOLO 参数、启用状态和创建/更新时间。视频帧、WebSocket 队列与实时指标不写入业务数据库。若同一配置已经存在但当前没有运行时会话，完全一致的创建请求按幂等恢复处理；运行时会话仍存在或关键字段不一致时返回冲突。

成功 `201`：

```json
{"stream_id":"inspection-001","state":"created","yolo_enabled":false}
```

### 5.2 查询会话

`GET /api/streams`

返回数组。每项至少包含 `stream_id`、`display_name`、`source_type`、脱敏后的 `source_url`、`enabled`、`state`、`yolo_enabled`、`frames_received`、`frames_processed`、`confidence`、`max_fps`、`last_error`，以及输出面字段 `publish_state`（`idle`/`connected`/`reconnecting`/`failed`）和 `viewers`。RTSP 用户名、密码和查询参数不会出现在普通 API 响应或拉流错误中。

### 5.3 YOLO 开关

`POST /api/streams/{stream_id}/yolo`

请求：`{"enabled":true}`。成功 `200` 返回 `stream_id`、`state`、`yolo_enabled`、`model_error`。

### 5.4 单路运行参数

`PATCH /api/streams/{stream_id}/config`

可选字段：

```json
{"confidence":0.4,"max_fps":15,"yolo_enabled":true,"overlay_enabled":true,"display_name":"North Gate","enabled":true}
```

`confidence` 范围 `0.01–0.99`，`max_fps` 范围 `1–60`。`enabled=false` 会持久化停用并关闭当前会话，之后可用 `enabled=true` 重新建立会话。未提供的字段保持原值。服务进程启动时会读取 `enabled=true` 的配置并恢复会话；单路来源连接失败只让该流进入可重试错误状态，不阻塞其他流和服务启动。`enabled=false` 的配置仍由列表返回，但标记为 `configuration_state=disabled`、`runtime_available=false`，不会自动恢复。

### 5.5 播放地址

`GET /api/streams/{stream_id}/playback`

返回该流的播放入口与当前可用性，客户端据此选择路径，不硬编码地址：

```json
{"stream_id":"inspection-001",
 "publish_state":"connected",
 "whep":{"url":"http://media:8889/inspection-001/whep","available":true},
 "llhls":{"url":"http://media:8888/inspection-001/index.m3u8","available":true},
 "rtsp":{"url":"rtsp://media:8554/inspection-001","available":true,"diagnostics_only":true}}
```

`publish_state` 取 `connected`、`reconnecting`、`failed`、`idle`。`available:false` 表示该协议当前不可用，客户端应按 §6.3 顺序回退。

### 5.6 删除会话

`DELETE /api/streams/{stream_id}`，成功返回 `204`。

## 6. WebSocket 与播放

### 6.1 移动端推流

连接：`/api/streams/{stream_id}/ingest`

- 客户端发送 binary JPEG/PNG；
- 服务端不要求客户端等待 ACK，可按最大 30 FPS 推送；
- 客户端可发送文本 `{"type":"ping","request_id":"..."}`，服务端返回 `{"ok":true}`；
- 客户端断开后服务端保留会话，是否删除由客户端调用 DELETE 决定。

### 6.2 检测结果旁路

连接：`/api/streams/{stream_id}/detections`

服务端按帧发送文本 JSON：

```json
{"stream_id":"inspection-001","frame_seq":1024,
 "captured_at":"2026-09-03T10:00:00.123+08:00",
 "model":"yolo11n","inference_ms":18.4,
 "detections":[{"class_id":0,"class_name":"person","confidence":0.87,
                "box":{"x":0.31,"y":0.22,"w":0.12,"h":0.34}}]}
```

- `box` 为归一化坐标（0–1，左上原点，`x`/`y` 为左上角），与输出画面尺寸无关；
- `track_id` 为可选字段，只在来源真的提供跟踪 id 时出现；不做跟踪的模型不得伪造该字段；
- YOLO 关闭时不发送检测消息，可发送心跳 `{"stream_id":"...","yolo_enabled":false}`；
- 该通道与视频通道互不依赖：任一方断开重连都不影响另一方；
- 客户端必须容忍 `frame_seq` 跳号（latest-only 丢帧属正常行为）；
- 客户端不得依赖检测消息与视频帧的严格同步，只能按 `frame_seq`/时间戳做最佳努力对齐。

### 6.3 播放与回退顺序

1. 用 `GET /api/streams/{stream_id}/playback` 取地址；
2. 优先 WHEP：向 `whep.url` POST SDP offer，`Content-Type: application/sdp`，响应体为 SDP answer；
3. WHEP 建连失败或超时（UDP 被封、ICE 失败、SDP 交换失败）后回退 LL-HLS；
4. 两者都失败时向用户报错，不静默停留在黑屏；
5. RTSP 只供 VLC/ffprobe 等工具排障，客户端不得把它作为回退路径；
6. MJPEG/WebSocket JPEG 只用于管理页和自动化测试。

### 6.4 管理端诊断预览

MJPEG：`/api/streams/{stream_id}/mjpeg`；WebSocket JPEG：`/api/streams/{stream_id}/ws`。仅用于诊断，不承诺指标。

## 7. 错误码与重试

HTTP 错误响应统一预留为：

```json
{"error":{"code":"stream_not_found","message":"stream not found","request_id":"optional-id","retryable":false}}
```

当前 FastAPI MVP 仍使用 `detail` 兼容响应，生产错误体在 `M03` 统一。

| 错误码 | HTTP/WS | 是否重试 | 说明 |
|---|---:|---|---|
| `stream_not_found` | 404/4404 | 否 | 先创建会话或检查 ID |
| `stream_already_exists` | 409 | 否 | 使用已有会话或换 ID |
| `invalid_frame` | 400/4400 | 否 | 丢弃当前帧，检查编码 |
| `frame_too_large` | 413/4400 | 否 | 降低分辨率或 JPEG 质量 |
| `input_rate_limited` | 429/4429 | 是 | 降低推送帧率 |
| `model_unavailable` | 503 | 是 | 关闭 YOLO 或等待模型恢复 |
| `encoder_unavailable` | 503 | 是 | H.264 编码器初始化失败，检查编码器与参数 |
| `publish_failed` | 503 | 是 | 到媒体服务器推流失败，等待重连或检查媒体服务器 |
| `playback_unavailable` | 503 | 是 | 该流暂无可用播放路径，按 §6.3 重试或回退 |
| `internal_error` | 500 | 视情况 | 查看服务日志和状态 |

## 8. 联调最低要求

1. 移动端可以创建唯一会话并拿到 `stream_id`；
2. 推送端可持续发送 1280×720 JPEG，目标 15–30 FPS；
3. 播放端可通过 WHEP 播放 H.264，并能在 WHEP 不可用时回退 LL-HLS；
4. 播放端可订阅检测结果 WebSocket 并拿到类别、置信度和坐标框；
5. 调用 YOLO 开关后，不重连即可看到原始/叠加模式变化；
6. 移动端处理 `404/409/413/429/503` 并向用户显示可理解状态；
7. App 退出或网络断开后，客户端按策略删除会话或重新连接；
8. 真实联调必须记录输入 FPS、编码 FPS、输出 FPS、端到端延迟（P50/P95）、回退发生次数和重连次数。

## 9. 后续兼容规则

- 新增字段只能向后兼容，不能改变既有字段语义；
- 升级协议时使用 `/api/v2` 或显式 `protocol_version`，不静默改变既有行为；
- 控制面语义（`stream_id`、会话状态、YOLO 开关）与传输协议解耦：更换分发协议不得改变控制面；
- 检测结果通道与视频通道必须保持可独立消费，不得为了同步把二者重新耦合；
- 增加新的分发协议（如 SRT 服务端间链路）只能作为额外出口，不得改变 WHEP 为生产主链路的定位；除 ADR-002 声明的 LL-HLS 回退外，不得引入第二条隐式回退路径。
