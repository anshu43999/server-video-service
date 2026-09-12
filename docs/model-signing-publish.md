# 模型签名与发布协议

对应任务：`M10-T01`。本协议复用 Android 已冻结的 `schemaVersion = 1` 模型包规范，不再定义第二套签名格式。

## 签名对象

服务端输出完整 Android Manifest，但 Ed25519 只签名排除 `signature` 对象后的固定 UTF-8 规范载荷。字段顺序、布尔值、浮点值和每个标签的索引形式必须与 App `ModelPackageManifest.canonicalPayload()` 完全一致，行尾固定为 `\n`。

签名对象包含：

- `algorithm`: 固定 `Ed25519`
- `keyId`: 发布公钥的稳定标识
- `signatureBase64`: 64 字节 Ed25519 签名的标准 Base64
- `signedPayloadSha256`: 规范载荷的 SHA-256 十六进制值

模型文件自身由 `modelFile.sizeBytes` 和 `modelFile.sha256` 保护。Manifest 签名覆盖该哈希，因此产物和元数据不能被分别替换。

## 密钥与信任

- 私钥只允许来自服务进程可读的外部密钥文件或秘密管理系统，不写入仓库、数据库、任务记录、日志和 API 响应。
- 配置只持久化 `keyId` 与私钥文件路径；后台诊断只返回是否可读、公钥指纹和 keyId。
- App 内置受信任公钥集合。轮换时先发布同时信任旧、新 keyId 的 App，再切换服务端签名密钥；观察窗口结束后才撤销旧 keyId。
- 下载得到的公钥或 Manifest 内自带公钥不构成信任锚。

## 发布门禁

`development` 模型（包括 COCO 功能测试模型）始终 `releaseEligible=false`，但可在 Debug/内部测试 App 中使用受信任开发密钥安装。`business` 模型只有在来源、许可证、张量契约、服务端试推理、Android 转换、本地复验和签名全部通过后才能进入发布候选。

未配置签名密钥时，服务端可以保留 PT 服务端推理能力和未签名 TFLite 转换结果，但目录必须明确标记为不可安装/不可发布，不得生成占位签名。

## 任务拆分

1. `M10-T02`: 实现规范载荷、Ed25519 签名生成、App Manifest 和目录下载契约。
2. `M10-T03`: 实现 keyId 轮换、撤销、发布/下线门禁及后台安全诊断。
3. App 侧通过新的模型安装接线任务解析同一 Manifest、从内置公钥集合验签并在预热后原子激活。

远程转换不属于签名执行器，独立由 `M27` 承接。远端只产出待复验的 TFLite 和元数据，最终签名由本服务在本地复验成功后完成。
