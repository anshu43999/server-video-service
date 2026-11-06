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
- 服务端使用 `MODEL_SIGNING_TRUSTED_KEY_IDS` 声明轮换窗口内的 keyId，使用
  `MODEL_SIGNING_REVOKED_KEY_IDS` 立即撤销 keyId；活动 key 必须同时受信且未撤销。
- `GET /aiyoloapi/conversion/signing-status` 只返回 keyId、信任/撤销集合、轮换窗口状态、私钥可读性、公钥 SHA-256 指纹和配置状态，绝不返回私钥路径或内容。

## 发布门禁

模型不再区分开发用途和业务用途。发布按目标端统一校验来源、许可证、哈希和就绪状态：PC 端需要已通过服务端试推理的 PT/ONNX，不需要 Android 转换或签名密钥；移动端需要转换、本地复验、张量契约与受信任 Ed25519 发布签名。双端可先发布一个就绪端，另一端之后补齐。历史 Manifest 若带有 `purpose`，该字段仅参与旧规范签名载荷验证，不参与用途控制；新 Manifest 不包含该字段。

未配置签名密钥时可以独立发布合规 PC 模型；未签名 TFLite 仅保留转换结果，移动端不可安装/发布，不得生成占位签名。

平台模型管理员调用 `POST /aiyoloapi/models/{modelId}/versions/{version}/publish`，请求体为 `targets: ["pc"]`（也可 mobile 或双端）、`licenseApproved: true`、非空 `reason`。响应 `targetReleaseEligible` 表示每端实际可分配性；`publishedTargets` 在注册表中记录已批准目标。Android 发布生成单独的内容寻址 `android-release-<hash>.json`，将 `releaseEligible=true`、许可批准结果纳入原 schemaVersion=1 签名后原子切换目录指针，不覆盖转换 Manifest 或 TFLite；重试保留已发布字节。签名失败不提交发布状态。

发布操作在注册表 `modelHistory` 同次原子写入操作人、目标、原因与前状态，并投影到平台 `model.publish` 审计。JSON 注册表与数据库审计没有跨存储事务；数据库审计故障时以注册表历史为权威证据，重试可补记平台审计，不应误以为未发布。

## 任务拆分

1. `M10-T02`: 实现规范载荷、Ed25519 签名生成、App Manifest 和目录下载契约。
2. `M10-T03`: 实现 keyId 轮换、撤销、发布/下线门禁及后台安全诊断。
3. `M10-T04` 以项目模型分配作为隔离的灰度分组；项目负责人可以通过 CAS 修订选择已发布版本，平台超级管理员/受控运维可以显式请求 Android 版本回退。回退响应包含 `previousModel`、`targetModel` 和新 `revision`，并写入 `model_assignment.forced_rollback` 审计；不修改 App 的 active/candidate/previous 本地槽位，也不把服务端回退伪装成本地授权。
4. App 侧通过新的模型安装接线任务解析同一 Manifest、从内置公钥集合验签并在预热后原子激活。

## 项目灰度与回退接口

项目模型分配是当前服务端唯一的灰度隔离边界：每个项目和场景固定一个精确版本、平台参数快照和 CAS `revision`。服务端不按请求头或客户端自报用户身份做隐式分组，也不在没有项目上下文时选择首个项目。

`POST /aiyoloapi/projects/{projectId}/model-assignments/{scenario}/rollback` 只接受 Android 分配，载荷必须包括：

- `expectedRevision`、`expectedModelId`、`expectedModelVersion`：防止旧页面覆盖新分配；
- `targetModelVersion`：同一模型族中已 `PUBLISHED`、`releaseEligible=true`、`androidReady=true` 且 `signatureStatus=signed` 的历史版本；
- `reason`：写入审计的人工回退原因。

成功响应返回更新后的 assignment、`operation=forced_rollback`、前后版本和新的 revision。版本撤销、未签名/不可用目标、非 Android 分配、项目权限不足或 CAS 冲突均拒绝，且不会改变 App 本地模型槽位；App 必须重新拉取项目分配并自行执行安装/激活安全状态机。

远程转换不属于签名执行器，独立由 `M27` 承接。远端只产出待复验的 TFLite 和元数据，最终签名由本服务在本地复验成功后完成。
