# M34-T04：分发退役升级、检查与受限回退

日期：2026-10-15。现行决策：[ADR-003](adr-003-analysis-alerts-only.md)。本轮只做静态配置和隔离回归，不执行容器部署、服务重启、防火墙修改、数据库迁移或业务数据清理。

## 1. 顺序与保留范围

先完成 M34-T05/T06、Android M101 相关本地验收，明确真实输入源、模型、PostgreSQL、PC 和 API27 的结果及长稳证据，再审批部署。配置解析、模拟推理或浏览器夹具不能替代本地真实验收。`deploy.sh up/pull-up` 要求环境变量 `AIYOLO_LOCAL_ACCEPTANCE_RECORD` 指向非空且已审阅的报告；脚本只检查文件存在，不自动认证报告内容。

保留 RTSP/HTTP/文件/摄像头拉取、OpenCV/FFmpeg 输入解码、受项目鉴权的设备/服务 ingest、PC 同源 JPEG 预览、YOLO、告警规则与证据；关闭预览页不停止推理。模型缺失只能验证原画面，不能宣称告警闭环可用。

不再包含 MediaMTX 服务、H.264 发布器、WHEP/LL-HLS/RTSP 输出、旧检测订阅。旧 `playback/mjpeg` 是 HTTP410，`ws/detections` 关闭1008，媒体鉴权回调始终403（read/publish/api均拒绝）。只有PC新 `/preview` 通道有效。

## 2. 配置与数据兼容

- 从运营配置中移除 `MEDIAMTX_*`、`MEDIA_*`、`MTX_*`、`MAX_OUTPUT_SUBSCRIBERS` 和旧 `DIAGNOSTIC_*`/`SRT_*` 分发项；不要删除 `RTSP_TRANSPORT`、输入源凭据、数据库/MinIO/转换器/模型配置。旧应用 `.env` 中分发字段由 Settings 忽略，非法旧数值也不阻止读取；部署脚本的占位符检查仍要求清除无用旧占位值。
- 不改 `stream_configs` 表结构，不重建/删除旧流。保留 `(project_id, stream_id)`、source_type/source_url、启停、YOLO参数、模型版本、revision、时间戳；旧 `websocket` 流作为既有授权 ingest 配置保留，不自动转成 RTSP。启用流按原有恢复逻辑启动，停用流仍可查询。
- 保留告警的 `SERVER_STREAM`、`streamId`、规则快照、处置、投递记录、证据对象及已存短视频；不批量重写来源类型，不重新导入旧告警。
- 保留 `model-data/evidence-data/converter-data/calibration-data` 四个卷和模型只读挂载；保留托管 PostgreSQL 和私有 MinIO。禁止为清理分发执行 `down -v`、删 PVC、清库、删除对象或重建模型卷。
- Compose 的 `media` 网络名继续存在，仅用于摄像机、托管数据库/MinIO等出站连接；`control` 保持内部网络。不能把两个网络都封闭导致输入/存储断连。

## 3. 旧实例的人工维护步骤（未在本轮执行）

删除 YAML 不会停止已存在的媒体进程；旧 Compose orphan 和 Kubernetes 对象必须在批准的维护窗口单独处理。

1. 记录当前不可变镜像、Compose project/文件、Kubernetes context/namespace、对象 UID、挂载和进程 PID。按 M33-T17 手册完成备份与独立恢复验证；隔离验收不能授权线上停写。
2. 审查 `/etc/aiyolo/compose-overrides.list` 及调度启动项，移除本系统旧媒体服务/端口/环境覆盖。其他系统和工作区输入测试源可能也使用 MediaMTX，不能按进程名一刀切停止。
3. 只读核验 Compose 服务归属，先列出该项目的旧媒体容器，再针对确认过的单个容器 ID 停止。示例中的占位值必须由运维核验替换：

   ```bash
   docker ps -a --filter label=com.docker.compose.project=CONFIRMED_PROJECT --filter label=com.docker.compose.service=mediamtx --format '{{.ID}} {{.Names}} {{.Status}}'
   docker inspect --format '{{json .Config.Labels}} {{json .Mounts}}' CONFIRMED_MEDIA_CONTAINER_ID
   docker stop CONFIRMED_MEDIA_CONTAINER_ID
   ```

   保留停止容器便于核查；确认日志/配置已安全留档且没有业务卷依赖后，才可单独 `docker rm CONFIRMED_MEDIA_CONTAINER_ID`，不加 `-v`。新部署脚本不再使用 `--remove-orphans`，避免清掉不属于本次任务的实例。
4. Kubernetes：先核验准确集群和 `saas-prod` 命名空间的 `deployment/aiyolo-mediamtx`、`service/aiyolo-mediamtx`、`service/aiyolo-mediamtx-public`、`configmap/aiyolo-mediamtx-config`；批准后逐项停用/移除这些对象。`kubectl apply -k` 不会自动清理旧对象；不要使用宽泛的 namespace 删除或未经审查的 `--prune`，不要动 PVC/Secret/其他服务。
5. 经归属确认后关闭旧分发入站端口（8888、8889、8189/UDP、8554、9997、8890/UDP）；不要关闭输入摄像机、外部数据库/MinIO的出站访问。Windows 旧 `start-server.ps1 -WithMediaMtx` 子进程也需按其 PID/命令行/端口核验后手工停止；新版启动脚本不会终止未知旧进程。
6. 使用已通过本地验收的镜像/配置发布两个服务，复验健康、登录/项目权限、源恢复、PC预览、无人预览分析、正式告警和证据。只看容器健康不算视频/告警验收通过。

## 4. 监控与健康

容器健康只检查应用 `/healthz`（包括已配置数据库连接），转换器保留独立健康检查，MinIO用既有只读健康验证。监控不得再等待 MediaMTX、发布进程、播放器数量或媒体端口。

关注 `frames_received/frames_processed/frames_dropped/frames_fallback`、输入/推理错误、模型授权/可用性、`alert_error` 及持久化/投递状态。老 API 的 `publish_state=retired`、`frames_published=0`、`viewers=0` 仅用于响应兼容，不表示故障，也不统计PC观看人数；旧 `outputting` 枚举仅作历史兼容，分析态为 `analyzing`。PC预览无新帧204并清空画面，不缓存上一次图像冒充在线。

## 5. 回退门禁

配置清理本身不需要数据库迁移，数据库与四个卷保持不变。回退仅可选择与当前数据结构兼容、已通过 ADR-003 边界测试的镜像或修复版本；不能因为功能回退重启 MediaMTX、重新打开旧播放端口或恢复移动直播。不能仅设置 `MEDIAMTX_ENABLED=false` 就把仍含发布器的历史版本判为安全。

如必须评估 ADR-003 以前版本，只能先在隔离环境恢复快照并验证；恢复移动直播需用户另行明确改变需求。未获得授权时停留在当前安全版本或维护状态，不恢复旧分发。涉及多项目数据库降级的恢复点、停写和新写入处置仍严格遵守 [M33-T17](m33-t17-release-runbook.md)，不因本任务豁免。

## 6. 自动化证据边界

`test_mediamtx_deployment`、`test_docker_deployment`、`test_kubernetes_deployment` 验证静态拓扑/配置；`test_publisher/test_encoder/test_capacity/test_player_compatibility_probe` 验证旧实现不可加载、旧工具失败、输入/证据依赖保留；预览、分析、流持久化与项目隔离测试继续运行。旧 MediaMTX 配置只保留在 `tests/fixtures/retired-mediamtx.yml`，用于回调拒绝测试且不进入镜像。历史容量、协议和任务完成记录保留，不可据此宣称新链路真实验收通过。
