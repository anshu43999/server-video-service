# YOLO 模型部署与追溯

## 配置

服务启动时通过环境变量指定模型，不将权重打包进代码仓库：

```powershell
$env:YOLO_MODEL_PATH='E:\models\inspection-best.pt'
$env:YOLO_IMGSZ='640'
$env:YOLO_CONFIDENCE='0.25'
$env:YOLO_DEVICE='auto' # auto、cpu、0 等由 ultralytics/PyTorch 解释
$env:YOLO_CLASSES='bottle,bag,box,tool,person'
```

Docker 部署时将模型以只读卷挂载：

```powershell
Copy-Item E:\models\inspection-best.pt .\models\best.pt
docker compose up --build
```

## 验证步骤

1. 启动服务并访问 `/healthz`；
2. 创建流并推送至少一帧；
3. 调用 `POST /api/streams/{id}/yolo` 开启分析；
4. 调用 `GET /api/streams`，保存返回的 `model` 元数据；
5. 检查 `model_exists`、`loaded`、文件大小、`imgsz`、设备和类别顺序；
6. 从 WebSocket/MJPEG 输出确认画面可解码，记录处理帧数和模型错误。

管理接口：

- `GET /api/models`：列出模型、格式、文件存在性、SHA-256 和当前活动模型；
- `POST /api/models/register`：登记 `models/` 目录下转换工具生成的 Manifest；服务端会重新计算产物 SHA-256，哈希不匹配或路径越界时拒绝登记；
- `POST /api/models/{model_id}/activate`：校验文件哈希后将 PT/ONNX 服务端模型设为新会话默认模型；TFLite 只作为移动端产物，不能直接作为当前服务端活动模型。

管理页面的“模型资产”区域会显示每个资产的格式、输入尺寸、文件存在性和哈希校验状态；只有文件存在且哈希匹配的 PT/ONNX 模型可以激活，新建视频流会使用激活模型。
转换完成后可在管理页面点击“登记 Manifest”，填写例如 `models/converted/yolo11n_640_manifest.json`；登记成功后 ONNX/PT 会出现在列表中，TFLite 会以 MOBILE ONLY 状态展示。

## 当前环境状态

服务器项目当前包含从移动端复制的内部开发 `.pt` 与 `.tflite` 资产，虚拟环境已安装 `ultralytics`。业务模型精度、GPU 吞吐和商业发布资格仍必须在目标部署服务器上单独验收。

当前服务器项目已经迁移移动端的内部开发资产到 `models/`：`yolo11n.pt`、640/416/320 三档 TFLite，以及标签和 Manifest。该 PT 已在本机 CPU 成功完成一次真实推理；这只证明模型文件和运行时可用，不代表业务五类目标精度达标。

转换命令详见项目根目录 README 和 `tools/convert_model.py`。服务端 ONNX/PT 导出和移动端 LiteRT INT8 导出共用同一份 PT 权重，但输出目录、运行时和 Manifest 必须分开记录。`--server-format pt` 保留可直接被 Ultralytics 加载的 PT，`--server-format both` 同时生成 ONNX 与 PT。

LiteRT 导出受 Ultralytics 平台限制：Windows 原生环境不支持该导出，需使用 WSL2 Ubuntu/Linux x86 或 macOS。Windows 侧的服务端模型转换不受此限制；在不支持的平台运行 `--format mobile` 或 `all` 时，工具会返回明确错误并要求切换到 WSL/macOS。

ONNX 产物需要目标环境提供 `onnxruntime`。由于不同 Python 版本和平台的 wheel 发布节奏不同，依赖单独放在 `requirements-onnx.txt`，不阻塞默认 PT 服务启动；缺少运行时时，服务会保留原始视频并在流状态中报告模型错误。

模型清单应至少记录：来源、版本、文件 SHA-256、类别顺序、输入尺寸、量化/精度、许可证和适用场景。
