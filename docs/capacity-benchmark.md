# M04-T03 多流并发与容量压测

## 测量边界

生产容量必须包含完整的“帧 → H.264 → RTSP/MediaMTX”路径。`tools/capacity_benchmark.py` 每路并发任务调用 `MediaMTXPublisher.publish()`；该方法先执行 `H264Encoder.encode()`，再向 MediaMTX 的固定 RTSP path 写入 Annex-B H.264。编码耗时通过 P50/P95 单独报告，不能引用 M02-T03 的 JPEG/无编码数字。

在没有运行 MediaMTX 的开发机上，可使用 `--dry-run`（默认）运行 H.264 编码加确定性内存 sink。该模式只用于校准编码开销，不作为生产并发结论；生产结论必须附带 `--publish` 的真实 MediaMTX 结果。

## 可重复命令

```powershell
cd E:\aiyolo\server-video-service
.venv\Scripts\python.exe tools\capacity_benchmark.py --streams 1 --duration 20 --fps 10 --dry-run --output artifacts\capacity-1.json
.venv\Scripts\python.exe tools\capacity_benchmark.py --streams 4 --duration 60 --fps 10 --publish --rtsp-base rtsp://127.0.0.1:8554 --output artifacts\capacity-4.json
```

逐步增加 `--streams`（1、2、4、8……），在每次运行中保持分辨率、FPS、码率和 GOP 不变。JSON 结果包含请求/成功帧数、有效总 FPS、编码 P50/P95、每路发布状态、编码后字节数和进程 CPU/内存采样。`--publish` 失败或成功帧数不足时，结果不得标记为通过。

## 容量判定与降级

单机并发上限定义为：连续 60 秒运行时，每路成功帧率不低于目标 FPS 的 90%，编码 P95 不超过单帧预算（`1000 / FPS` ms），且无 `publish_state=failed`、BrokenPipe 重连耗尽或进程内存持续增长。记录达到上限的最后一个流数 `N`，扩容指标为 `N+1` 流或任一资源门槛先触发者。

建议初始资源门槛：CPU 持续 80%、进程 RSS 1 GiB、GPU 显存 80%。超出门槛时按以下顺序降级：

1. 降低每路目标 FPS（保持关键帧 GOP 1–2 秒）；
2. 关闭叠加或 YOLO 推理，保留原始 H.264 视频和检测心跳；
3. 拒绝新流并返回容量不足状态，避免影响已建立流；
4. 扩容到另一服务实例/MediaMTX 节点，并按固定 path 分片。

## 结果记录要求

现场结果应保存 JSON 和运行环境（CPU、内存、GPU、FFmpeg、MediaMTX 版本）。未安装 FFmpeg、MediaMTX 不可达或缺少 `psutil` 时，工具仍输出结果但必须把资源字段记为 `null`，并在验收记录中列为环境限制。
