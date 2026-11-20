# M33-T08 验证记录

日期：2026-10-12（Asia/Shanghai）。工程：`E:\aiyolo\server-video-service`。

## 实测结果

- 全量普通测试：518/518 通过，19 项按环境条件跳过；使用空 `DATABASE_URL` 避免连接外部数据库。
- SQLite 项目模型授权存储：3/3 通过（含快照、CAS、项目隔离、活跃流保护、项目生命周期和参数竞态）。
- PostgreSQL 隔离 schema assignment 存储：8/8 通过；覆盖并发首次写入/更新、参数快照、项目隔离、迁移旧数据和禁止降级。
- PostgreSQL 多项目迁移：1/1 通过；重复升级、metadata 对齐、降级/再升级和 Alembic `command.check`（No new upgrade operations detected）。
- Harness 单元测试：30/30 通过；`validate` 和 `render` 通过。
- `python -m compileall -q app tests`：通过。

## 覆盖范围

`tests/test_project_model_assignments.py` 覆盖平台管理员与项目负责人/项目用户权限、场景唯一分配、目录和下载隔离、版本固定、参数快照、撤权回退原图、活跃流切换保护、项目暂停和恢复拒绝。

`tests/test_project_model_assignment_storage.py` 覆盖 SQLite/PostgreSQL 持久化、CAS、并发锁、旧 assignment 禁用、快照存在时禁止 downgrade。

实现文档见 `docs/project-model-assignments.md`。本任务未修改 Android、未提交或推送 Git，也未执行生产库升级或停止运行中的服务。
