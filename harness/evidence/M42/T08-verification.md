# M42-T08 安全加固验证

日期：2026-10-29。仅服务端安全子任务，未部署生产、未修改 Android。

## 实现

- 发布、停止、回退、外链登记、MinIO 上传入口逐次校验动态会话、启用状态和 PLATFORM_ADMIN。请求体接收后重检，会话摘要带入数据库写事务核对撤销、到期及账号；异步已接受作业继续按租约和当前账号权限执行。
- 双来源入口补充有限 IP 桶、并发与速率预算、no-store、查询参数拒绝、重复/深层 JSON 拒绝、SQL 错误脱敏及异常释放名额。
- 上传完成增加 SQLite 写锁与跨来源幂等校验；仅终态暂存文件可清理，数据库失败保留租约供恢复扫描清理。
- 审计绑定操作者、原因摘要、结果、策略前后修订、工件及来源修订；API 已解析管理操作被拒绝另留 rejected 事件。原因脱敏 URL、Bearer、PEM 及常见凭据形式；核验证据引用只记摘要，不回显 SQL/原始异常或任意审计详情。
- 外链拼接重定向前拒绝控制字符、空白、反斜线及重复 Location，拒绝响应长度歧义和不支持的传输编码；保留 DNS 每跳检查、固定 IP/TLS 域名验证和无业务认证头。
- 退役来源使用冻结协议已有 failed 投影，details.sourceState 保留 retired，不能用于发布。

## 验证证据

主验收：`T08-verified-20261029T064811Z-result.json`。

| 测试文件 | 数量 | 结果 |
|---|---:|---|
| test_app_update_security.py | 31 | 全部通过，SQLite + PostgreSQL |
| test_app_update_service.py | 32 | 全部通过，含并发发布/停止/回执 |
| test_app_update_rollback.py | 16 | 全部通过，含回退/发布并发与幂等 |
| test_apk_external.py | 21 | 全部通过，含并发登记/认领、SSRF、DNS变化、租约清理 |
| test_apk_uploads.py | 16 | 全部通过，含不可变来源、重复字节、清理失败与重试 |
| test_apk_verification_jobs.py | 12 | 11 通过；1 个 SDK 条件测试未启用 |
| test_app_update_contract.py | 6 | 全部通过，schema/金样未变更 |
| test_app_update_storage.py | 18 | 全部通过，SQLite/PG 约束、迁移重跑及回退限制 |

合计 152 个用例：151 通过，1 条件跳过。随机端口 61970，非开发库；专属 schema 已清理，实例端口已关闭。

真实 TLS/签名 APK 回归：`T08-tls-20261029T064957Z-result.json`，2 项全部通过；使用真实 aapt2/apksigner、独立临时 PostgreSQL 和受控 HTTPS 源，完整核验 24,796 字节 APK，来源替换拒绝、不保留托管副本、无 Cookie/Bearer 外传，状态码/截断/截止时间/证书校验通过。原始报告：`T08-tls-raw/external-tls-integration.json` 及子目录核验报告。随机端口 53933，schema 已清理且端口关闭。测试连接工厂把已验证测试公网 IP 映射到回环 TLS，生产代码无地址或证书绕过；不是正式公网部署验收。

最终权限矩阵额外加入真实 PROJECT_OWNER membership 后重跑 `test_app_update_security.py`，31 项全部通过，见 `T08-role-final-20261029T065155Z-result.json`。随机端口 64898，schema 已清理，端口已关闭。

Harness：`T08-harness-tests.log`，34 项通过；Python compileall 通过；validate 通过。完成后再次执行 Harness 单测、validate/render。

## 失败保留与修复

- `T08-initial-20261029T064226Z-result.json`、`T08-security-20261029T064533Z-result.json`：沙箱临时目录 PermissionError，无数据库测试执行；经工具审批后在相同隔离流程重试。
- `T08-initial-20261029T064244Z-result.json`：既有直接构造 ASGI Request 的两个上传用例缺省 query_string，引入查询参数检查后出现 KeyError。入口改为安全读取 scope 默认空串，原测试保持，后续上传 16 项全部通过。失败日志未删除。
- `T08-security-20261029T064638Z-result.json`：安全矩阵初版 24 项与上传 16 项全部通过；后续补充深层 JSON、清理数据库故障、异常 code、并发上传等形成最终 31 项。

## 限制与后续归属

- 入口限流按进程；多 worker/多实例及未认证流量需要反向代理全局限流。数据库临时不可用时无法写审计，保留固定字段请求遥测和作业租约补偿。
- 脱敏针对已知结构，运维仍不得把任意格式秘密写到原因/说明；生产私钥和存储凭据只从受控配置读取。公开外链只保存在核验/交付所需数据库字段，管理投影和审计不返回完整 URL。
- 登录退出不取消已受理的异步作业；账号降权/停用在最终晋级前再次核对，撤权后不能新增可用来源。已提交事务或已交付文件不可追回。
- 公开链接可被托管方替换，Android 的摘要、生产证书、版本/包名和安装前许可检查仍是必须条件。
- T09 承接真实 MinIO + 第三方 HTTPS + 管理后台联合闭环；T10/M118 承接覆盖安装、数据保留与 100→101→102 恢复。生产证书、独立元数据密钥、正式域名、显示名称、厂商真机和许可证/SBOM 门禁未在本任务验收。生产默认 APP_UPDATES_ENABLED=false。
