# 异物入侵五类场景包（M09-T05）

`site-intrusion-v1` 已登记为服务端 ONNX 与 Android LiteRT/TFLite 的成对目录条目，固定标签顺序为：`bottle`、`bag`、`box`、`tool`、`person`，输入尺寸为 `640×640`。中文显示名只存在于 Manifest 映射层，推理和跨端结果仍使用权重原始类名。

## 当前冻结结论

仓库当前没有可验证的五类业务训练权重、训练数据授权、现场精度结果或 Enterprise License 证据。因此登记的两个产物是**开发占位文件**，只用于验证目录、下载、大小/SHA-256 和 Android/服务端身份对齐；它们不是 ONNX/LiteRT 模型，禁止加载、激活、安装、业务验收和发布。

- 服务端 Manifest：`models/site-intrusion-v1-manifest.json`
- 服务端目录：`models/registry.json` 中的 `site-intrusion-v1`
- Android Manifest：`../mobile-app/docs/models/site-intrusion-v1-business-placeholder-manifest.json`
- Android 产物：`../mobile-app/local-models/android-assets/models/site-intrusion-v1-android.tflite`
- 来源/许可证决策：`docs/adr-003-model-sources.md`

占位产物已登记实际大小和 SHA-256，服务启动校验会拒绝缺失或被篡改的文件。替换为真实权重时，必须保持 `modelId`/版本变更、重新导出成对产物、更新 Manifest 的张量输出与标签哈希，并补齐授权证据、精度/设备验收和 M10 签名发布流程；在此之前 `releaseEligible=false` 保持不变。
