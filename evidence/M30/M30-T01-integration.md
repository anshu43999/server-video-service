# M30-T01 管理后台真实视频流联调证据

- 日期：2026-09-15
- 输入发送端：`E:\aiyolo\tools\rtsp\start_rtsp_video.ps1`
- 输入地址：`rtsp://127.0.0.1:18554/file-test`
- 管理后台：`http://127.0.0.1:8080/admin/`
- 正式测试流：`file-test-backend`

## 真实链路

`FFmpeg 文件循环源 -> 输入 MediaMTX :18554 -> server-video-service 拉流/处理 -> FFmpeg H.264 发布 -> 输出 MediaMTX :19554 -> WHEP/LL-HLS/RTSP`

输入源经 `ffprobe` 确认为 H.264 Constrained Baseline、1280x720、25 FPS、yuv420p。后台流在联调中从零持续增长到 494 个接收帧和 493 个发布帧，`state=ingesting`、`publish_state=connected`，且无输入或发布错误。

输出端点：

- WHEP：`http://127.0.0.1:18889/file-test-backend/whep`
- LL-HLS：`http://127.0.0.1:18888/file-test-backend/index.m3u8`
- RTSP 诊断：`rtsp://127.0.0.1:19554/file-test-backend`

LL-HLS 返回有效 `#EXTM3U`，输出 RTSP 经 `ffprobe` 确认为 H.264 Baseline Level 4.0。受后台会话鉴权保护的 MJPEG 预览返回 HTTP 200 和持续 multipart 图像数据。

## 管理页面验收

浏览器中的管理后台显示 `Live API 已连接`，真实流卡片和现场彩条画面可见，发布状态显示 `CONNECTED`，WHEP 显示“可用”，LL-HLS 显示“可回退”，RTSP 诊断地址可见。

通过“新建视频流”表单创建了临时流 `m30-browser-probe`，输入上述 RTSP 地址后，其接收帧从 0 增长到 419，状态由 `IDLE` 变为 `CONNECTED`，WHEP 和 LL-HLS 均转为可用。随后通过真实 API 删除该临时流，保留正式测试流。

页面契约测试覆盖真实创建、刷新、YOLO 开关、置信度与最大 FPS 更新、删除、同源 MJPEG 预览，以及被选流消失后的选择恢复。Demo 模式仍只操作本地演示数据。

## 可复现启动

`start-server.ps1 -WithMediaMtx` 会从工作区 `tools\rtsp` 自动定位 MediaMTX 1.20.1 与 FFmpeg 9.0.1，启动独立输出媒体平面，设置后台所需的 MediaMTX 环境变量，并在退出时清理子进程和临时配置。默认输出端口与本次联调一致，避免和输入发送端及 Android 模拟器端口占用冲突。

## 边界

本证据确认后端管理系统与真实 RTSP 输入、H.264 重新发布及三种播放地址已经打通。Android 端 WHEP 首帧成功率和 P50/P95 延迟属于移动端 `M13-T08` 的后续验收范围，不在本任务中宣称完成。
