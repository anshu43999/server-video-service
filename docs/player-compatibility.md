# 输出流播放器兼容性验证

状态：按 [ADR-002](adr-002-production-transport.md) 更新目标协议；WHEP/LL-HLS 行尚无任何实测证据

## 目标协议（ADR-002）

生产播放路径是 **WebRTC/WHEP**，H.264 Baseline/Main、Level ≤ 4.0、无 B 帧；**LL-HLS** 为回退；**RTSP** 只给诊断工具。

## 诊断协议（已实现，非生产）

1. `GET /api/streams/{stream_id}/mjpeg`：标准 `multipart/x-mixed-replace; boundary=frame`，每个 part 为 JPEG；
2. `WS /api/streams/{stream_id}/ws`：每条 binary message 为 JPEG。

这两条通道只用于管理页预览、自动化测试和联调探针，不再作为任何客户端的生产播放路径。

## 验证矩阵

| 播放端 | 目标 | 当前证据 | 状态 |
|---|---|---|---|
| Android（生产） | WHEP 播放 H.264，libwebrtc + API 27 硬解码 | 无 | 未验证。libwebrtc 在 API 27 的可用性与 APK 体积（预估 arm64 约 10 MB）是 ADR-002 的未验证假设 |
| Android（回退） | LL-HLS 由平台播放器播放 | 无 | 未验证 |
| 浏览器（生产） | WHEP 播放 | 无 | 未验证 |
| 浏览器（诊断） | 管理页面内 `<img>` 加载 MJPEG | `tests/test_api.py` 验证页面与 `/mjpeg` 路由存在 | 自动化契约通过，浏览器实播待现场确认 |
| VLC / ffprobe（诊断） | 打开 RTSP 地址；或直接打开 MJPEG URL | `tools/probe_output.py` + VLC 命令见下方 | RTSP 待编码推流落地后执行；MJPEG 待在有 VLC 的联调机执行 |

## VLC 手工验证（诊断通道）

先启动服务并通过 `tools/push_video.py` 推帧，然后执行：

```powershell
tools\rtsp\vlc\3.0.23\vlc-3.0.23\vlc.exe `
  http://127.0.0.1:8080/api/streams/inspection-001/mjpeg `
  --intf dummy --play-and-exit --run-time=10
```

H.264 推流落地后，同样用 VLC 打开 `rtsp://127.0.0.1:8554/inspection-001` 做诊断对照。

记录 VLC 是否成功显示连续画面、首帧时间和退出码。不要把“VLC 进程启动”当作播放通过。

## Android 联调建议

Android 生产播放端需至少验证：

- WHEP 信令（POST SDP offer / 收 answer）能建连，H.264 能在 API 27 上硬解码；
- WHEP 不可用时能按协议 §6.3 回退 LL-HLS，且回退可见；
- 检测结果 WebSocket 可独立订阅，断开重连不影响视频；
- 网络断开后能显示离线状态并重连；
- YOLO 开关改变后无需重建播放器即可看到模式变化；
- 720p 横屏、竖屏和 4:3 画面不拉伸；
- 连续 30 分钟无明显积帧或内存增长；
- 记录首帧时间、P50/P95 端到端延迟和 APK 体积增量。

正式 Android 证据应写入对应播放器兼容性任务的完成记录，并注明设备型号、Android API、WebRTC 库版本和视频源。
