# M34-T07 CPU 运行验收

日期：2026-11-05。范围：服务端配置、两个 Docker 构建定义、推理与转换工具；未操作线上服务，未修改 Android，未提交或推送 Git。

## 交付

- `requirements-cpu.txt` 使用 PyTorch 官方 CPU wheel 页面；`constraints-cpu.txt` 固定 Torch 2.12.0+cpu、TorchVision 0.27.0+cpu（Linux/Windows）及兼容 LiteRT 0.9.x 的 Ultralytics 8.4.138。macOS 使用同版本原生 CPU 运行库。
- 两个 Dockerfile 均复制 CPU 依赖与约束文件，保留 `PIP_CONSTRAINT`/`PIP_FIND_LINKS`，设置 CPU/CUDA/JAX 设备策略；安装后执行 `pip check` 与 `tools/check_cpu_runtime.py`。审计拒绝 GPU 计算运行库，检测 CPU wheel，并实际运行 TorchVision NMS。`nvidia-ml-py` 仅是小型监控客户端，不作为 GPU 计算库。
- 视频推理与按流模型切换固定 CPU；旧 auto/cuda/设备编号兼容为 CPU。转换 worker 隐藏 CUDA 并指定 JAX CPU；PT 检查、LiteRT 导出原有 CPU 参数保留，ONNX 导出补充明确 CPU 参数。
- Compose、Kubernetes 示例、README 和转换/部署文档同步；没有改变模型卷、数据库或告警数据。

## 自动化回归

原有 Windows 开发虚拟环境中以下 11 组共 **124 项测试通过**：

| 测试文件 | 数量 |
|---|---:|
| test_cpu_runtime.py | 4 |
| test_docker_deployment.py | 17 |
| test_kubernetes_deployment.py | 7 |
| test_detection.py | 50 |
| test_stream.py | 14 |
| test_stream_model_binding.py | 3 |
| test_conversion_worker_progress.py | 2 |
| test_conversion.py | 13 |
| test_remote_conversion.py | 4 |
| test_converter_service.py | 8 |
| test_convert_model.py | 2 |

每组命令为 `.venv/Scripts/python.exe -m unittest discover -s tests -p <文件名>`。首次部分测试受 Windows 临时目录沙箱权限影响，沙箱外重跑上述完整集合全部通过。完成后又针对工作区并行发生的模型类别过滤修改重跑 4 项 CPU 行为测试，通过且保留其改动。Harness 34 项单元测试通过，状态校验通过；改动文件的 `git diff --check` 通过。

## Linux 依赖与真实模型

按镜像目标 Python 3.11 / Linux x86_64 manylinux_2_28 解析：视频服务 **75** 个依赖、转换器 **117** 个依赖，两组均无 CUDA/NVIDIA 计算库、Triton 或 JAX GPU 插件。解析快照见同目录 `video-python311-resolved.txt`、`converter-python311-resolved.txt`。

WSL Ubuntu 创建隔离 Python **3.12.3** 环境，安装上述转换器解析版本及官方 cp312 CPU wheels（并非 Docker 构建）。官方 CPU 索引在 WSL 下访问不稳定，因此通过 Windows 从相同官方下载地址获取 CPU wheels，再在 Linux 安装；没有改用 GPU 包或更改镜像中的安装来源。真实执行 `linux_smoke.py`，结果见 `linux-runtime.json`、`linux-mobile.log`、`linux-verify.log`：

- Torch **2.12.0+cpu**、TorchVision **0.27.0+cpu**；`torch_cuda=null`，`cuda_available=false`，`gpu_packages=[]`，CPU NMS 通过，JAX 只有 CPU 设备。
- 使用既有 `models/yolo11n.pt` 真实推理，模型参数位于 CPU，80 个类别；显式传入旧 `cuda:0` 设置也只运行 CPU。单次 320 输入推理 396.638 ms，仅为功能冒烟，不是吞吐基准。
- worker `check`、`inspect`、`mobile`、`verify` 均成功；LiteRT INT8 导出约 77.4 秒，独立复验通过，CPU XNNPACK delegate 执行成功。
- TFLite 大小 **2,639,325 字节**；SHA-256 `37248b07bb1b3d04ca46eba2e59b8fb1734cbaeadc8966c9e1c0806f4c042d47`；输入 `[1,3,320,320]`、输出 `[1,84,2100]`，float32 I/O、INT8 内部量化，符合现有张量协议。
- 转换后 `pip check` 返回 `No broken requirements found.`。校准采用现有 COCO8 的 4 张验证图片，仅验证工具链，不声明业务精度。
- 转换完成后再次运行 CPU 审计，同样通过：`linux-post-audit.json` 确认转换过程没有引入 GPU 计算包，PyTorch/TorchVision/JAX 仍全部为 CPU。

## 限制与发布

本机无可用 Docker，因此未构建或运行两个最终镜像，未测量镜像实际大小；Linux 模型实测使用 Python 3.12，Python 3.11 完成的是依赖解析验证。新 Dockerfile 自带安装一致性和 CPU 审计，目标环境构建仍需通过这些门禁。上线须重新构建并发布两个镜像；仅更改环境变量或重启旧容器不会删除旧镜像中的 CUDA 库。目标服务器容量、并发流数与业务模型准确率不在本次验收范围。

真实验证临时环境、下载 wheels、安装缓存与原始调试日志在验收后清理；本目录保留解析快照、运行结果、转换日志及复现脚本。首轮校准生成的 `calibration/builtin/dev8/labels/val.cache` 也仅删除本次新生成文件；复现脚本已改为将校准图片复制到临时目录，避免后续污染内置资产。
