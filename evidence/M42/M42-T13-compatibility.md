# M42-T13 当前 HTTP 试用包兼容声明

日期：2026-11-06。对应 FR-12；这是当前两个明确构建产物的保守构建声明，不是在线覆盖安装、恢复包或生产兼容性验收。

适用且仅已评审的候选：

| versionCode / versionName | APK SHA-256 |
| --- | --- |
| 1 / 0.1.0 | 666eca0ba8b25b0af669dc05baf824461659c7bfc018aa6419c52f918bdecd21 |
| 2 / 0.1.1 | 611089263c0b795ec0ce0b983fee3da66fd3a5de07cafa364b25a63b77c9ffc9 |

两个APK由M164同一源码生成，版本号递增，没有数据库结构或升级协议变更。依据M164实际编译/签名/核验清单与111项升级JVM回归，声明serverContract范围仅1到1，Room数据schema及可读范围仅20到20，不声称读取更早数据库或兼容未来服务契约。M165已在PKX110安装原始v1并核对实际文件/证书/版本和启动成功。

证据：
- E:/aiyolo/mobile-app/harness/evidence/M164/verification.md
- E:/aiyolo/mobile-app/harness/evidence/M164/package-manifest.json
- E:/aiyolo/mobile-app/harness/evidence/M164/debug-jvm/
- E:/aiyolo/mobile-app/harness/evidence/M165/phone-v1-install.md

启用前重新核对两份APK的大小、SHA-256与v2签名，并验证实际配置工厂及独立公钥。配置仅供当前环境登记这些候选；后续不同构建不得直接沿用，需重新评审契约/数据库版本及真实兼容证据。既有配置加载器是操作员信任声明，不是逐APK自动兼容证明，APK完整验签与全局版本水位门禁继续生效。

未完成：v1到v2在线覆盖安装、原始数据保留、较早schema迁移、API27真机、双来源及高版本恢复。不得用本声明关闭M42-T10、Android M118或正式发布门禁。后台启用本身不创建或发布任何版本。
