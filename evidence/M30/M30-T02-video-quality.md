# M30-T02 后端 H.264 视频质量与流畅度验证

验证日期：2026-09-15

## 环境

- 输入：`rtsp://127.0.0.1:18554/file-test`
- 输入素材：`information/rtsp-test-videos/sucai1.mp4`
- 输入规格：H.264 Constrained Baseline，1920x1080，25 FPS
- 后端输出：`rtsp://127.0.0.1:19554/file-test-backend`
- 编码器：`ffmpeg-persistent:h264_qsv`
- 输出参数：Baseline / Level 4.0 / `bf=0` / 6 Mbps / GOP 50

本次使用 1080p/25 FPS 输入，高于任务要求的 720p/25 FPS 验收分辨率。

## 根因与修复

原链路逐帧启动 FFmpeg 并编码单帧 H.264，反复重置编码状态和时间戳；RTSP
输入还经过 JPEG 编码/解码往返，并把网络到帧抖动当作上传超限处理。运行日志
因此出现 `corrupted macroblock`、`Invalid level prefix`，且频繁断流重连。

修复后每路流只维护一个长驻 FFmpeg 进程，连续写入 YUV420P 原始帧；RTSP
解码帧直接进入处理链路；浏览器 JPEG 预览由独立 latest-only 任务编码；读取侧
使用 8 帧有界抖动缓冲和令牌桶，队列满时丢最旧帧，避免延迟无限增长。

## 真实运行结果

稳定运行后后台指标：

```text
received_fps=24.70
output_fps=24.95
frames_received=483
frames_published=482
frames_dropped=27
publish_state=connected
publish_error=null
encoder_backend=ffmpeg-persistent:h264_qsv
encoder_last_ms=2.454
```

模拟管理页持续打开 MJPEG 预览时：

```text
active_subscribers=1
received_fps=24.55
output_fps=24.55
publish_error=null
```

发布器隔离基准为 250 帧 / 2.292 秒，即 109.07 FPS，证明长驻发布器具备足够
余量。FFmpeg 通过 TCP 拉取后端输出 150 帧，退出码为 0，过程中未出现
`corrupted macroblock`、`Invalid level prefix` 或其他解码警告。进程检查确认
`file-test-backend` 只有一个长驻 FFmpeg 发布进程。

## 自动化验证

- `test_stream.py`：11/11 通过。
- `test_publisher.py`：10/10 通过。
- `test_fault_recovery.py`：4/4 通过。
- `git diff --check`：本任务代码无空白错误；工作区既有 `TASK_BOARD.md` 行尾
  空格和 CRLF 提示仍存在。
- 完整服务端套件：401 项，366 通过、8 跳过、21 失败、6 错误。失败集中于
  账号鉴权共享状态、既有 Compose health 条件和模型参数/播放 API 契约，相关
  视频发布、读取与故障恢复定向测试均通过。

## 遗留风险

- `h264_qsv` 已在本机实测；无 Intel QSV 的部署环境会自动回落 `libx264`，仍需
  在目标服务器按实际并发路数做容量验收。
- 8 帧缓冲用于吸收 OpenCV 集中补帧，满时会主动丢弃旧帧；源端长时间停顿时
  优先保证低延迟，而不是补播所有历史帧。
