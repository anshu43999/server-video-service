# 服务端视频输入、PC预览与分析告警协议

版本：v3，2026-10-15，现行决策 [ADR-003](adr-003-analysis-alerts-only.md)。v1/v2中的移动推流/收流、WHEP/LL-HLS/RTSP输出、MJPEG和逐帧检测订阅已退役。视频输入、PC实时预览、YOLO与正式告警保留，不改变移动端图片/相机本地分析。

## 1. 身份、项目与权限

所有新业务接口使用 `/aiyoloapi/projects/{project_id}` 前缀。平台超级管理员显式进入项目留审计；项目负责人维护源/参数/模型绑定；项目用户按能力查看、使用模型、预览及消费告警。权限与生命周期以 [项目授权](project-authorization-kernel.md)、[视频隔离](project-stream-isolation.md)、[服务主体](project-service-principals.md) 为准。

控制API继续接受对应权限的账号会话；PC预览只接受同源Session Cookie，拒绝Bearer（包括同时带Cookie）、旧静态Token、服务凭据和跨站读取。不要用客户端或物理设备名称当安全边界。旧非项目路由仅用于受控迁移，不能默选默认项目。

## 2. 控制面

下表路径均加项目根前缀：

| 方法 | 路径 | 行为 |
|---|---|---|
| POST | `/streams` | 新建配置/运行会话，成功201；重复运行或不同配置409 |
| GET | `/streams` | 列出本项目启用/停用配置、运行状态、模型/输入/告警错误 |
| PATCH | `/streams/{stream_id}/config` | 配置显示名、启停、置信度、最大处理FPS、YOLO/叠加及模型绑定 |
| GET / PUT | `/streams/{stream_id}/model` | 查询/绑定本项目获授权的模型版本 |
| POST | `/streams/{stream_id}/yolo` | 开关分析；模型不可用可观测，不终止输入 |
| DELETE | `/streams/{stream_id}` | 删除配置并释放会话，成功204；不是升级清理操作 |
| GET | `/capabilities/sources` | 当前项目规则可用来源 |
| GET | `/metrics` | 受项目能力控制的指标 |

平台 `/aiyoloapi/metrics` 另受平台能力限制，不能泄露其他项目源。输入URL中的敏感凭据不应进入日志/普通API响应。

创建示例：

```json
{"stream_id":"inspection-001","display_name":"North Gate","source_type":"rtsp","source_url":"rtsp://camera.example/live","enabled":true}
```

`stream_id` 为1–128个ASCII字母/数字/点/下划线/连字符，以字母或数字起始。支持RTSP/RTSPS、HTTP、文件、摄像头索引；`source_url=null` 保留为已授权设备/服务等待输入，不能据此恢复移动推流UI。创建可包含 `model_id/model_version`；绑定示例 `{"model_id":"inspection-model","model_version":"1.0.0"}`。

YOLO控制 `{"enabled":true}`。配置可包含 `confidence`（0.01–0.99）、`max_fps`（1–60）、`yolo_enabled`、`overlay_enabled`、`display_name`、`enabled`、`model_id/model_version`；实际项目模型参数约束仍有效。source_url不属于当前PATCH请求字段；不能声称修改UI中输入源就已更新运行输入。

持久化配置以 `(project_id, stream_id)` 标识；完全相同且没有运行会话的旧配置可按既有幂等流程恢复。重启只恢复启用流，停用记录保留。帧、预览缓存、运行队列不入业务配置库。

## 3. 输入面

`WS /aiyoloapi/projects/{project_id}/streams/{stream_id}/ingest` 保留项目/账号或明确授权服务主体能力检查。连接撤权和项目状态变化继续检查；这不是移动远程视频产品功能。

- binary消息每条一张完整JPEG/PNG，不拆分拼接；非法帧不导致进程退出。
- 最大5MiB、1920×1080，默认最大输入30fps（MAX_INPUT_FPS）；配置RTSP_TRANSPORT=tcp或udp用于输入。
- 输入限速/队列latest-only，忙时丢旧帧，不堆积延迟。
- 文本ping格式为 `{"type":"ping","request_id":"..."}`；错误和消息限制沿用输入处理器，不把历史播放错误当输入错误。
- RTSP断流释放VideoCapture并重试；输入连接断开不等于删除持久配置。
- OpenCV/FFmpeg为输入解码和图片证据保留，不再调用H.264发布编码器。

## 4. PC专用预览

`GET /aiyoloapi/projects/{project_id}/streams/{stream_id}/preview`：

| 状态 | 语义 | 客户端处理 |
|---|---|---|
| 200 | 当前JPEG，`X-Preview-Mode: raw|yolo` | 替换上一帧并释放对象URL |
| 204 | 无有效帧或输入超过3秒未更新 | 清空画面，后续轮询可恢复 |
| 401/403 | 未登录、失效或无能力/错误通道 | 清屏，停止未授权预览 |
| 404 | 项目不可见、流不存在/已关闭 | 清屏，不尝试其他项目 |
| 网络失败/超时 | 不保证新帧可用 | 清空旧图，取消过期请求 |

响应包含 `Cache-Control: no-store, private`、`Cross-Origin-Resource-Policy: same-origin` 和 `X-Content-Type-Options: nosniff`。请求前及编码后复验权限/会话/流身份；网关不得缓存JPEG、改写鉴权失败或开放跨域。

预览按需编码，最高5fps、宽1280、共享短时缓存；不是25/30fps全帧率播放器。YOLO关闭/不可用显示raw，开启且有有效匹配推理结果可显示yolo；标注超过2秒或模型代次失效则不展示。切项目/离页abort，迟到响应不可显示。已交给浏览器的单帧无法远程收回。

## 5. 分析与告警

分析使用独立帧率和latest-only，无预览者时仍运行。检测结果是规则输入，不是逐帧推送消息。规则、冷却/去重和持久化产生正式告警后，由项目告警查询、通知、处置及证据接口消费，保留 `SERVER_STREAM/streamId` 溯源和模型/规则快照。

独立告警接口参见 [告警隔离](project-alert-isolation.md)。断线补拉、提示去重、持久化失败、证据失败和投递失败分别可观测；不能使用直播订阅驱动通知。M34-T05/T06与Android M101负责未完成的闭环与真实联合验收，本协议不是其完成证明。

### 5.1 内部检测序列化兼容

以下仅为 `FrameDetections.to_wire()` 保留的数据形状（叠加/规则的内部结果兼容），不是对外WebSocket或正式告警消息。客户端不能通过此示例重新订阅逐帧检测。类别名由模型提供，未跟踪时不伪造track_id，box使用归一化左上角坐标。

```json
{"stream_id":"inspection-001","frame_seq":1024,
 "captured_at":"2026-09-03T10:00:00.123+08:00",
 "model":"yolo11n","inference_ms":18.4,
 "detections":[{"class_id":0,"class_name":"person","confidence":0.87,
                "box":{"x":0.31,"y":0.22,"w":0.12,"h":0.34}}]}
```

## 6. 退役接口与错误

旧项目及非项目 `/streams/{stream_id}/playback`、`mjpeg` 始终HTTP410，`detail.code=live_video_retired`，不查询资源、不返回地址。旧 `ws/detections` 关闭1008、reason为live_video_retired。内部 `POST /aiyoloapi/internal/media/authorize` 对所有请求403（含空/非法payload及read/publish/api），不查会话或存储。

不重试这些接口、不改走WHEP/LL-HLS/RTSP输出、不设置旧环境变量复活功能。输入RTSP和新的PC预览不是旧出口例外。告警WS和已存短视频证据仍保留。

其他控制/输入错误：不可见资源404、重复/版本冲突409、参数422、未认证401/403；输入非法/超大帧、限速和模型错误依实际处理器与运行状态呈现。不要将历史encoder_unavailable/publish_failed/playback_unavailable作为当前服务故障类别。

## 7. 状态、兼容与运维

运行状态created/ingesting/analyzing/error/closed；outputting枚举仅兼容历史。YOLO模式独立，旧metrics的publish_state=retired、frames_published=0、viewers=0不是健康或PC观看人数。观察输入/处理帧、丢帧、模型错误、alert_error与存储/投递状态。

`/healthz` 包括已配置数据库健康，不检查已退役媒体端口；预览可用不证明YOLO或告警已可用。`video-protocol.schema.json` 保留基础请求子集，完整请求字段以本服务OpenAPI为准。

旧流、模型绑定/版本/revision、告警和证据无损保留；配置退役无需数据库迁移。升级/回退须遵守 [手册](media-retirement-upgrade.md)，先本地验收，再容器部署，不恢复移动分发。

## 8. 验证矩阵

独立告警的REST/WS路径、项目鉴权、断线补取和提示去重规则见[独立告警通知契约](independent-alert-notifications.md)。告警WS不是检测帧订阅，移动端不得从来源streamId跳转到退役播放出口。

至少覆盖RTSP接入/断流重连、raw/yolo预览、无人观看分析告警、同ID跨项目隔离、撤权/关流/切模型竞态、旧接口拒绝、旧配置忽略、持久流恢复与历史证据可读。单元桩与真实模型/摄像机/PostgreSQL/API27/长稳结果分开留证据，不能相互替代。
