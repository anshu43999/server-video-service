# App 升级契约 v1（M42-T01 / Android M118）

状态：2026-10-29 冻结；对应 FR-12 / PR-09。本文定义接口、数据与安全语义；实际 HTTP 路由、APK 核验、MinIO 和后台交互分别由 M42-T02～T08 实现。本次不将接口定义描述成已上线功能。

实现进度：M42-T02～T04 已完成核验与来源登记，M42-T05～T07 的发布/检查/地址/许可/回执、后台和快速回退实现及配置见 [App 升级服务](app-update-service.md)。安全专项、真实后台托管联合、跨端安装与生产部署仍按后续任务验收。

## 1. 权威来源和正式身份

- 可执行类型：`app/app_updates/contract.py`；导出 JSON Schema：`docs/app-update-v1.schema.json`；共同金样：`docs/app-update-v1-golden.json`。
- Android M118-T01 必须消费上述同一份 schema 和金样，记录原始文件 SHA-256；如复制到 Android 测试资源，逐字节对比，禁止重新手写不同语义。Android 尚未接入，不能据此宣称跨端验收通过。
- applicationId/packageName 固定 `com.aiyolo.inspection`，首个正式 APK 的 versionCode 为 **1**；全渠道和部署共用同一递增序列。v1 仅使用 Android versionCode，范围 1～2,147,483,647，versionCodeMajor 固定 0；Android 以 Long 比较。versionName 只展示。不得复用已登记的版本码，更换渠道也不能复用。
- AppIdentity 保存包名、发布者、首版本、高水位和批准证书。升级核验器/发布服务必须在同一事务锁定身份行，再校验/递增高水位；首个核验通过的工件必须为 1。重复上传相同字节返回已有工件，不再分配版本码；新字节使用新版本。失败核验不能抢占别人的正式版本。
- 首阶段固定一个生产 APK 签名身份，不支持密钥轮换。批准证书和元数据私钥配置引用默认为空，不能从首次外链、debug 包或来路不明响应自动建立信任。
- `dataSchemaVersion` 是 App 业务库 schema；`serverContractVersion` 是独立 App/服务通信版本，不能将当前 Room schema 19 当作服务端协议号。v1 的首个服务协议编号为 1。
- 包名和证书与当前安装不同，不能承诺覆盖或数据保留；已有不同 debug 签名安装需要独立迁移计划。生产显示名称、签名材料、首个具备更新功能的正式能力包仍是发布前置。

## 2. 路由和身份边界

统一前缀 **`/aiyoloapi`**。`/api` 仅是早期调研示例。路径、请求类型、响应类型和权限的机器清单见 schema 的 `x-api`；下表为核心写接口。JSON 请求 Content-Type 为 application/json，严格区分整数/布尔/字符串，未知字段拒绝。

| 方法与相对路径 | 请求 / 响应 | 语义 |
|---|---|---|
| POST `/mobile/app-updates/check` | CheckRequest / SignedEnvelope(CheckPayload) | 五种检查结果，绝不自动下载 |
| POST `/mobile/app-updates/{releaseId}/download-ticket` | DownloadRequest / SignedEnvelope(DownloadPayload) | 只给直连地址，不返回 APK 流 |
| POST `/mobile/app-updates/{releaseId}/install-permission` | InstallPermissionRequest / SignedEnvelope(InstallPermissionPayload) | 完整文件本地校验通过后重新在线核验撤回、修订和安装资格 |
| POST `/mobile/app-updates/receipts` | Receipt / ReceiptResult | 单事件幂等补报，成功不构成远程安装证明 |
| POST `/admin/app-updates/artifacts/upload` | multipart `apk,idempotencyKey,reason` / ResourceResult | 自有 APK 暂存后异步核验，202 |
| POST `/admin/app-updates/external-artifacts` | ExternalArtifactRequest / ResourceResult | 外链登记，后台完整读取一次核验，202 |
| POST `/admin/app-updates/artifacts/{artifactId}/download-sources` | SourceRequest / ResourceResult | 同一字节新增来源，修订递增，202 |
| POST `/admin/app-updates/releases` | ReleaseDraftRequest / ResourceResult | 由已验证工件建立草稿，201 |
| POST `/admin/app-updates/releases/{releaseId}/publish` | PublishRequest / ResourceResult | 校验全部前置后原子切换策略，200 |
| POST `/admin/app-updates/releases/{releaseId}/stop` | StopRequest / ResourceResult | 停止新地址和安装许可，200 |
| POST `/admin/app-updates/rollback-preview` | RollbackPreviewRequest / RollbackPreview | 只读预览、指纹、预期修订、阻塞项和有限有效期，200 |
| POST `/admin/app-updates/rollbacks` | RollbackRequest / OperationResult | 幂等提交，202；操作查询 GET `.../rollbacks/{operationId}` |

后台 GET：工件列表/详情、来源列表、发布列表/详情、审计列表，返回 ResourcePage/ResourceView。列表统一 `limit`（1～100，默认 50）、不透明 `cursor`；按 createdAt、ID 稳定分页，首阶段不返回总量。ResourceView.details 是管理端可扩展投影，不作为 App 安装授权。

管理端每次请求重新读取账号启用状态、当前 PLATFORM_ADMIN 和会话，不信任前端菜单或过时角色声明。普通/项目管理员禁止操作。所有写入保存审计、原因、幂等键和请求摘要；URL 路径 ID 与请求 ID 不一致返回 invalid_request。

移动更新是部署级公共元数据入口：已配置的 HTTPS 服务实例限定 publisher/package/channel/deployment 白名单，登录前可用；未知部署返回 deployment_not_allowed。此处“deployment”不是复用项目/模型授权，也不是允许客户端任意选租户。App 固定可信部署和元数据公钥，不接受响应自带新信任根。公共 APK 本身不含业务秘密；业务访问仍由现有账号权限控制。安装实例随机 ID 和回执不是硬件身份或可信远程证明；限流、请求体上限和有界记录由 T05/T08 实现。

## 3. 检查与三类更新

结果固定为 `up_to_date`、`update_available`、`no_compatible_release`、`client_unsupported`、`recovery_pending`；仅 update_available 携带 release，目标 versionCode 必须高于当前值。无兼容目标、未知协议、网络失败和问题版待恢复不能显示“已是最新”。

三类策略通过两个维度表达，避免强制安装误读：

1. 普通：importance=normal，可稍后。
2. 重要推荐：importance=important，强化提示，仍由用户点击下载/安装。
3. 兼容门禁：minSupportedVersionCode + onlineAction=restrict_declared_capabilities + 非空 restrictedCapabilities/reasonCode。仅限制明确不兼容的在线能力，保留数据、诊断、升级、账号退出与恢复入口。提醒强度可以独立设置。

服务端选目标时检查包名、批准签名、SDK/ABI、服务协议、工件和来源验证状态、停止状态及当前设备版本。发布门槛不能高于受影响设备实际可获取/安装的目标。无有效目标时拒绝设置该门槛，不能把旧设备锁死。检查缓存不采用 304，v1 每次返回新的有界签名响应。

release 固定 artifactId/sourceId/sourceRevision、精确 sizeBytes、SHA-256、APK signerSha256、SDK/ABI、服务协议与数据 schema 能力。v1 最大 APK 为 8GiB，实际部署可进一步降低；大小来自完整字节核验，不能依赖 HEAD。

## 4. 双来源下载与签名

external/public：第三方公开 HTTPS 文件直链，downloadUrlExpiresAt=null；App 直接连接第三方，不经过业务服务/MinIO 代理。internal：保存 MinIO bucket/objectKey，可返回 public 或 presigned 地址；访问密钥只保存受控配置引用。

外链核验允许一次后台完整读取流量；同工件后续检查和设备下载复用验证证据。工件/已验证来源不可覆盖，换域名/路径新增 sourceId 并递增 artifact 内 sourceRevision；换字节必须新工件和版本码。上传/登记待核验状态可有空解析字段，只有真实完整验证通过才能进入 verified。

线格式只有 `{keyId,payloadBase64Url,signatureBase64Url}`；Base64URL 无 padding，签名 64 字节。签名消息为：

```text
Ed25519("AIYOLO-APP-UPDATE/v1\0" || exactDecodedPayloadBytes)
```

APK 签名证书、元数据公钥、模型签名密钥三者独立。签实际 payload 字节，不重新排序序列化验签。先根据受控 trusted keys 验签，再严格 UTF-8/JSON 校验；拒绝重复键、NaN、无限值、非法类型、未知字段、未知协议、超限和整数溢出。payload ≤256KiB，信封 ≤512KiB。参考校验在 `app/app_updates/signatures.py`，金样仅含一次性测试公钥和签名，没有测试/生产私钥。

三类签名载荷都绑定 messageType、publisher/package/channel/deployment、requestId、installationId、currentVersionCode、policyRevision、issuedAt、authorizationExpiresAt。地址/安装许可进一步绑定 release、artifact、source/revision、version、hash、size、APK 证书。客户端必须与本次请求和已验证文件逐项匹配，不能只验证签名。

检查/地址授权最长 15 分钟，安装许可最长 120 秒；公开文件链接无期限与授权过期是两回事。私有 URL 不得早于地址授权过期。拒绝更低的已知策略修订、过期/未来签发数据、错误设备/请求上下文。设备时钟异常进入校时/重试，不能无限延长离线许可。首阶段离线安装关闭，userActionRequired=true。

所有地址和逐跳重定向必须 HTTPS 且域名获准，拒绝 URL 用户名/密码、fragment、HTTP 降级；不能将业务 Authorization、Cookie、账号或 MinIO 密钥发往文件源。登记阶段的 SSRF/DNS/IP/重定向实际拦截和可达检查由 T04/T08 实现，类型层 HTTPS 校验不能代替它。

Wi-Fi/移动网络均点击下载；移动网络先展示被签名绑定的精确 APK 大小并确认，同意绑定 artifact/hash。Wi-Fi 转移动网络无授权时暂停。下载完整后核对大小、SHA-256、包名、versionCode、SDK/ABI、批准证书；后台 apksigner 真验签及证据是发布门禁，getPackageArchiveInfo 不是密码学验签。

用户点击安装后、系统安装器交接前重新请求安装许可，修订冲突重新检查。许可不保证系统 UI 打开后可追回安装：撤回与系统安装器之间存在已交接竞态，必须在 UI/运维中记录边界。持久化告警/证据/待同步状态后到安全点停止相机/推理，再交给系统确认安装；不能静默安装。

## 5. 发布、回退、幂等与设备状态

管理写请求幂等范围为操作者+动作+幂等键，回退额外在 policyId+idempotencyKey 唯一。同键同规范化请求返回原结果，同键不同请求 409 idempotency_conflict。校验 expectedPolicyRevision 后 CAS 更新，失败 409，不覆盖其他发布。预览指纹绑定全部问题版本、稳定来源、恢复版本/兼容证据、源修订、当前策略、有效期；重新发布或证据改变必须重新预览。

事务内完成：停止问题版、生成新策略修订与签名快照、切换活跃选择、写操作/审计。对象存储不参加 DB 事务，必须先核验对象存在且可读，事务失败保留草稿/待清理记录，不先发布悬空文件。

回退：未安装设备重新推荐稳定版；已安装问题版只能升级同包名同签名、versionCode 更高的 recovery 包。示例 100 稳定→101 问题→102 恢复。恢复包行为可来自 100，数据 schema 不降级，不清库，必须读写 101 已产生的数据并具备验证证据。没有恢复包时可先止损，recoveryState=pending；受影响已安装设备检查结果 recovery_pending。恢复就绪后返回 update_available/releasePurpose=recovery，签名包含 rollbackOperationId、restoresBehaviorFromReleaseId、affectedReleaseIds。

后台的 applied 只表示策略原子生效，设备恢复单独统计。受控条件下策略服务目标≤5秒，移动设备离线/不启动/用户未确认不承诺完成时间。公开链接无法追回，停止不等于删除文件或卸载 App。

回执按 policyId+installationId+eventId 去重，同 ID 不同摘要冲突；同 attemptId+sequence 不能复用。事件按服务端接收时间持久化，不以不可信 occurredAt 排序。设备投影只前进到新 attempt/更大 sequence，迟到的 downloaded 不覆盖 healthy；旧 attempt 的 healthy 也不能覆盖更新尝试。客户端上报不作为账号授权或可信设备证明。

```text
not_discovered → discovered → downloading → downloaded → verified
→ waiting_install → installer_opened → started_pending_health → healthy
任意阶段 → failed / canceled；装了更高版本 → superseded
```

installer_opened 不算安装成功；只有真实包级版本等于目标、迁移与基础健康通过才上报 healthy。更高版本用 superseded，不归因本次成功。设备状态以 last_contact_at 派生“长期未联系”，未知设备不虚构为未发现；统计分母仅限本服务已联系的安装实例。

## 6. 持久化和迁移边界

| 表 | 用途/关键约束 |
|---|---|
| app_update_identities | 包级发布者、首版本=1、全局高水位、批准证书/密钥配置引用 |
| app_artifacts | 全包唯一 versionCode、实际字节身份、兼容能力、核验证据 |
| app_artifact_sources | 双来源、同工件来源修订唯一、可达性和完整字节核验证据 |
| app_update_policies | publisher/package/channel/deployment 唯一、CAS 修订、兼容门槛和选择快照 |
| app_releases | 草稿/发布/停止、importance/purpose，工件与策略身份复合外键 |
| app_update_policy_revisions | 不可变历史策略快照、摘要、独立签名，不复用每设备响应 |
| app_rollback_operations | 预览指纹、幂等、前后修订、稳定/恢复版本、原因、结果 |
| app_update_device_states | 策略+安装实例投影、观测版本、尝试/序列、最后联系 |
| app_update_receipts | 持久阶段事件、精确工件/源/发布绑定、重复与健康约束 |
| app_update_audit_events | 操作者/动作/原因/摘要/前后修订/结果，拒绝操作也可记录 |

历史外键采用 RESTRICT；不因删除账号而丢失发布审计，actorId 保存身份快照。JSON/JSONB 保存能力列表与有界快照，正式服务写入前使用可执行类型校验。禁止审计 details 存完整 URL、请求原文、令牌或私钥。

迁移 `20261029_27`（父 `20261027_26`）只增加上述十张表和索引，不改现有业务数据，不连接或自动升级开发数据库。Alembic upgrade head 重跑应无变化。只有十张表全部为空才可 downgrade；先检查所有表再删除，任何登记/事件/审计存在均拒绝。真实数据恢复使用兼容服务和前向修复，不能删除表伪装回退。

跨行的已发布不可变、严格版本高水位、真实证书核验、首包=1、来源字节相等、门槛可达、原子切换和完整回退范围仍需 T02/T05/T07/T08 事务实现；DB 类型/约束不能单独证明这些业务规则已经运行。

## 7. 错误和验收

错误结构 `{code,message,requestId,retryable}` 与 HTTP 状态由 schema.x-errors 固定；错误响应不能表示最新或授权安装。429 带 Retry-After；网络/5xx 有界退避，401 处理会话，403 无权限，404 发布不存在，410 停止，409 修订/幂等/工件未就绪，422 类型错误，426 协议不支持。

执行：`.venv/Scripts/python.exe tools/accept_m42_contract.py`。脚本创建 `.tmp/` 下专用 PostgreSQL 集群，随机回环端口和显式 aiyolo_app 角色；进程环境覆盖 DATABASE_URL，核对 data_directory、端口、用户，测试后清理 schema、关闭该实例并确认端口关闭。不会使用 `.env` 的开发库。

T01 测试包含：固定签名跨端金样、三类策略、双来源、恢复结果、重复键/错误 UTF-8/过期/重放/未知公钥/错上下文、迁移重跑、空库回退/有数据拒绝回退、唯一/复合外键、幂等/健康阶段及 CAS。真实 APK、MinIO、第三方 HTTPS、Android 覆盖安装和数据保护在后续任务验收，不能用本次模型测试替代。
