# M34-T02 后端分析链路与直播出口退役验证

日期：2026-10-15。范围仅为M34-T02，不能作为PC、Android或三端完整验收通过。

## 已实现

- StreamSession不再创建MediaMTXPublisher，不执行发布、观看者查询或预览JPEG编码；YOLO关闭只接收输入计数，不转发原始视频。
- 保留OpenCV输入解码、受保护输入、latest-only与分析限速、流配置恢复、项目归属、模型绑定和正式告警运行时。新增analyzing状态，旧发布指标固定retired/0，不伪装连接成功。
- 旧项目及兼容playback/mjpeg入口统一410/live_video_retired，无流查询或播放URL；JPEG/detections WebSocket统一关闭1008。旧MediaMTX鉴权回调拒绝read/publish/api，即便旧开关仍开启也不能通过应用恢复直播分发。
- 推理任务捕获generation，关闭/重开YOLO、换模型、撤权或关闭会话时拒绝迟到结果。告警处理失败以脱敏状态呈现，后续输入可恢复。
- 移除旧输出测试的成功播放预期，改为退役负向测试；保留模型、输入、证据及项目隔离覆盖，未删历史失败日志。

## 测试与结果

核心命令（cwd为server-video-service；PYTHONPATH=tests）：

```powershell
./.venv/Scripts/python.exe -m unittest test_analysis_only test_stream test_detection test_playback test_output test_detections_ws test_stream_config_persistence test_stream_restart_recovery test_stream_model_binding test_server_alert_runtime test_project_stream_isolation test_metrics test_metrics_api test_fault_recovery test_protocol test_project_isolation_matrix -v
./.venv/Scripts/python.exe -m unittest test_project_alert_isolation test_alert_delivery test_alert_disposition test_alert_persistence test_alert_lifecycle test_alert_evidence test_alert_engine_operators test_alert_engine_conformance -v
```

- 核心回归118/118通过，68.212秒：`M34-T02-focused-final.log`。包括真实本机MediaMTX HTTP鉴权握手的HLS/WHEP和内部API拒绝，不是只断言代码字符串。测试进程退出并释放自身资源。
- 告警/项目隔离回归51/51通过，9.028秒：`M34-T02-alert-regression-run2.log`。
- 无播放器消费者时，StreamSession接入桩推理结果，经真实ServerAlertRuntime规则、SQLite持久化及JPEG证据落盘：首帧不告警、达到阈值后只入库/通知一次，重新连接数据库仍可读取，另一项目不可见。此测试不等同于真实YOLO模型和PostgreSQL三端验收。
- 验证latest-only最新帧、限速、关停/重开/重绑/撤权/关闭竞态、模型不可用、告警失败恢复、同流ID双项目及旧开关开启仍不发布。
- `git diff --check`目标文件通过，仅现有Windows换行提示。

## 失败与修复记录

- 初次新增测试错误地直接设置只读load_error属性，改为受控测试故障字段后通过（分析run2日志）。初次模块式发现路径不匹配，改用tests目录导入。
- `M34-T02-focused-run1.log`：109项中1项metrics夹具尝试校验本机旧业务库schema；补齐该API单测的schema隔离后run2/final通过。未迁移或修改业务数据库。
- `M34-T02-alert-regression-run1.log`：告警API夹具启动时尝试恢复本机业务库旧stream_configs表，缺project_id，导致setup及cleanup错误；该测试显式使用内存流配置存储后run2通过。没有绕过产品schema校验、没有升级业务库。
- 其余阶段日志保留，最终通过不能掩盖首次失败。

## 遗留范围与上线风险

- M34-T03：PC仍有旧预览/播放诊断/视频墙和请求，需修改Vue及旧管理页面，并做浏览器验收。
- M34-T04：旧发布器模块、容量探针、MediaMTX部署/端口/环境变量及旧运维文档仍待清理；本任务只确保运行中的业务StreamSession不调用它们。不得将此状态直接用于部署。
- M34-T05/T06、Android M101：独立告警提示、App入口/SDK移除、真实YOLO/PostgreSQL/PC/API27与长稳联合验收尚未完成。
- 原M100-T05和M33-T22数据迁移/审批验收保留，未假完成；本地验收始终先于容器部署。
- 本轮不重启用户服务、不执行部署、不提交或推送Git。
