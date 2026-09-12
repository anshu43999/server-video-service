# 场景模型目录数据源

M09-T02 将 `models/registry.json` 固定为服务端模型市场的唯一登记源。每个模型必须声明：

- `modelId`、`version`、`scenario`、`runtime`
- 原始类别顺序 `labels` 与可选的 `compatibleDevices`
- `artifacts[]` 中每个产物的 `artifactId`、格式/平台、相对 `path`、`sizeBytes` 和 SHA-256

产物路径相对于服务端工程根目录解析，登记文件不得依赖本机绝对路径。服务启动时 `ModelCatalog.validate_startup()` 会读取登记源并逐项检查：

1. 模型与产物元数据完整且 ID 唯一；
2. 产物文件存在；
3. 文件大小与 `sizeBytes` 一致；
4. 文件 SHA-256 与登记值一致。

任何一项失败都会抛出 `ModelCatalogValidationError`，FastAPI lifespan 启动失败并保留明确错误信息。服务不会删除无效条目，也不会静默回退到默认模型。模型转换注册 (`/api/models/register`) 必须先校验 manifest 产物哈希，再写回同一 `registry.json`。

开发环境如需新增模型，请先把产物放入 `models/` 下，计算 SHA-256 和大小后更新登记源，并在启动服务前运行：

```powershell
python -c "from app.model_catalog import ModelCatalog; ModelCatalog().validate_startup()"
```
