# M36-T03 验证记录

日期：2026-10-19。实现：`app/project_scenes.py`、`app/database.py`、Alembic `20261019_14`；API 说明：`docs/project-scenes.md`。

场景与成员采用项目复合键、精确版本与目标端、连续位置；管理 capability、CAS、生命周期、模型端就绪/发布与输入适用性校验生效。创建未批准、修改清除批准；多成员 sync/async 只存配置，不改变任何推理行为。旧 assignment 为幂等只读兼容视图，保留全部引用与 revision，禁止同 ID 覆盖。

## 实际测试

环境：项目 `.venv/Scripts/python.exe`、PYTHONPATH=tests、TEMP/TMP 指向 `.harness-python-temp`、RUN_POSTGRES_TESTS=1。

unittest 模块 test_project_scenes、test_database、test_project_authorization、test_project_model_assignment_storage：40 tests，全部通过、无跳过，48.204 秒。

- 场景专项 15 项（包含 4 项隔离 PostgreSQL 测试）；覆盖创建、增删排序、改名、停用、输入/端校验、权限、同 ID 跨项目隔离、过期 revision、旧 assignment 不变、审计与无部分更新。
- SQLite/隔离 PostgreSQL 重新打开持久化、失败审计事务回滚、非活动项目拒绝写。
- 两个独立进程锁模拟的 store 对同 PostgreSQL 项目行同时创建/更新：一个成功、另一个冲突。
- Alembic 新表迁移重复执行幂等，非空 downgrade 拒绝且保留数据。隔离 PostgreSQL 从既有完整迁移链升级到 head 成功，未修改生产 schema。
- 既有数据库、权限矩阵及模型分配 SQLite/PostgreSQL 快照/CAS 回归通过。

Harness 34 tests passed；validate passed；目标文件 diff check 和新模块 compileall passed。

## 边界

未部署、未提交/推送 Git、未执行真实模型推理或 Android 真机验收。批准与普通用户获准目录在依赖任务 M36-T04 实现，当前只向管理 capability 开放配置；没有提前授予未批准场景的下载/运行权限。
