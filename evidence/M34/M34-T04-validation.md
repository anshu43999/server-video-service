# M34-T04 验证记录：直播分发配置、依赖与运维契约退役

日期：2026-10-15。任务：M34-T04。工程：`E:/aiyolo/server-video-service`。

## 结论与范围

本任务范围内的清理及自动化回归已完成；不代表 M34 全部完成，也不代表真实视频链路或容器部署已经验收。现行产品边界以 ADR-003 为准：保留视频源接入、PC 项目专用实时预览/视频墙、独立 YOLO 分析和正式告警；不恢复 PC 推流、移动直播/收流或 MediaMTX 播放分发。

执行前通过 Harness validate/status/next/show，并以 `start M34-T04 --owner codex` 绑定任务；依赖 M34-T03 已完成。既有工作区变更保留，未重置或提交 Git。

## 交付

- 移除发布器、发布编码器、旧输出容量模块及 Settings/启动入口中的分发配置；保留 OpenCV/FFmpeg 输入解码、JPEG 预览、YOLO、模型/证据/转换依赖。旧分发环境变量包括非法值不能重新启用发布。
- 媒体鉴权回调仅保留无条件 403 `live_video_retired` 的拒绝入口，不查询流或凭据。旧容量和播放器探测工具返回退役错误并退出 2，不访问网络、不启动发布子进程、不生成假容量结果。
- Compose 移除 MediaMTX 服务及分发端口，保留视频服务和模型转换器、四个业务卷、托管 PostgreSQL/MinIO 配置及必要出站网络；Kubernetes 删除对应媒体工作负载、Service、配置及凭据示例。历史媒体 YAML 移到仅供负向测试的夹具，不进入镜像。
- 本地 PowerShell 启动器移除媒体参数和启动逻辑，旧参数明确拒绝；保留 Windows PowerShell 5.1 所需 UTF-8 BOM。部署脚本取消宽泛 orphan 清理，部署前要求非空的本地验收记录文件；该检查不自动判定报告内容真实有效。
- 更新 API 协议、ADR、本地启动、安全、部署和升级回退文档；历史材料明确标注退役范围。升级手册说明旧实例不会随 YAML 删除自动退出，后续只能在批准窗口核验归属后精准处理，禁止删除业务卷/清库，禁止通过回退重新开放移动分发。
- 增加旧持久流无损兼容验证：两个项目同名流、RTSP/历史 websocket 来源、模型版本、revision、时间戳及完整字段在隔离 SQLite 中保留；重启恢复后配置完整不变。未执行业务数据库迁移。

## 真实执行的测试

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 最终后端回归，28 个模块 | 190/190 通过，91.256 秒 | `M34-T04-backend-verified.log` |
| PC 前端单元回归，17 个文件 | 132/132 通过 | `M34-T04-frontend-verified.log` |
| 修复后后端子集 | 77/77 通过，属于重复验证，不另算总覆盖 | `M34-T04-repair-tests.log` |
| 完成前 Harness 单元测试 | 30/30 通过 | `M34-T04-harness-tests.log` |
| 完成后 Harness 单元测试及状态门禁 | 30/30 通过；validate/render 通过；M34-T04 为 completed，M34-T05 可执行 | `M34-T04-harness-final.log` |
| Git 差异空白检查 | 通过，仅有 LF/CRLF 提示 | 本轮执行 `git diff --check`，未修改既有工作区内容 |
| Windows PowerShell 5.1 旧参数拒绝 | 通过，未启动服务 | 最终回归中 `test_local_launcher_has_no_media_process_or_parameters` |
| Bash 部署脚本语法 | `bash -n deploy/deploy.sh` 通过，未执行部署 | 最终回归中 `test_deploy_script_parses_without_running_docker` |

空白检查范围说明：产品/配置/测试/文档的定向 `git diff --check` 通过。最后把 Harness 生成的 `TASK_BOARD.md` 也纳入检查时，Git 对其中 6 行 Markdown 行尾双空格报告 trailing whitespace；这些双空格是现有 `harness.py` 渲染器用于硬换行的格式，本轮未改写渲染器或手工修改生成看板。完成记录和本验证报告的定向检查再次通过；不把包含生成看板的全范围检查记录为通过。

后端最终回归显式清空当前测试进程的 `DATABASE_URL`、`MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`，`PYTHONPATH=tests`，以工程 `.venv/Scripts/python.exe -m unittest ... -v` 执行。模块包括：

```text
test_mediamtx_deployment test_docker_deployment test_kubernetes_deployment
test_publisher test_encoder test_capacity test_player_compatibility_probe
test_transport_docs test_admin_preview test_analysis_only test_stream
test_detection test_playback test_output test_detections_ws
test_stream_config_persistence test_stream_restart_recovery
test_stream_model_binding test_server_alert_runtime test_project_stream_isolation
test_metrics test_metrics_api test_fault_recovery test_protocol
test_project_isolation_matrix test_dashboard_stats
test_multi_project_release_rehearsal test_local_project_baseline
```

测试覆盖静态 Compose/Kubernetes 拓扑、卷和出站保留、旧配置忽略、退役 API/工具、PC 预览权限与撤权、无人预览分析管线、流持久化/恢复、正式告警运行时及项目隔离。项目隔离矩阵中的媒体握手为独立 loopback 负向测试实例，不是部署 MediaMTX 分发服务。前端源码本轮未改，未把前一任务的构建或浏览器测试重复记为本轮成果。

## 初轮失败与修复

- `M34-T04-initial-tests.log`：70 项中 1 项失败。Windows PowerShell 5.1 以错误编码解析含中文的无 BOM 脚本；补回 UTF-8 BOM 后旧参数拒绝测试通过。
- `M34-T04-regression.log`：187 项出现 4 个 error。两处文档测试仍引用旧协议章节；看板测试遗漏对全局流配置存储的隔离，触发本机旧 PostgreSQL 表缺失 `project_id` 的 SELECT 失败，并产生后续清理 error。文档测试已改为内部序列化兼容章节；看板测试注入隔离 `StreamConfigStore(None)`，最终运行另显式清空外部存储环境变量。
- 初轮确实发生过业务数据库连接/SELECT 尝试，不能描述为全程未连接数据库；本轮没有为此迁移、清理或修改业务数据。保留所有失败日志以便追溯，最终 190 项日志不覆盖初轮失败证据。

## 验收限制与后续

1. 尝试 `docker compose --env-file .env.example -f compose.yml config --quiet` 时，本环境未找到 Docker 命令。因此 Docker Compose 原生插值/配置校验未执行成功；本轮通过的是 PyYAML 静态解析与配置契约测试，不能称作容器验收。未安装 Docker、未连接 Docker 守护进程、未部署容器。Kubernetes 同样仅做静态测试，未访问集群。
2. 未重启现有用户服务，未停止任何既有媒体实例，未修改防火墙，未迁移/清理业务数据库，未读取真实 `.env` 或密钥内容，未修改 Android 产品工程，未提交/推送 Git。移除的旧发布代码可由 Git 历史恢复，但不应重新启用旧功能。
3. PC 预览仍是 M34-T03 的最高 5fps/宽 1280 方案，不是 25/30fps 播放器。自动化用隔离存储、受控输入/推理和测试会话验证契约；不能替代真实摄像机、真实 YOLO、PostgreSQL、PC/API27 联合及长稳测试。
4. 下一任务 M34-T05 完成无人预览时正式告警持久化与 PC/移动独立提示闭环；M34-T06 完成真实本地联合验收与长稳。Android M101、原数据迁移 M100-T05 和审批 M33-T22 仍按原任务门禁执行，不因本任务关闭。完成本地验收后才允许进入部署。
5. 已通过 Harness CLI 完成 M34-T04；随后复验 Harness 单元测试 30/30、validate/render 均通过，show 确认 completed，next 列出可执行的 M34-T05。最终结果见 `M34-T04-harness-final.log` 与 `harness/records/M34/M34-T04.md`；未自动启动下一任务，这些状态检查不扩大本任务的验收范围。

操作及回退说明：`docs/media-retirement-upgrade.md`。
