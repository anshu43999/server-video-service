# H.264 编码实现决策（M08-T02）

## 实现

`app.publisher.MediaMTXPublisher` 为每路流维护一个长驻 FFmpeg 进程，
直接执行连续 BGR `numpy.ndarray` → YUV420P → H.264 → RTSP。编码配置由
`EncoderConfig` 校验，固定满足 API 27 兼容约束：

- profile 为 `baseline` 或 `main`
- level 不高于 4.0
- `bf=0`
- GOP 为 1–2 秒（按 FPS 换算帧数）
- `tune=zerolatency`

管道写入耗时、累计帧数和滑动窗口 FPS 由 publisher 指标暴露。禁止逐帧启动
FFmpeg：独立单帧 H.264 片段会重置编码状态和时间戳，造成 CPU 抖动、卡顿和码流损坏。

## 后端选型

`app.encoder.H264Encoder` 仍保留为独立编码原语与参数验证工具，但实时发布链路固定使用：

1. 每路流一个长驻 FFmpeg 子进程；
2. 后端先将 BGR 转为 YUV420P，再通过 `rawvideo/yuv420p` 从 stdin 连续输入，
   将 Windows 管道的单帧数据量减半；
3. FFmpeg 内部完成 libx264 编码并直接发布 RTSP 到 MediaMTX。

默认 `MEDIAMTX_VIDEO_ENCODER=auto`：优先使用 Intel Quick Sync `h264_qsv`，
启动前几帧失败时自动回落 `libx264`。也可显式配置为 `h264_qsv` 或
`libx264`。软件回退使用 `ultrafast + zerolatency`；两者默认 6 Mbps，以更高
码率补偿快速预设的压缩效率，避免因码率不足出现块状画面。

工作区启动脚本显式提供 FFmpeg 路径，不依赖系统 PATH。长驻子进程保留进程隔离，发生断管时按有限次数重建；输入分辨率或最大 FPS 改变时主动重建，避免用错误的 rawvideo 参数解释帧内存。

RTSP 拉流使用最多八帧的有界抖动缓冲：它能吸收 OpenCV 在网络停顿后向事件
循环成批交付帧的抖动，并用同容量令牌桶限制长期平均帧率。队列满时仍丢弃
最旧帧，避免延迟持续增长。浏览器 JPEG 预览使用
独立 latest-only 编码任务，不阻塞 H.264 发布。外部上传接口继续执行瞬时帧率
拒绝；内部相机拉流允许正常到帧抖动，避免因偶发的帧间隔缩短而断开并从 GOP
中间反复重连。

## 验证

- `python -m unittest tests.test_encoder -v`：5 项通过。
- 测试覆盖参数约束、GOP 计算、FFmpeg 命令、指标记录及结构化失败。
- 本机 Intel QSV 已用 1080p/25 FPS RTSP 输入实测：稳定输出 24.95 FPS，管理页
  MJPEG 预览连接时为 24.55 FPS；150 帧输出码流检查无解码警告。其他部署硬件
  和多路并发容量仍需在目标服务器补测。
