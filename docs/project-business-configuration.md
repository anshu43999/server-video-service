# M33-T07 项目业务配置分层

> M33-T13 更新：平台 `/metrics` 改用 platform.observability.read，只返回机器资源与流聚合数字，不返回跨项目流明细；完整报告、审计检索与留存见 `project-reporting-observability.md`，替代下文 T07 时点的全局诊断说明。

业务入口使用 `/aiyoloapi/projects/{projectId}/...`，服务端从认证会话重新解析项目成员关系、能力及生命周期。历史业务路径必须携带 `X-Project-Id`；缺失返回 400，不选择默认项目。不可见项目或其资源返回 404，可见但缺少写能力返回 403。

## 权限与数据边界

| 业务 | 项目路径 | 读取能力 | 修改能力 |
| --- | --- | --- | --- |
| 告警规则与来源绑定 | `rules`、`rules/{ruleId}/bindings` | `project.read` | `project.rules.manage` |
| 来源能力列表 | `capabilities/sources` | `project.streams.view` | 无写入入口 |
| 获分配版本的模型参数 | `models/{modelId}/parameters?platform=server\|android&version=...` | `project.read` | `project.models.assign` |
| 复核策略 | 已退役（旧接口返回 410） | 不提供 | 不提供 |
| 投递策略 | `delivery/policy` | `project.read` | `project.settings.manage` |
| 看板与聚合指标 | `dashboard/stats`、`metrics` | `project.read` | 无写入入口 |
| 规则审计 | `rules/audit` | `project.audit.read` | 无写入入口 |

项目负责人具有相应管理能力，项目用户读取配置并使用获准功能。平台超级管理员显式进入项目，身份仍来自会话并记录进入审计。客户端 `X-Operator-Id` 不能伪造操作人。

平台参数入口为 `/aiyoloapi/platform/models/{modelId}/parameters`，要求 `platform.models.manage`。复核供应商连接、凭据、转换配置、机器运行指标等由平台管理，项目策略只保存业务选择。项目看板传入空的 `system`，项目指标只返回流数量和三个帧数总计；完整机器和流诊断的 `/aiyoloapi/metrics` 要求平台管理能力。项目 ID 是响应上下文，不作为动态指标标签或字段名。

## 参数覆盖、继承与 revision

平台默认与项目覆盖使用独立 revision。未覆盖时返回 `source=inherited`、项目 `revision=0` 和平台 `inheritedRevision`。项目 DELETE 重置保留新的项目 revision 和继承标记；以后平台默认更新即时生效，不重新改变项目 revision。实际服务端告警运行按项目读取覆盖参数。

所有 HTTP 配置写入必须提供 `expectedRevision`。首次参数/策略写入是 0，规则创建由服务端固定为 0；旧 revision 返回 409，不产生部分写入。规则绑定、拒绝绑定及解绑都会推进 `ruleVersion`。删除规则只清除当前项目绑定，历史审计保留。复核配置更新保留当前日已使用额度，修改额度不会重置使用次数。

PostgreSQL 写事务先锁项目行，覆盖首次创建没有配置行可锁的情况。策略、参数、规则和复核修改在同一事务记录项目审计；平台默认写入记录平台审计。记录包含真实账号、请求 ID、修改前后快照及 revision；首次创建的旧快照/旧 revision 为 null。内存审计也保存独立快照，后续规则绑定不会修改历史记录。

绑定来源只能来自当前项目的持久流配置或运行会话，模型必须匹配来源。客户端能力列表不参与授权或兼容判定；TRACK 只取实际运行检测能力，停止状态的 BOX 模型不默认具有 TRACK。运算符要求与用户要求合并，不能通过减少 `requires` 让 LINE_CROSS/DWELL 绕过跟踪要求。

## 生命周期与发送

归档项目对负责人和平台超级管理员只读，普通项目用户不可见；参数、规则、策略修改返回 403。停用或归档项目不再入队投递；每次真正调用通道（包括重试）前重新检查生命周期、通道及严重级别策略。已入队但后来被拒绝的投递记录 `cancelled`、错误码 `project_inactive_or_policy`，attempts 只计实际发送次数。已开始的供应商调用不能撤销，此处保证之后不再开始新的发送/重试。

投递阈值使用 MINOR/MAJOR/CRITICAL，兼容 NORMAL/IMPORTANT/URGENT；看板使用同一映射。复核 HTTP 客户端不能声明供应商已配置；当前复核无真实供应商适配器，返回可诊断失败。邮件、短信和企业 IM 仍为既有本地适配器，并未因增加项目策略而启用真实外部服务。

## 数据库升级与回滚

`20261010_08` 增加参数 `scope` 和 `project_business_config`。默认项目旧参数作为 PLATFORM；其他项目旧参数作为 PROJECT，保持原 `mp-...` 主键及审计/分配复合外键。默认项目的新覆盖使用 `project-mp-...`，允许与平台默认共存，唯一约束包含 scope。

旧 JSON 自动导入只接收平台键（允许历史 projectId 缺失或 null），不把命名空间中的项目覆盖提升成平台参数。平台导入使用默认项目行锁，避免多实例首次导入冲突。项目 JSON 到生产库的全面迁移仍由 M33-T14 承接。

如果存在项目策略或 PROJECT 参数行，downgrade 明确拒绝，不自动丢弃或合并配置。需先备份并执行经确认的迁移方案；空配置库的降级/重升和 Alembic metadata 一致性有集成测试。

## 验证入口

普通回归使用空 `DATABASE_URL`，`tests/test_project_business_configuration.py` 验证内存、SQLite 与认证 HTTP，覆盖规则/来源隔离、能力伪造、参数继承、生命周期、投递取消、审计、实际运行事件、看板及指标。

`RUN_POSTGRES_TESTS=1` 下运行 `tests/test_project_business_postgresql.py`，使用随机独立 schema 验证多实例首次写入与更新 CAS、并发额度、重连持久化、默认项目 scope 分离、旧外键迁移与有数据回滚拒绝。不会连接 public 业务表做清理。完整测试结果与命令见 Harness 完成记录。
