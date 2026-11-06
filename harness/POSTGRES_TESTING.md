# PostgreSQL 集成测试连接约定

适用于 `tests/postgresql_support.py` 驱动的 PostgreSQL 集成测试。目标是避免测试把应用 `.env` 中的账号误用于一个未按相同身份初始化的临时 PostgreSQL 集群，也避免误操作开发/生产数据。

## 配置来源与当前开发连接

- `app/config.py` 的 `Settings` 默认从当前工作目录 `.env` 读取 `DATABASE_URL`；同名进程环境变量优先级更高。
- 当前开发服务的已验证连接端点为 `127.0.0.1:5432/aiyolo_dev`，角色为 `aiyolo_app`。凭据只保存在本机 `.env`，禁止复制到 Harness、日志、命令行记录或证据文件。
- 当前开发连接只用于本机服务。未经任务明确授权，集成测试不得对 `aiyolo_dev` 创建/删除测试 schema、运行迁移或改写数据。

## 隔离 PostgreSQL 测试的唯一推荐方式

1. 在仓库 `.tmp/` 下创建一次性 PostgreSQL data directory，并为实例分配专用回环端口；确认端口未占用，记录 data directory、端口和进程身份。
2. 初始化集群时显式创建与测试 URL 一致的角色，例如 `initdb -D <精确临时目录> -U aiyolo_app ... --auth-local=trust --auth-host=trust`。不可省略 `-U` 后依赖 Windows 当前用户名，也不可假定 `DATABASE_URL` 会自动创建角色。
3. 启动后对**这个临时实例**使用连接 URL `postgresql+psycopg://aiyolo_app@127.0.0.1:<临时端口>/postgres`。`postgres` 数据库由 initdb 默认创建；不要继承 `.env` 的 `aiyolo_dev` 数据库名或凭据。
4. 在启动测试进程前通过进程环境变量覆盖 `DATABASE_URL`，并设置 `RUN_POSTGRES_TESTS=1`。不得改 `.env`。测试辅助器读取 `settings.database_url`，在 URL 所指定的数据库中创建随机 schema，将 Alembic `search_path` 指向该 schema，并在退出时只删除该 schema。
5. 每次连接前打印/核对脱敏后的 driver、用户名、host、port、database；测试启动前断言端口、data directory 与本次临时集群一致。遇到 `role does not exist`、`database does not exist` 或 endpoint 不匹配时停止，不要对应用库试错，也不要临时创建账号来掩盖配置错误。
6. 测试完成后确认 schema 清理完成；只对本次精确 data directory 执行 `pg_ctl stop -m fast`，并验证临时端口已关闭。不要停止其他实例或服务。

示例（PowerShell；`<临时端口>` 和 `<精确临时目录>` 必须由本次运行显式确定，不可照抄成固定值）：

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://aiyolo_app@127.0.0.1:<临时端口>/postgres'
$env:RUN_POSTGRES_TESTS = '1'
python -m unittest discover -s tests -p 'test_scene_execution_parameters.py'
```

如果没有隔离 PostgreSQL，不得将测试 URL 回退到 `.env` 的 `aiyolo_dev`；运行非 PostgreSQL 测试并明确记录 PG 验收未执行。
