# ADR-002：生产输出传输协议重构

状态：accepted（取代 ADR-001）
日期：2026-09-03
适用任务：`M07-T02`
取代：`docs/adr-001-output-protocol.md`

## 背景

ADR-001 把 MJPEG / WebSocket JPEG 定为 MVP 与 P1 的输出协议，把 WebRTC 留到 P2 做 PoC。按该路线继续推进后，暴露出四个不是靠调参能解决的结构性问题，因此本决策整体重置输出传输协议，而不是在 ADR-001 的阶段划分上继续往后走。

需要明确的定位前提：**App 只接收服务端推理后的视频流，不在远程流上做任何推理。** 一路流可能被多个用户同时观看，推理必须在服务端统一完成。App 的端侧 YOLO 只用于本地图片和相机预览实时帧。

## 决策

### 1. 输出协议分层

| 用途 | 协议 | 定位 |
|---|---|---|
| 生产播放（App、浏览器） | **WebRTC，信令用 WHEP** | 主链路，唯一的生产播放路径 |
| 过渡与回退 | **LL-HLS** | WebRTC 打不通（UDP 被封、NAT 失败、客户端不具备条件）时降级；也用于早期没有 WebRTC 客户端时先跑通链路 |
| 诊断与排障 | **RTSP** | 只给 VLC/ffprobe 等工具连，不进 App |
| 测试与诊断 | **MJPEG / WebSocket JPEG** | 保留但降级：管理页预览、自动化测试、联调探针。不再是任何客户端的生产输出 |

### 2. 服务端只编码一次，由媒体服务器扇出

Python 服务对每一路流只做一次 H.264 编码，把结果推给 MediaMTX，由 MediaMTX 同时提供 WebRTC/WHEP、LL-HLS 和 RTSP。服务端不再为每个订阅者单独编码，也不再自研扇出、重连和拥塞控制。

```
输入（App 推帧 / RTSP / 文件）
  → 解码为帧
  → YOLO 推理（latest-only）
  → 叠加（可选）
  → H.264 编码（一次）
  → 推流到 MediaMTX
      ├── WebRTC / WHEP  → App、浏览器（生产）
      ├── LL-HLS         → 回退
      └── RTSP           → 诊断工具
  → 检测结果 JSON → WebSocket 旁路（与视频分开）
```

### 3. 控制面与数据面分离

- **控制面**：REST/JSON，沿用现有 `stream_id` 会话语义、`yolo_enabled` 开关、模型切换和会话删除接口；
- **视频面**：H.264（WebRTC/LL-HLS/RTSP）；
- **元数据面**：检测结果以 JSON 走独立 WebSocket 旁路，与视频帧解耦。

### 4. H.264 编码约束（为 API 27 硬解码定死）

| 参数 | 取值 | 原因 |
|---|---|---|
| Profile | Baseline 或 Main | API 27 设备硬解码覆盖面最广 |
| Level | ≤ 4.0 | 同上 |
| B 帧 | **`bf=0`，不使用** | B 帧引入重排序延迟，实时链路不可接受 |
| GOP | 1–2 秒（25fps 下 25–50 帧） | 首帧等待时间与带宽的折中；LL-HLS 分片依赖关键帧 |
| 调优 | `tune=zerolatency` | 关闭 look-ahead 等增加延迟的特性 |
| 码率 | CBR，或 CRF + `maxrate`/`bufsize` | 弱网下码率可预测 |
| 目标档位 | 720p @ 15–25fps，2–3 Mbps | 当前业务画面的够用档 |
| 硬件编码 | 有则用 `h264_nvenc` / `h264_qsv` | 降 CPU；不可用时回落 libx264 |

### 5. 编码器实现二选一

- **PyAV 进程内编码**：无子进程管理开销，帧对象直接送编码器；引入 PyAV 依赖；
- **FFmpeg 子进程管道**：进程隔离、崩溃不拖垮服务、参数调试直观；多一层管道拷贝与进程生命周期管理。

两者都可满足上述编码约束，选择留到实现任务（见 `harness/TASK_BOARD.md` 的 M08）按实测决定。工作区已装 FFmpeg 9.0.1（`tools/rtsp/installed-tools.json` 已登记 SHA-256）。

## 理由

### 为什么 ADR-001 的路线是错的

1. **MJPEG 没有帧间压缩，带宽随观看人数线性放大。** 720p25 每个观看者约 15–25 Mbps；同样画质的 H.264 约 2–3 Mbps，差 8–10 倍。10 个观看者：约 200 Mbps 对约 25 Mbps。而"一路流多人观看"正是本项目的核心场景 —— ADR-001 选的协议在自己的主场景上最不划算。
2. **把检测结果烧进画面，丢掉了结构化数据。** 现有 `detector.annotate()` 走 Ultralytics `results[0].plot()`，返回的是已经画好框的图像，结构化检测结果被丢弃。App 因此拿不到类别、置信度、坐标，做不了交互、统计和事件；多用户也无法各自决定是否叠加。必须重构为 `detect()` 返回结构化结果，叠加变成可选的下游步骤。
3. **把媒体解码栈放在了最难验证的一端。** 端侧自研 RTSP + H.264 解码（`third_party/rtsp-client-android`）把马赛克、积帧、Surface 尺寸、首个 IDR 门控这类问题压在 API 27 真机上，而这些问题在平台播放器/WebRTC 栈里本就是已解决的。M09-T23/T25/T26 三个任务都在为这条自研栈打补丁，已按 `supersede` 终止。
4. **缺分发层。** 服务端直接对每个订阅者出流，扇出、重连、弱网自适应全部要自研。MediaMTX 1.20.1 已在工作区、已登记哈希、已开启所需协议，没有理由重造。

### 为什么选 WHEP 而不是自定义信令

WHEP 是 WebRTC 播放侧的标准 HTTP 信令：一次 POST 交换 SDP 即可拉流，无需长连接信令服务器和自定义状态机。MediaMTX 原生支持，客户端实现面小。

### 被否决的方案

| 方案 | 否决原因 |
|---|---|
| 继续 MJPEG 到生产 | 带宽 8–10 倍劣势正好落在多人观看主场景上 |
| SRT 作为 App 主链路 | Android 播放端集成成本高，没有像 WebRTC 那样的成熟客户端生态；作为服务端之间的专用链路仍可保留 |
| 普通 HLS（非 LL） | 分片级延迟 6–30 秒，不满足实时监看 |
| RTMP 输出到 App | 延迟不占优，Android 端需额外播放器，且是采集侧协议 |
| 自研 UDP 私有协议 | 要自己解决拥塞控制、丢包恢复、NAT 穿透 —— WebRTC 已经解决 |
| 保留端侧 RTSP 解码 | 见上述理由 3 |

## 依赖组件

| 组件 | 版本 | 许可证 | 位置 |
|---|---|---|---|
| MediaMTX | 1.20.1 | MIT，Copyright (c) 2019 aler9 | `E:\aiyolo\tools\rtsp\mediamtx\1.20.1\mediamtx.exe`，SHA-256 `DC970F8E…1EBE53` |
| FFmpeg / FFprobe | 9.0.1 | 见发行版声明（essentials build） | `tools/rtsp/ffmpeg/9.0.1/…/bin/`，SHA-256 `FEC81AE0…DA2E9` |

已在 `tools/rtsp/mediamtx/1.20.1/mediamtx.yml` 核对开启的协议与端口：`rtsp: true`（`:8554`）、`rtmp: true`、`hls: true`（`:8888`，`hlsVariant: lowLatency`、`hlsSegmentCount: 7`、`hlsSegmentDuration: 1s`、`hlsPartDuration: 200ms`）、`webrtc: true`（`:8889`，`webrtcLocalUDPAddress: :8189`）、`srt: true`（`:8890`）。

## 影响

### 服务端

- 新增 H.264 编码环节和到 MediaMTX 的推流环节；
- `detector.annotate()` 必须重构为 `detect()` 返回结构化检测结果，叠加下移为可选步骤；
- 新增检测结果 WebSocket 旁路；
- 部署拓扑增加 MediaMTX 进程与 UDP 端口（`:8189`）、HTTP 端口（`:8888`/`:8889`）；
- 模型注册表当前只有单个全局 `activeServerModel`，多路流各自绑定模型需要改为按流绑定；
- M02-T03 的容量与资源指标需要在加入编码后重新测量，旧数字不再代表实际负载。

### App 端

- 需要从零建立网络层（当前工程内没有任何网络库，无 OkHttp/Retrofit）；
- 需要 WebRTC 播放能力和 WHEP 信令；
- `third_party/rtsp-client-android` 整个 Gradle 模块可以退役；
- 端侧 YOLO 保留，但只用于本地图片和相机预览帧。

### 保持不变的上层契约

`stream_id` 会话标识、`created/ingesting/outputting/error/closed` 状态、`yolo_enabled` 开关语义、服务端流状态/延迟/FPS/丢帧指标、断线由客户端重连、会话删除走 REST。

## 未验证项（不得当作已验证）

以下四项在本 ADR 中是**假设**，必须由后续任务用实测数据确认或推翻：

1. **libwebrtc 在 API 27 上的可用性与体积。** 预估 arm64 约 10 MB APK 增量，未实测；API 27 上的硬解码行为未验证。
2. **公网 NAT 穿透。** 局域网可直连；公网需要 STUN，可能需要 TURN 中继（TURN 会把带宽成本转回服务端）。拓扑与端口策略未定。
3. **加入编码后的单机并发容量。** 编码本身消耗 CPU/GPU，M02-T03 的旧容量数据不再成立，需重新压测。
4. **实测端到端延迟。** WHEP 链路的 P50/P95 尚无测量值，目标档位（要求 < 500ms）未经验证。

## 解冻与回退

- 若未验证项 1 证伪（libwebrtc 无法在 API 27 稳定工作），回退到 LL-HLS 作为 App 主链路，延迟目标随之放宽，本 ADR 的编码约束与单次编码架构不变；
- 若未验证项 2 在目标网络下无法解决，则限定部署在同一网络内，或引入 TURN 并重新核算带宽；
- 任何回退都必须新开 ADR 记录，不修改本文件的决策段。
