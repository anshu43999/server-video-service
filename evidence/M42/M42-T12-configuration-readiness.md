# M42-T12：现有环境升级签名与配置准备

日期：2026-11-06（Asia/Shanghai）

## 范围及需求覆盖评审

用户要求推进现有环境的 App 升级准备，不新建隔离部署环境；APK HTTPS 下载直链由管理员在每次「新建版本」时填写。依据 PRODUCT_REQUIREMENTS.md 的 FR-12，本任务仅接入既有正式签名身份与本机核验工具，不发布版本、不启用分发、不重启服务、不修改手机数据。

- FR-12 正式包身份与全局版本水位：登记 com.aiyolo.inspection，first_version_code=1、version_high_water=0；重复执行保留身份和水位，冲突拒绝覆盖。
- FR-12 独立可信签名：使用现有 APK 公钥证书和独立 Ed25519 升级元数据密钥，未生成或轮换密钥；数据库只存公开摘要及 keyId。
- FR-12 外链发布：不固定 APK 下载地址、不要求 MinIO 上传凭据，保留已有填写直链、完整核验、创建草稿、单独发布流程。
- FR-12 安全门禁：三个开关仍为 false；不伪造兼容性证据，不以本任务替代 M42-T10 / Android M118 联合验收或生产放行。

## 落地配置

1. E:/aiyolo/config/app-updates/scopes.json：单一发布范围。publisherId=aiyolo，packageName=com.aiyolo.inspection，channel=enterprise-stable，deploymentId=primary，contractVersion=app-update/v1。上述为本次选定的技术标识，后续客户端信任配置必须一致；primary 不表示另建环境。
2. server-video-service/.env：追加 APP_UPDATE_KEY_ID、APP_UPDATE_PRIVATE_KEY_PATH、APP_UPDATE_SCOPES_PATH 与 AAPT2/Java/apksigner 路径；APP_UPDATES_ENABLED、APP_APK_EXTERNAL_ENABLED、APP_APK_WORKER_ENABLED 全部 false。
3. 原 .env 前 430 字节 SHA-256 仍为 55aa0c3db50f3e451157d921811dcc25e9ee28711587fb1a795d5ca5e71be37e，原有配置未被替换；git check-ignore 确认 .env 被忽略。本文不复制原配置、私钥或口令。
4. tools/init_app_update_identity.py：默认只检查，显式 --apply 才登记；仅插入缺失的 AppIdentity，不更新已存在身份，不改版本水位。PostgreSQL 使用事务 advisory lock，异常回滚。

公开身份：

- APK 证书 SHA-256：cf4ef605ec59b4a647c2c6776393379efac9ac56fbbc1e9b5ec5f8627c48ddf8
- 升级元数据 keyId：aiyolo-app-update-20261106-01
- 私钥位置沿用 E:/aiyolo/secrets/app-update-signing/，APK 密钥位置沿用 E:/aiyolo/secrets/app-signing/；不改变 ACL。

## 现有环境实测结果

- 引导脚本只读执行：would_create；第一次 --apply：created；第二次 --apply：unchanged，versionHighWater 始终为 0。
- 前后升级表计数：app_update_identities 从 0 变为 1；app_artifacts、app_artifact_sources、app_update_policies、app_releases、app_update_policy_revisions、app_rollback_operations、app_update_device_states、app_update_receipts、app_update_audit_events、app_apk_uploads 均保持 0。唯一业务写入是登记公开 App 身份，不运行迁移、不创建测试发布或操作其他业务表。
- 通过实际 Settings 和 AppPublisher.from_settings 加载现有密钥，公私钥匹配；使用真实签名器及 verify_envelope 验证自检报文成功，篡改报文被 InvalidSignature 拒绝。报文仅驻留内存，时间固定在 2000-01-01 并用同一测试时钟验证，不能作为当前安装授权。
- 实际 false 配置下 configured_updates 拒绝服务；仅对内存中的 Settings 副本临时设 true 后构造服务对象成功，并以只读方式检查已登记身份。未改变环境开关、未挂载 HTTP 路由、未发布策略。
- AAPT2：Android Asset Packaging Tool (aapt) 2.20-13193326。
- Java：OpenJDK JBR 21.0.11+1-1163.116。
- apksigner：0.9（SDK build-tools/36.0.0/lib/apksigner.jar）。
- 核验结束时现有监听 PID 未变：8080 为 34060，5173 为 10136；本任务未重启它们，新配置尚未由运行中服务重新加载。

## 自动化测试

在 E:/aiyolo/server-video-service 执行：

| 命令 | 结果 |
|---|---|
| .venv/Scripts/python.exe -B -m unittest discover -s tests -p test_app_update_identity_bootstrap.py -v | 6 通过；覆盖只读、创建、重复执行保留水位、三类身份冲突及事务回滚 |
| .venv/Scripts/python.exe -B -m unittest discover -s tests -p test_app_update_contract.py -v | 6 通过 |
| .venv/Scripts/python.exe -B -m unittest discover -s tests -p test_app_update_service.py -v | 17 通过，15 个独立 PostgreSQL 用例跳过 |
| python -m unittest discover -s harness/tests -p test_*.py | 34 通过 |

合计 63 个用例通过、15 个跳过。服务回归第一次受 Windows 沙箱临时目录权限影响失败（无法打开 SQLite/临时密钥文件），随后获准在沙箱外原命令重跑通过；没有修改测试断言或放宽密钥权限。服务测试用临时 SQLite、身份测试用内存 SQLite，未把应用数据库用于回归测试。真实环境数据库仅用于上述公开身份登记及只读核验，不能视作 PostgreSQL 集成测试覆盖。

完成门禁复测补充：完成记录生成后再次执行 Harness 测试曾因 Windows 沙箱临时目录权限出现 5 个错误；批准在沙箱外同命令重跑后 34 个全部通过。Harness validate 和 render 均通过。该权限错误不视作产品断言失败，也不隐去首次失败。

## 尚未完成 / 下一阶段输入

1. App 调用的后台 HTTPS 服务地址及可信 TLS：与每版 APK 下载直链不同；需要确认真实服务地址后绑定客户端信任。
2. 客户端公钥及发布范围接入、正式签名 APK 基线和升级候选包、真实版本/数据兼容性验证。目前 APP_APK_COMPATIBILITY_PATH 未配置，不生成占位兼容证据。
3. 现有手机安装包签名及数据保留过渡方案仍需核验；本任务没有读取或操作手机，也没有卸载、覆盖安装或清数据。
4. 正式密钥的独立安全备份和恢复验证仍未完成；不能把单机文件存在当作备份。
5. 满足依赖和部署门禁后再启用外链核验、受控重启并进行真实端到端测试。APK 下载地址继续由管理员按版本填写。

目前「新建版本」仍受 !config?.externalEnabled || busy 禁用条件控制；本任务没有启用 externalEnabled，因此不能声称按钮或升级闭环已恢复可用。配置准备完成不代表生产可发布。
