# 视频推帧联调客户端

`tools/push_video.py` 是独立的联调工具，用于模拟移动端向服务端推送 JPEG 帧。它不会修改或依赖 `mobile-app/` 源码。

## 推送本地视频

```powershell
python run.py
python tools/push_video.py --server http://127.0.0.1:8080 `
  --stream-id inspection-001 `
  --source E:\aiyolo\information\rtsp-test-videos\landscape_1280x720_25fps.mp4 `
  --fps 15 --duration 30 --create --loop --verbose
```

打开 `http://127.0.0.1:8080/`，选择 `inspection-001` 查看输出画面。调用 YOLO 开关后，推送客户端无需重连。

## 推送摄像头

```powershell
python tools/push_video.py --stream-id camera-001 --source 0 --fps 15 --create
```

工具输出 JPEG，默认质量 80，`--fps` 最大 30，与冻结协议一致。`--duration` 省略时持续推送，Ctrl+C 停止。
