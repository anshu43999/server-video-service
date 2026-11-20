# M33-T15 跨项目授权与数据隔离测试矩阵

日期：2026-10-13。测试范围：`server-video-service`。除双项目测试和验收证据外，本任务修复了默认 Compose 模板及 Kubernetes 生产配置允许匿名直连媒体的高风险缺口；没有修改 Android、在线业务库或 MinIO 对象。

## 金样身份

测试夹具通过真实 API 创建并登录以下身份：

| 身份 | 项目 A | 项目 B | 用途 |
| --- | --- | --- | --- |
| 平台管理员 | 显式平台入口 | 显式平台入口 | 项目创建、成员管理、平台目录 |
| 项目负责人 A | `PROJECT_OWNER` | 无成员（切换专项中显式加入为 `PROJECT_USER`） | 项目 A 写操作 |
| 项目负责人 B | 无成员 | `PROJECT_OWNER` | 项目 B 写操作 |
| 项目用户 A | `PROJECT_USER` | 无成员 | 项目 A 使用和告警处置 |
| 项目用户 B | 无成员 | `PROJECT_USER` | 项目 B 使用和告警处置 |
| 无成员账号 | 无成员 | 无成员 | ID 猜测和资源存在性隐藏 |
| 禁用账号 | 禁用前加入 B | 禁用 | 旧 Session 即时失效 |
| 设备凭据 A/B | 各自绑定单项目 | 各自绑定单项目 | 告警推送、能力和重放边界 |

## 覆盖矩阵

| 契约范围 | 直接证据 |
| --- | --- |
| REST 列表、详情、写操作、角色能力 | `test_identity_rest_lists_writes_guesses_and_roles`；现有 `test_project_authorization.py`、`test_project_management_api.py` |
| ID 猜测、无成员、禁用账号、404 不泄露 | `test_identity_rest_lists_writes_guesses_and_roles`；foreign/missing 项目响应逐项相等 |
| 双项目相同 `streamId`、运行时帧、WHEP、LL-HLS、MJPEG | `test_streams_media_websockets_and_model_downloads`；`test_project_stream_isolation.py`；`test_media_server_authorizes_direct_reads_against_live_membership`；`test_real_mediamtx_rejects_cross_project_whep_and_hls` |
| 检测/输出/告警 WebSocket、跨项目握手 | `test_streams_media_websockets_and_model_downloads`；`test_service_principals.py` |
| 模型分配、版本和项目授权下载 | `test_streams_media_websockets_and_model_downloads`；`test_project_model_assignments.py` |
| 告警列表、详情、证据、处置、导出和审计 | `test_alerts_objects_exports_disposition_and_audit`；`test_project_alert_isolation.py`、`test_project_reporting.py` |
| 对象存储项目分区、伪造 key、跨项目读取 | `test_alerts_objects_exports_disposition_and_audit`；`test_alert_evidence.py` |
| 设备/服务凭据项目绑定、请求体 projectId、能力与重放 | `test_devices_role_changes_project_switch_and_concurrent_requests`；`test_service_principals.py` |
| 成员变更即时生效、项目切换、并发查询 | `test_devices_role_changes_project_switch_and_concurrent_requests`、`test_same_account_can_switch_only_between_explicit_memberships`；`test_project_management_api.py` |
| MediaMTX 部署的匿名读取回归门禁 | `test_mediamtx_deployment.py::test_public_media_reads_are_never_anonymous_in_either_deployment`；`authMethod: http`，无匿名 read/playback 例外 |

所有跨项目资源请求均与随机不存在项目进行状态和错误体对照；因此不能通过猜测资源 ID 推断另一个项目存在。对象存储使用受控替身，断言 key 为哈希项目分区且不包含原始项目 ID；没有把替身结果当成在线 MinIO 可用性验收。

## 媒体端到端授权与限制

原 Compose 默认模板和 Kubernetes 配置的 `user: any` 允许不经过 FastAPI、只凭路径直接访问另一个项目的 WHEP/LL-HLS。这与项目隔离验收冲突，现已改为 MediaMTX `authMethod: http` 且无匿名例外。回调从 MediaMTX 的媒体路径提取项目和流，逐次校验真实账号 Session、账号状态、当前成员关系、项目生命周期和 `project.streams.view`；未知路径、无凭据的读取一律拒绝。平台管理员直接媒体读取也记录项目进入审计（同项目与同 Session 的 HLS 高频请求按 60 秒节流）。RTSP 发布和 MediaMTX API 使用独立 `MEDIAMTX_INTERNAL_TOKEN`，只有服务主体可操作已登记的发布路径；不得对公网发布其端口。非必要 MoQ 已关闭。

真实回环测试使用本机 MediaMTX v1.20.1、FFmpeg 以服务凭据发布 B 项目实时 H.264：B 用户可加载 LL-HLS 清单，A 用户和匿名请求直连 B 的 LL-HLS/WHEP 被拒绝；B 用户被移除后，同一旧令牌的下一次 HLS 请求被拒绝；有效 B 用户发送无效 SDP 到 WHEP 进入 SDP 校验而非媒体鉴权拒绝。匿名访问 MediaMTX 控制 API 被拒绝，内部服务凭据可查询发布中的项目流。额外单测证明跨项目路径的伪造发布、A 用户尝试 `publish/api` 动作均遭拒绝，且服务凭据不进入公开播放地址、指标及诊断 RTSP URL。该回环测试在没有两个工具二进制文件的环境条件跳过，不等同于 Android 播放器、网关、TLS 或 Kubernetes 现场验收。浏览器和 Android 的媒体客户端必须为 WHEP、HLS 清单、分片及刷新请求携带 Bearer Session；不能附加 HTTP 头的原生播放器需要在联合验收前适配，不允许回退匿名媒体访问。已经建立的 WebRTC 会话在撤权后的强制中断尚未验证，不能把“新请求即刻拒绝”表述为“旧连接瞬间断开”。

## 测试结果

- 专项矩阵：`.venv\\Scripts\\python.exe -m unittest discover -s tests -p test_project_isolation_matrix.py -q`，7 项通过，包含真实 MediaMTX/FFmpeg 直连。
- MediaMTX 配置回归：`.venv\\Scripts\\python.exe -m unittest discover -s tests -p test_mediamtx_deployment.py -q`，5 项通过。
- 既有项目授权/业务/流/告警/模型/报表/服务凭据回归：70 项通过，10 项条件跳过。
- 项目专项回归：将测试进程内 `DATABASE_URL`、`MINIO_ENDPOINT` 与 MinIO 凭据显式设为空后，`test_project_*.py` 共 77 项通过、10 项条件跳过；避免触碰线上数据库与 MinIO。
- 出版器、Docker、Kubernetes 和 MediaMTX 配置检查：分别 12、15、6、5 项通过。生产入口验证拒绝缺失/默认占位媒体服务密钥；RTSP 发布时密钥不进入对外播放 URL 或指标。
- 隔离环境全量后端回归：测试进程显式清空在线数据库和对象存储连接配置，`test_*.py` 共 588 项通过、31 项环境条件跳过；此轮完成后追加的密钥占位检查与鉴权请求长度限制，已分别通过对应部署单测（15 项）与双项目矩阵复跑（7 项）。
- Harness 单元测试：30 项通过；`harness.py validate` 通过。
- 直接继承机器 `.env` 的无范围全量测试曾触发 MinIO bucket location 的连接重试；发现后已中止，**没有把中断执行记为全量通过**。隔离环境重跑全量测试已通过。
- 已通过的测试退出码均为 0；测试使用内存 API、临时模型目录和受控对象存储，不写在线业务数据库。

M33-T15 只证明服务端授权和数据隔离测试矩阵；真实部署升级、媒体网络、管理后台浏览器和 Android 联合流程分别属于 M33-T16～T18。
