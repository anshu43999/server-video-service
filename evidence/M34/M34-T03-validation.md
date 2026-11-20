# M34-T03 PC实时预览范围修正与本地回归

日期：2026-10-15。任务：M34-T03。结论：本任务代码及下述自动化验收通过，不代表整个M34/M101或生产部署已验收。

## 用户确认与实施边界

- 用户再次确认保留后台/PC接入视频源、实时查看和YOLO分析，只取消PC推流和移动远程视频功能。
- 修订ADR-003、M34大任务及未完成T03/T04/T05/T06的定义；T04现在依赖T03，防止清理分发时再次误删PC预览。T01/T02既有完成记录不改写。
- 保留输入拉流、YOLO/规则/告警持久化；不恢复MediaMTX发布器、H.264发布编码器或旧移动MJPEG/JPEG/WHEP/HLS/RTSP/检测订阅通道。
- 新增项目专用`GET .../streams/{stream_id}/preview`，同源后台登录Cookie＋`project.streams.view`鉴权，每次请求及编码后复验。Bearer（即使同时携带有效Cookie）、匿名/无效Cookie、跨站请求、外项目、撤权、停用/归档项目均拒绝。Cookie通道不是物理设备识别，合法用户通过浏览器登录后台仍可按项目权限预览。
- PC预览按需获取最新快照，最高5fps、宽1280，多个观看者共享单流短时编码缓存；没有观看者不编码预览，推理/规则/告警不依赖预览。关闭YOLO可看原画面，开启有效模型后可显示相应帧的标注。该方案不是25/30fps播放器。
- 来源超过3秒无帧返回204；客户端清空画面并恢复轮询；断网或超时不保留冻结画面。YOLO标注限当前有效代次及2秒内的结果，切模型/关闭/撤权后不展示旧标注。页面退出或项目切换取消请求、释放图片；已送达浏览器的图像无法远程收回。
- Vue视频流工作台和视频墙均使用新预览，移除播放地址、分发诊断、移动推流来源选项及检测WS；保留配置、模型、状态、正式告警和证据。按frontend-design技能复查桌面/窄屏截图，修正ElButton包装层导致流名称被压缩不可见的问题，并增加名称宽度断言；沿用原有后台样式。
- 构建`dist`及`dist-preview`，两套本地后台入口同步。归档旧管理页面未恢复、未修改。

## 真实执行的自动化检查

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 后端核心/项目/推理/故障/旧出口与新预览 | 137/137，69.745s | M34-T03-backend-verified.log |
| 其中PC预览专测 | 19项，包含真实JPEG编码/尺寸/缓存、原帧/标注、权限与在途撤销 | tests/test_admin_preview.py及上述日志 |
| 前端单元测试 | 132/132，17文件 | M34-T03-frontend-verified.log |
| 类型检查＋生产构建 | 通过 | M34-T03-build-release.log |
| 类型检查＋预览入口构建 | 通过 | M34-T03-preview-release.log |
| 本机Chrome生产产物浏览器回归 | 28/28，44.5s | M34-T03-browser-verified.log |
| Harness单测 | 30/30 | M34-T03-harness-run1.log；完成后另记M34-T03-harness-final.log |
| 目标tracked diff空白检查 | 通过，仅CRLF提示 | `git diff --check -- app/main.py app/stream.py README.md harness/task-state.json` |

后端命令（工作目录server-video-service，`PYTHONPATH=tests`）：

```powershell
./.venv/Scripts/python.exe -m unittest test_admin_preview test_analysis_only test_stream test_detection test_playback test_output test_detections_ws test_stream_config_persistence test_stream_restart_recovery test_stream_model_binding test_server_alert_runtime test_project_stream_isolation test_metrics test_metrics_api test_fault_recovery test_protocol test_project_isolation_matrix -v
```

前端命令（工作目录admin-web）：`npm run test`、`npm run build`、`npm run build:preview`；设置`PLAYWRIGHT_CHROMIUM_EXECUTABLE=C:/Program Files/Google/Chrome/Application/chrome.exe`后执行`npm run test:e2e:production -- streams.spec.ts dashboard.spec.ts projects.spec.ts --workers=2 --output=test-results-m34-pc-preview-final`。

浏览器覆盖桌面/390px窄屏、源创建/编辑/停启/删除、实时预览、YOLO关闭原画面、断流204清屏和恢复、重连、视频墙、切流迟到响应、离页释放、双项目切换、撤权和退出登录；断言页面不请求旧播放/检测通道。主要截图：`M34-T03-streams-desktop.png`、`M34-T03-streams-narrow.png`、`M34-T03-dashboard-desktop.png`、`M34-T03-dashboard-narrow.png`、`M34-T03-project-1440.png`、`M34-T03-project-390.png`。

## 失败与修复保留

- `M34-T03-backend-run1.log`：新增测试使用2560px输入，违反既有1920×1080上限；成员删除测试缺expectedRevision。修正测试夹具到合法输入/乐观锁版本，不放宽产品限制。
- `M34-T03-backend-final.log`：旧MediaMTX本机HTTP鉴权握手回归超时；授权沙箱外重跑135项通过（`backend-recheck`），最终完整137项复验通过（`backend-verified`），未通过跳过该测试掩盖问题。
- `M34-T03-browser-run1.log`：Playwright默认浏览器未安装，28项没有执行到页面。使用本机已安装Chrome后28项通过（`browser-run2`），最终布局/客户端修改后再次28项通过（`browser-verified`）；没有安装新浏览器或删除旧失败日志。

## 验收限制与下一步

- 浏览器测试使用真实Chrome/构建产物/本地测试HTTP服务，但业务返回由Playwright测试夹具提供。它不是实际摄像机或真实YOLO全链路证明。新预览API/项目授权使用真实处理器和内存隔离账号；JPEG编码是真实OpenCV，YOLO结果为测试桩。
- 核心回归包含真实MediaMTX拒绝握手及SQLite告警持久化，不能替代真实YOLO＋PostgreSQL＋PC＋API27的本地联调与持续运行。该门禁仍由M34-T06/M101-T04完成，不能先部署容器。
- M34-T04清理发布配置/依赖/旧运维文档，T05完成独立告警提示闭环，T06真实联合验收。Android M101产品代码及任务本轮未修改；其无直播要求限定Android，不影响本次PC预览。
- 平台管理员访问预览沿用项目访问审计；多路/多人并发的数据库审计写入量与性能需在T06长稳验收中观测，不能据此声明容量指标已达标。
- 未读取或修改业务凭据、未迁移/删除业务数据库、未重启用户服务、未部署容器、未提交或推送Git；保留工作区原有未提交改动。
