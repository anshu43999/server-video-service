# H.264 编码实现决策（M08-T02）

## 实现

`app.encoder.H264Encoder` 提供统一的 BGR `numpy.ndarray` → Annex-B H.264 API。
编码配置由 `EncoderConfig` 校验，固定满足 API 27 兼容约束：

- profile 为 `baseline` 或 `main`
- level 不高于 4.0
- `bf=0`
- GOP 为 1–2 秒（按 FPS 换算帧数）
- `tune=zerolatency`

编码耗时、累计帧数和滑动窗口 FPS 通过 `EncoderMetrics` 暴露，可由流指标层直接合并。

## 后端选型

实现同时保留两种后端：

1. FFmpeg 子进程管道（`ffmpeg -f rawvideo ... -f h264 pipe:1`）
2. PyAV 进程内 `libx264`（运行环境安装 PyAV 时可用）

本开发环境未安装 PyAV，且系统 PATH 没有 FFmpeg；因此无法进行本机吞吐实测。生产 Dockerfile 已安装 FFmpeg，且 FFmpeg 子进程具备进程隔离、参数可观测和编码器崩溃不拖垮 Python 服务的优势，故 `auto` 默认优先选择 FFmpeg，缺失时才回落 PyAV。两种后端均使用相同的约束参数。

## 验证

- `python -m unittest tests.test_encoder -v`：5 项通过。
- 测试覆盖参数约束、GOP 计算、FFmpeg 命令、指标记录及结构化失败。
- 尚未完成真实硬件编码器（NVENC/QSV）与 720p 实时 FPS 测量，需在包含 FFmpeg/硬件设备的部署环境中补测。
