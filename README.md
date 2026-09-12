# Server Video Service

独立的服务器端视频流处理服务：接收移动端推送的 JPEG 帧（或拉取 RTSP/文件源），按需在服务器运行 YOLO，把结果编码为一路 H.264 交给媒体服务器分发给 App 和浏览器，并把结构化检测结果通过独立通道下发。

输出传输协议见 [docs/adr-002-production-transport.md](docs/adr-002-production-transport.md)：**WebRTC/WHEP 是唯一生产播放路径，LL-HLS 是过渡与回退，RTSP 只给诊断工具，MJPEG/WebSocket JPEG 降级为测试与诊断通道。** App 只播放服务端推理后的流，不在远程流上做推理。

告警引擎规格见 [docs/alert-engine-spec.md](docs/alert-engine-spec.md)（状态：冻结，机器可读契约 [docs/alert-engine.schema.json](docs/alert-engine.schema.json)）：**服务端与 App 共用同一份规格**，服务端实现远程视频流事件（`M11`），App 侧实现本地图片与相机事件（`M15`）。这是一个告警引擎，不是预警引擎，不做趋势外推与未来状态预测。双侧共用的一致性金样向量在 [docs/alert-engine-conformance/](docs/alert-engine-conformance/README.md)（29 条，服务端加载器 `tests/test_alert_engine_conformance.py`，App 侧原样复制执行）。

项目的正式定位、范围、需求、接口契约和验收标准见 [PRODUCT_REQUIREMENTS.md](PRODUCT_REQUIREMENTS.md)。该服务只承接视频流链路，不修改现有 `mobile-app/`，移动端图片分析和本地相机分析继续保持原方案。

启动后访问 `http://localhost:8080/` 可打开管理控制台；控制台用于人工查看流、切换 YOLO 和调整单路运行参数，移动端仍应使用独立 API/播放接口。

模型资产页现提供 **PT 上传与异步本机/WSL 转换**：PT 在服务端验证后可直接按流绑定；TFLite 单独转换并登记下载产物。配置现有虚拟环境、校准集、任务重试与当前 App 接线边界见 [本机模型转换说明](docs/local-model-conversion.md)。COCO 仅用于用户功能测试。

## 一键启动（Windows）

直接双击 `start-server.bat`。脚本会自动创建 `.venv` 并安装基础依赖，然后启动服务。

PowerShell 高级用法：

```powershell
.\start-server.ps1                 # 默认 8080 端口
.\start-server.ps1 -Port 8090      # 指定端口
.\start-server.ps1 -InstallYolo    # 同时安装 ultralytics YOLO 依赖
.\start-server.ps1 -Reload         # 开发模式，代码变更自动重载
.\start-server.ps1 -NoInstall      # 不安装依赖，仅使用已有虚拟环境
```

首次运行需要联网下载依赖；之后脚本通过 `.venv/.server-video-service-deps` 标记避免重复安装。未配置 `YOLO_MODEL_PATH` 时服务仍可启动并提供原始视频流，开启 YOLO 会显示模型未就绪提示。

## 开发任务 Harness

服务器项目有独立的任务驱动开发流程，位于 `harness/`：

```powershell
python harness/harness.py validate
python harness/harness.py status
python harness/harness.py next
```

当前主线是 `M07 生产传输协议重构与架构重定位`，`next` 会给出当前可启动的任务。完整任务拆分见 [harness/TASK_BOARD.md](harness/TASK_BOARD.md)，规则见 [harness/README.md](harness/README.md)。

## 功能

- 每个 `stream_id` 一个独立会话，支持多个客户端订阅。
- `POST /api/streams/{stream_id}/yolo` 手动开启/关闭 YOLO。
- YOLO 模型惰性加载，未安装 `ultralytics` 或模型文件不存在时服务仍可输出原始视频。
- 输入方式：
  - WebSocket 推送：`/api/streams/{stream_id}/ingest`，每条 binary message 是一张 JPEG/PNG。
  - 服务端拉流：创建流时传入 `source_url`（RTSP、HTTP、摄像头索引或本地文件）。
- 输出方式（目标形态，见 ADR-002）：
  - WebRTC/WHEP：生产播放路径，H.264，由 MediaMTX 提供（默认 `:8889`）。
  - LL-HLS：WebRTC 打不通时的回退路径（默认 `:8888`）。
  - RTSP：只给 VLC/ffprobe 等诊断工具（默认 `:8554`），不进 App。
  - 检测结果 WebSocket 旁路：结构化 JSON，与视频帧解耦。
- 测试与诊断通道（已实现，非生产输出）：
  - MJPEG：`GET /api/streams/{stream_id}/mjpeg`，用于管理页预览和自动化测试。
  - WebSocket JPEG：`/api/streams/{stream_id}/ws`，用于联调探针。

当前代码库已实现输入、YOLO 开关、MJPEG/WebSocket JPEG 输出和模型管理；H.264 编码、MediaMTX 推流、WHEP/LL-HLS 播放和检测结果旁路是 ADR-002 之后的实现任务，尚未落地。

## 快速开始

```powershell
cd E:\aiyolo\server-video-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

项目已内置从移动端迁移的 YOLO11n 开发模型 `models/yolo11n.pt`，安装 YOLO 依赖后新建视频流默认使用该模型。部署其他模型时设置 `YOLO_MODEL_PATH`，并安装 `requirements-yolo.txt`：

```powershell
pip install -r requirements-yolo.txt
$env:YOLO_MODEL_PATH='E:\models\best.pt'
```

模型转换工具：

```powershell
pip install -r requirements-convert.txt
python tools/convert_model.py --weights models/yolo11n.pt --format server --imgsz 640
python tools/convert_model.py --weights models/yolo11n.pt --format server --server-format pt --imgsz 640
python tools/convert_model.py --weights models/yolo11n.pt --format server --server-format both --imgsz 640
python tools/convert_model.py --weights models/yolo11n.pt --format mobile --imgsz 640
python tools/convert_model.py --weights models/yolo11n.pt --format all --imgsz 640
```

`server` 默认生成 ONNX 服务端候选模型；使用 `--server-format pt` 可复制一份可直接加载的 PT，使用 `both` 同时生成两者。`mobile` 使用与移动端一致的 LiteRT INT8 导出链生成 TFLite，`all` 两者都生成；每次转换同时生成带 SHA-256、源权重哈希、输入尺寸和工具平台信息的 Manifest。转换依赖只用于开发机，不进入运行服务镜像。若要在服务端激活 ONNX，需按目标 Python/平台额外安装 `requirements-onnx.txt`；PT 模型无需该运行时。

注意：Ultralytics 当前 LiteRT 导出器不支持 Windows 原生环境。Windows 上可正常生成 ONNX/PT；要生成移动端 TFLite，请在 WSL2 Ubuntu/Linux x86 或 macOS 中安装同一份 `requirements-convert.txt` 后执行 `mobile` 命令。工具会在不支持的平台返回明确错误，不会伪造 TFLite 产物。

也可以直接使用 Docker（将模型放入项目的 `models/best.pt`）：

```powershell
docker compose up --build
```

## API 示例

创建一个等待移动端推送的会话：

```http
POST /api/streams
Content-Type: application/json

{"stream_id":"巡检-001"}
```

开启 YOLO：

```http
POST /api/streams/巡检-001/yolo
Content-Type: application/json

{"enabled":true}
```

移动端将摄像头帧 JPEG 二进制写入 ingest WebSocket；诊断预览可访问：

```text
http://server:8080/api/streams/巡检-001/mjpeg
```

生产播放先调用 `GET /api/streams/{stream_id}/playback` 获取 MediaMTX 的 WHEP 地址（H.264），例如 `http://server:8889/巡检-001/whep`；WebRTC 不可用时回退 `http://server:8888/巡检-001/index.m3u8`。接口同时返回 RTSP 诊断地址及各协议当前可用性。

完整接口可打开 `http://server:8080/docs` 查看。

运维指标接口：`GET /api/metrics`，返回进程 CPU/内存、可选 NVIDIA GPU 和各视频流 FPS/延迟/丢帧指标。

## 媒体服务器

分发由 MediaMTX 1.20.1（MIT，Copyright (c) 2019 aler9）承担，已随工作区安装在 `E:\aiyolo\tools\rtsp\mediamtx\1.20.1\`，SHA-256 登记在 `tools/rtsp/installed-tools.json`。`mediamtx.yml` 中已开启：RTSP `:8554`、RTMP、HLS `:8888`（`hlsVariant: lowLatency`、`hlsSegmentCount: 7`、`hlsSegmentDuration: 1s`、`hlsPartDuration: 200ms`）、WebRTC `:8889`（`webrtcLocalUDPAddress: :8189`）、SRT `:8890`。

部署时媒体服务器与本服务一起编排；服务端不假设它已就绪，推流失败要能识别并重建。RTSP 端口只对诊断网络开放。

## 当前边界

服务端已实现 H.264 编码、MediaMTX 推流、播放地址接口和检测结果 WebSocket 旁路；MJPEG/WebSocket JPEG 仍仅用于管理页和自动化诊断。ADR-002 中的四项未验证假设（libwebrtc 在 API 27 的可用性与体积、公网 NAT 穿透、加入编码后的并发容量、实测端到端延迟）都还没有实测数据，不得当作已验证。生产环境需在前置网关增加鉴权、TLS 和限流。服务不会修改 `mobile-app/`。
