# M33-T20 审批后端本地验收（2026-10-14）

范围仅服务器侧：安装证明、完整清单、人工审批、领取、在线校验/结果回执、来源上传守卫与SQLite/PG持久化。本轮没有修改Android工程、PC审核界面，没有运行容器或读写真实业务库。

## 结果

隔离原生PostgreSQL临时集群及SQLite文件数据库均通过。脚本保存原始逐套件退出码、测试摘要、日志绝对路径、临时目录、真实PG数据库进程重启结果：

- [机器可复验报告](M33-T20-backend-acceptance.json)
- 测试运行器：tools/accept_mobile_legacy_approval.py（白名单环境、临时cwd、临时schema/进程；结束停止临时PG，不自动删除合成诊断）。

真实FastAPI/SQL审批每库32条、真实双HTTP服务进程/nonce/CAS/杀进程重启/原生备份恢复/迁移精确校验每库3条、真实旧告警上传门禁和撤销/媒体竞态/事务审计失败每库6条，共82次。原T19签名与状态金样64条，鉴权、服务主体、数据库、移动告警、SQLite/PG迁移、默认项目回滚、报表和演练等回归共76条。**合计222条全部通过，PG迁移测试不是skip**。另脚本在已领取并COMPLETED的真实PG数据上停止/重启数据库进程，复核同实例ID、operation、回执、现态均持久。

具体可定位门禁：

| 检验 | 证据 |
| --- | --- |
| P256签名挑战、丢注册响应同key恢复、禁用账户/会话/安装、固定默认项目成员、动态管理员、自审批、unknown/mixed | tests/test_mobile_legacy_approval_api.py |
| 11字段绑定、双摘要、清单排序/重复/大小/非法类型、签名改体、时间边界、有效失败nonce消费、持久化幂等/限流 | tests/test_mobile_legacy_approval_api.py |
| 拒绝/撤销/重代次、一经claim永久operation锁；结果迟到、aborted需reconcile、不可改committed、exact TTL、列表过滤分页 | tests/test_mobile_legacy_approval_api.py |
| SQLite/PG Head schema Alembic check、SQLite早期默认值兼容、已有安装拒绝降级、旧数据库迁移回归 | tests/test_mobile_legacy_approval_persistence.py + tests/test_default_project_rollout.py + tests/test_default_project_rollout_postgresql.py |
| 两个独立OS进程共享同库，管理员竞争只有一个成功、相同签名nonce只有一方成功；服务端杀进程与丢响应原幂等恢复 | tests/test_mobile_legacy_approval_persistence.py |
| 审计数据库插入触发器故障：审批状态和permit均不提交；旧告警写入+审计同事务失败关闭 | tests/test_mobile_legacy_approval_api.py + tests/test_mobile_legacy_approval_ingest.py |
| 告警POST完整原始字节签名、变造operation/binding/未签名覆盖、媒体I/O中撤销、旧数据处置同一事务及本人身份 | tests/test_mobile_legacy_approval_ingest.py |
| 新状态/角色不影响原项目业务鉴权、服务身份、历史数据迁移，旧无标记新产生告警行为不变 | 报告中的 regression 套件 |

## 已知边界和后续

- LEGACY_APPROVAL_ORIGIN默认禁用，只有受审配置、SQL迁移并满足T19流程后才可试用。PC审批体验为M33-T21，Android双摘要适配、Keystore、Room隐藏事务和读取/上传来源标记为M100-T05；PC/Android/API27/真实媒体联合验收为M33-T22。T22之后还必须完成T18本地联合验收，最后才允许T17容器部署。
- 安装证明只能证明持有密钥；清单hash不能自行证明所有权；客户端是否正确标记全部旧数据、Room/媒体真实一致性与断电/ENOSPC未由本任务证明。旧数据原件未读取、迁移、删除。
- 无法保证原本未标记的上传可被服务端准确识别为旧数据；Android T05必须实施来源标记与本机读/上传门禁。服务端仅实时阻断显式携带legacyApproval的告警；已接受/导出内容不能远程撤销。
- 同origin数据库克隆不能被软件自动察觉；异环境克隆必须停用功能并经单独运维审批轮换实例与撤销复制登记。旧单项目便携迁移工具明确拒绝已经升级的审批库，验证新库采用原生SQLite备份或pg_dump/pg_restore，不绕过受保护的历史记录降级约束。
- 审批历史、nonce、permit和审计不自动删除；后续必须配套容量监控和获批的长期保留政策。已见Starlette/httpx弃用告警，没有私自升级依赖。没有容器性能/负载压测或真实网络断电证据。
