# Server Video Service

独立的服务器端视频流处理服务：接入 RTSP/文件等视频源，在服务器运行 YOLO 与正式告警规则，提供按项目隔离的 PC 实时预览；符合规则的告警持久化后由告警功能展示和提示。

当前视频边界见 [ADR-003](docs/adr-003-analysis-alerts-only.md)：**保留后台/PC接入、实时预览和YOLO分析；取消PC推流及移动端远程视频/直播收流，不再通过MediaMTX向移动端分发。** PC专用预览使用同源登录Cookie和当前项目权限，最高5fps/宽1280；关闭YOLO仍可看原画面。旧播放接口继续退役。M34/M101仍在实施，Android清理、告警闭环及真实三端验收不能视为已完成；ADR-002中的分发方案仅作历史参考。

告警引擎规格见 [docs/alert-engine-spec.md](docs/alert-engine-spec.md)（状态：冻结，机器可读契约 [docs/alert-engine.schema.json](docs/alert-engine.schema.json)）：**服务端与 App 共用同一份规格**，服务端实现远程视频流事件（`M11`），App 侧实现本地图片与相机事件（`M15`）。这是一个告警引擎，不是预警引擎，不做趋势外推与未来状态预测。双侧共用的一致性金样向量在 [docs/alert-engine-conformance/](docs/alert-engine-conformance/README.md)（29 条，服务端加载器 `tests/test_alert_engine_conformance.py`，App 侧原样复制执行）。

项目的正式定位、范围、需求、接口契约和验收标准见 [PRODUCT_REQUIREMENTS.md](PRODUCT_REQUIREMENTS.md)。该服务只承接视频流链路，不修改现有 `mobile-app/`，移动端图片分析和本地相机分析继续保持原方案。

启动后访问 `http://localhost:8080/` 会跳转到 `/admin/` Vue 管理控制台；控制台用于查看流、切换 YOLO 和调整单路运行参数，移动端使用项目告警接口而非播放接口。前端源码和业务服务分别位于 `admin-web/` 与 `app/`，采用 [ADR-004](docs/adr-004-admin-frontend-engineering.md) 的同源部署架构。先完成本地真实验收，再进行容器部署。

## 管理前端开发与构建

Vue 3 + TypeScript + Vite 工程位于 `admin-web/`，要求 Node.js 22.12+。首次安装及验证：

```powershell
cd E:\aiyolo\server-video-service\admin-web
npm ci
npm run typecheck
npm run test
npm run build          # /admin/ 产物写入 dist/
npm run build:preview  # /admin-next/ 产物写入 dist-preview/
```

本地联调先启动 FastAPI，再在另一个终端执行 `npm run dev`，打开 `http://127.0.0.1:5173/admin-next/`。Vite 同源代理 `/aiyoloapi`（含 WebSocket）和 `/healthz` 到 `ADMIN_API_TARGET`，默认 `http://127.0.0.1:8080`；该配置只接受不含账号、路径或查询参数的 HTTP(S) origin。

`ADMIN_FRONTEND_MODE` 默认 `vue`，`/admin/` 使用 `dist`；产物缺失则启动失败并提示构建命令，不静默切回旧页面。本机首次运行或更新前先在 `admin-web/` 执行 `npm ci`、`npm run build`。容器镜像通过独立 Node 阶段执行锁文件安装、测试和两套构建，Python 运行层不包含 Node.js。

只要 `dist-preview/index.html` 存在，FastAPI 就会提供独立 `/admin-next/` 预览。应整体发布同一次构建的 HTML 和 assets，HTML 使用 `no-cache`，带内容哈希的资源使用一年 `immutable` 缓存，缺失资源为 404；网关不能把 API 错误改为 SPA HTML。旧前端已归档到本机 `E:\aiyolo\archives\server-admin-legacy\20261009-M32-T11` 并从产品目录删除，当前仅支持 `ADMIN_FRONTEND_MODE=vue`。历史查询与带备份恢复见 [本地档案说明](../archives/server-admin-legacy/README.md)，详细验证命令和缓存策略见 [管理前端发布与回退](docs/admin-frontend-release.md)。

模型资产页现提供 **PT 上传与异步本机/WSL 转换**：PT 在服务端验证后可直接按流绑定；TFLite 单独转换并登记下载产物。配置现有虚拟环境、校准集、任务重试与当前 App 接线边界见 [本机模型转换说明](docs/local-model-conversion.md)。COCO 仅用于用户功能测试。

## 一键启动（Windows）

先构建上文 Vue 产物，再双击 `start-server.bat`，或在本工程目录执行：

```powershell
.\start-server.ps1 -NoInstall       # 使用已有虚拟环境，默认 8080
.\start-server.ps1 -InstallYolo     # 需要时安装 YOLO 依赖
.\start-server.ps1 -Port 8090
.\start-server.ps1 -Reload
```

首次安装需要联网；无模型时 PC 可以看原画面预览，YOLO 分析和告警要求可用、已授权模型。脚本不再启动分发进程；旧 `-WithMediaMtx` / `-Media*` 参数会被拒绝，旧输出环境变量被忽略。

本地真实 RTSP 验收可以使用既有的摄像机地址；若使用工作区的文件循环测试源，在工作区根目录单独运行 `tools/rtsp/start_rtsp_video.ps1 -NoAdbReverse`，再在本工程执行 `start-server.ps1 -NoInstall`。测试源作为输入，不是后台的输出分发服务；不要误停共享的摄像机源，也不要打开 Android 直播。

PC 登录后进入明确项目，在“视频流管理”创建安全字符 ID（如 `inspection-001`），配置 RTSP 输入地址并按权限绑定模型。视频墙和流详情通过同源 Cookie 查看实时 JPEG 预览，最高 5fps、宽1280；切模型、撤权、断流与无人预览均需验证。移动端只使用服务地址访问模型与告警功能，不填写媒体地址。

## 开发任务 Harness

App 全量 APK 升级的自有上传接口、MinIO 版本固定、运行配置和恢复流程见 [APK 上传说明](docs/app-apk-upload.md)。默认关闭。
第三方公开 HTTPS 链接的登记、逐跳核验和临时文件清理见 [外链 APK 说明](docs/app-apk-external.md)；发布下载和 Android 安装流程仍在后续任务中。

服务器项目有独立的任务驱动开发流程，位于 `harness/`：

```powershell
python harness/harness.py validate
python harness/harness.py status
python harness/harness.py next
```

当前视频范围由 `M34` 与 Android `M101` 跟踪，`next` 会给出可启动的任务。完整任务拆分见 [harness/TASK_BOARD.md](harness/TASK_BOARD.md)，规则见 [harness/README.md](harness/README.md)。

## 功能

- 以 `(project_id, stream_id)` 隔离配置、运行会话、模型绑定与告警来源；重启恢复启用流，保留停用流和历史记录。
- 平台账号、项目空间、成员关系和项目权限持续生效；项目负责人维护源/参数，项目用户按权限使用模型、预览和告警功能。
- 支持 RTSP/HTTP/文件/摄像头输入，以及已鉴权的服务/设备 ingest；不提供 PC 或 Android 推流界面。
- YOLO 使用 latest-only 和独立限速；关闭或模型故障不取消 PC 原画面预览。无人观看时分析与正式告警仍运行。
- PC 同源快照预览/视频墙；不提供 WHEP、LL-HLS、RTSP 分发、通用 MJPEG 或逐帧检测 WebSocket。
- 告警按规则及冷却去重持久化，PC/移动端从告警功能查询、提示、处置和读取受保护证据。
- 移动端旧数据审批功能与数据表已移除；旧数据不读取、不迁移。升级到当前版本会删除旧审批相关数据库表。
- 保留模型资产、转换、签名、项目分配、证据与运行状态；正式链路的联合验收仍由后续任务执行。

## 快速开始

```powershell
cd E:\aiyolo\server-video-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

模型权重不作为默认部署保证。安装 `requirements-yolo.txt`，通过模型资产登记可用的模型并按项目分配、按流绑定；默认模型路径可用 `YOLO_MODEL_PATH` 设置：

```powershell
pip install -r requirements-yolo.txt
$env:YOLO_MODEL_PATH='E:\models\best.pt'
```

服务端统一使用 CPU：`requirements-yolo.txt` 包含 CPU 版 PyTorch/TorchVision 和兼容版本约束，视频推理、按流切换模型、PT 校验、ONNX/LiteRT 导出与 TFLite 复验均不使用显卡。旧 `YOLO_DEVICE=auto` 或 GPU 配置按 CPU 处理。Linux 镜像会执行 GPU 依赖审计与 CPU NMS 冒烟测试；重建和升级说明见 [Docker CPU 运行说明](docs/docker-deployment.md#cpu-only)。

模型转换工具：

```powershell
pip install -r requirements-convert.txt
python tools/convert_model.py --weights models/yolo11n.pt --format server --imgsz 640
python tools/convert_model.py --weights models/yolo11n.pt --format server --server-format pt --imgsz 640
python tools/convert_model.py --weights models/yolo11n.pt --format server --server-format both --imgsz 640
python tools/convert_model.py --weights models/yolo11n.pt --format mobile --imgsz 640
python tools/convert_model.py --weights models/yolo11n.pt --format all --imgsz 640
```

`server` 默认生成 ONNX 服务端候选模型；使用 `--server-format pt` 可复制一份可直接加载的 PT，使用 `both` 同时生成两者。`mobile` 使用与移动端一致的 LiteRT INT8 导出链生成 TFLite，`all` 两者都生成；每次转换同时生成带 SHA-256、源权重哈希、输入尺寸和工具平台信息的 Manifest。转换依赖只进入开发机和独立转换器镜像，视频服务镜像仅保留推理与 LiteRT 复验依赖。若要在服务端激活 ONNX，需按目标 Python/平台额外安装 `requirements-onnx.txt`；PT 模型无需该运行时。

注意：Ultralytics 当前 LiteRT 导出器不支持 Windows 原生环境。Windows 上可正常生成 ONNX/PT；要生成移动端 TFLite，请在 WSL2 Ubuntu/Linux x86 或 macOS 中安装同一份 `requirements-convert.txt` 后执行 `mobile` 命令。工具会在不支持的平台返回明确错误，不会伪造 TFLite 产物。

本地启动不需要 Docker 或 MediaMTX。先完成真实视频源、模型、PostgreSQL、PC 和 Android 的本地验收；本轮静态配置测试不是该验收的替代品。

## Linux 服务器部署

根目录唯一 `compose.yml` 只编排 `video-service` 与独立 `model-converter`。PostgreSQL 和 MinIO 仍为外部服务；保留四个命名卷、只读模型挂载、非 root/资源限制/健康检查与日志轮转。生产启动禁止自动数据库迁移。

部署步骤见 [Docker 部署说明](docs/docker-deployment.md)，旧部署须先阅读 [分发退役升级/回退](docs/media-retirement-upgrade.md)。`deploy.sh up/pull-up` 需要运维提供已经审阅的 `AIYOLO_LOCAL_ACCEPTANCE_RECORD`；这是人工验收门禁，不代表脚本能判断报告真假。本地验收完成前只做静态校验，不执行构建、启动、推送或集群变更。

服务器私有挂载清单仍由 `/etc/aiyolo/compose-overrides.list` 维护。升级前检查它不含旧媒体分发服务、端口和环境变量；不要删除存储卷，也不要用旧镜像回退重新开启移动直播。

## API 示例

先登录并选择有权限的项目，使用明确的项目路由：

```http
POST /aiyoloapi/projects/{project_id}/streams
Content-Type: application/json

{"stream_id":"inspection-001","source_url":"rtsp://camera.example/live"}
```

按当前项目授权绑定模型，再向 `/aiyoloapi/projects/{project_id}/streams/inspection-001/yolo` 发送 `{"enabled":true}`。不要在日志中保存完整输入凭据。

PC 同源登录 Cookie 访问 `GET /aiyoloapi/projects/{project_id}/streams/inspection-001/preview`；有效画面返回 200 JPEG，无帧/断流返回 204，Bearer 请求拒绝。接口定义见 [项目视频契约](docs/project-stream-isolation.md) 和 `/docs`。

旧 `playback/mjpeg` 返回 410，旧 `ws/detections` 关闭 1008；旧媒体鉴权回调无条件 403。兼容字段 `publish_state=retired`、`frames_published=0`、`viewers=0` 不是健康故障，也不是 PC 观看人数。监控应观察输入/处理帧、模型与告警错误。

## 当前边界

本地真实模型/摄像机、无人预览告警提示、跨项目隔离、API27 及长稳验收仍由 M34-T05/T06、M101 等后续任务承接。本轮不修改 Android，不部署容器。历史 H.264/MediaMTX 性能记录不证明当前系统容量或验收完成。
