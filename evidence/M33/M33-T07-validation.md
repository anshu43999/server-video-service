# M33-T07 验证记录

日期：2026-10-12（Asia/Shanghai）。工程：`E:\aiyolo\server-video-service`。

## 实测结果

- 普通相关回归：75/75 通过，43.695 秒。
- PostgreSQL 随机 schema 集成：7/7 通过，6.556 秒。
- Harness 单元测试：30/30 通过；validate、render 通过。
- `compileall -q app tests` 与 `git diff --check -- app tests alembic docs` 通过。
- PostgreSQL Alembic `command.check`：No new upgrade operations detected。

普通回归使用空 DATABASE_URL，按以下测试模式构造同一 unittest suite：

```text
test_project_business_configuration.py
test_admin_operations_api.py
test_model_parameters.py
test_model_parameters_api.py
test_dashboard_stats.py
test_account_auth.py
test_multi_project_migration.py
test_project_lifecycle_migration.py
test_project_authorization.py
test_project_management_api.py
test_project_stream_isolation.py
test_project_alert_isolation.py
test_alert_verification_api.py
test_alert_delivery_api.py
test_server_alert_runtime.py
test_alert_delivery.py
test_alert_rules.py
```

PostgreSQL suite 使用 RUN_POSTGRES_TESTS=1、RUN_POSTGRES_MIGRATION_TESTS=1，读取本地数据库配置而不打印凭据，模式如下：

```text
test_project_business_postgresql.py
test_verification_delivery_postgresql.py
test_multi_project_migration_postgresql.py
```

## 主要证据

`tests/test_project_business_configuration.py`：15 项测试覆盖平台与默认项目独立覆盖/重置、SQLite scope 共存、JSON 平台导入排除项目命名空间、实际告警运行阈值差异、看板事件/额度/流聚合隔离、同名规则绑定/删除/CAS 与审计快照、客户端来源/模型/能力伪造、项目指标过滤、平台指标授权、真实会话操作人、归档读取与写拒绝、投递严重级别/通道及重试停用。

`tests/test_project_business_postgresql.py`：4 项测试覆盖独立存储实例并发首次创建与更新（参数、投递、规则、复核）、并发复核额度不超限及配置变更不重置用量、数据库重连、默认项目 PLATFORM/PROJECT 共存与动态继承、migration07 旧参数主键和审计/分配外键升级后保留，以及存在项目覆盖时 downgrade 拒绝且数据和版本保留。

另外 3 项 PostgreSQL 测试覆盖双项目复核结果/额度与回执重连、旧库升级重复执行、metadata 对齐及无项目覆盖时 downgrade/re-upgrade。

## 实现说明与边界

业务配置权限、接口、继承、并发、审计、生命周期和回滚行为详见 `docs/project-business-configuration.md`。本任务没有执行生产库升级或停止运行中的服务。

复核真实供应商尚未接入，邮件/短信/企业 IM 仍为既有本地适配器；已开始的发送调用无法撤销，但后续发送及重试重新检查项目状态和策略。完整模型分配治理由 M33-T08 承接，全量历史数据与文件迁移由 M33-T14 承接，整个 M33 的全链路验收尚未完成。
