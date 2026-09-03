# 真实视频链路验收

## 自动化链路

`tools/e2e_smoke.py` 读取本地视频文件，逐帧 JPEG 编码，连接服务端 ingest WebSocket，再从 output WebSocket 接收 JPEG，并统计发送到接收的延迟。

```powershell
python tools/e2e_smoke.py `
  --source E:\aiyolo\information\rtsp-test-videos\landscape_1280x720_25fps.mp4 `
  --stream-id e2e-local --frames 30
```

该工具验证的是服务端输入→处理→输出闭环，不等同于 Android 真机验收。

## 移动端联调记录要求

真实移动端联调时必须记录：

- 手机型号、Android API 和播放器库；
- 推送编码、分辨率、实际输入 FPS；
- 服务端地址、会话 ID 和 YOLO 开关状态；
- 首帧时间、P50/P95 端到端延迟、输出 FPS；
- 推送断开、服务端重启、播放器重连结果；
- 流删除后服务端是否释放连接和任务。

## 当前结果

本环境已完成本地视频/合成帧自动化闭环；真实 Android 移动端链路需要在目标设备接入后补充记录，不将本地 TestClient 结果替代真机结果。
