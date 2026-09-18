# PostgreSQL 本地开发

后端在配置 `DATABASE_URL` 时连接 PostgreSQL；未配置时明确保持进程内存回退，便于无数据库的单元测试和诊断运行。数据库密码只写入 Git 忽略的 `.env` 或部署环境，不写入源码、Alembic 配置和日志。

本机开发配置：

```text
PostgreSQL: D:\PostgreSQL
Service: postgresql-x64-17
Host: 127.0.0.1
Port: 5432
Database: aiyolo_dev
Application role: aiyolo_app
```

首次安装依赖和执行迁移：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
```

检查迁移版本：

```powershell
.\.venv\Scripts\python.exe -m alembic current
```

迁移和自动化测试必须使用独立测试数据库或进程内 SQLite，不得清空 `aiyolo_dev`。服务运行期间可通过 `/healthz` 查看数据库连接状态，但接口不会返回连接 URL、用户名或密码。

## 业务数据边界

以下业务状态由 PostgreSQL 统一保存，服务重启或多进程切换后仍可查询：

- `alert_rules`、`alert_rule_bindings`、`alert_rule_audits`：规则、来源绑定和变更审计。
- `model_parameter_profiles`、`model_parameter_audits`：按模型 ID、版本和平台保存参数档案及修订记录。
- `alert_verification_config`、`alert_verifications`：复核开关、每日额度、用量和每事件复核结果。
- `alert_delivery_receipts`：管理页、App、邮件、短信和企业 IM 的投递结果、尝试次数和安全错误码。
- `conversion_config`、`conversion_jobs`：转换配置、任务快照、排队/执行/失败/重试/中断状态。
- `alert_events`、`alert_disposition_actions`、`false_positive_feedback`：移动端和服务端自产告警、确认/误报处置及回流记录。

以下内容刻意不进入数据库：模型权重、TFLite/ONNX/PT 转换产物、转换日志和工作目录、告警截图二进制、实时视频帧、候选告警状态、WebSocket 短生命周期队列，以及任何密钥或令牌。数据库只保存截图和产物的相对引用、哈希、状态和审计元数据。

服务端检测正式事件的顺序是：模型参数评估 → 生成确认事件 → PostgreSQL 注册 → 写入截图引用 → 异步投递。数据库写入或投递异常会在流诊断状态中暴露，不能让视频推理线程崩溃。服务重启后会从 PostgreSQL 恢复已确认/已结束事件；逐帧候选计数不恢复，需要重新满足连续帧和停留时间。

## 生产连接要求

- 使用独立的最小权限应用角色，不使用 `postgres` 超级用户运行服务。
- `DATABASE_URL` 由部署环境或密钥管理服务注入，不写入镜像、源码和日志。
- 数据库与服务不在同一可信主机时启用 TLS，并在连接 URL 中要求证书校验。
- 先执行 `alembic upgrade head`，迁移成功后再启动新版本服务；禁止用
  `Base.metadata.create_all()` 替代生产迁移。
- PostgreSQL 不可用或表结构未迁移时，已配置数据库的服务启动会失败，不会静默回退
  到内存存储。这样可避免恢复后出现两套互相冲突的数据。

## 备份与恢复演练

使用 PostgreSQL 客户端工具做自包含格式的逻辑备份：

```powershell
pg_dump --no-password --format=custom --file=aiyolo_dev_20260914.dump --dbname="$env:AIYOLO_PG_URL"
pg_restore --clean --if-exists --dbname="$env:AIYOLO_RESTORE_PG_URL" aiyolo_dev_20260914.dump
```

`AIYOLO_PG_URL` 和 `AIYOLO_RESTORE_PG_URL` 使用 PostgreSQL CLI 支持的
`postgresql://...` 格式，不使用 SQLAlchemy 专用的 `postgresql+psycopg://...` 前缀。
恢复 URL 必须指向独立的恢复验证数据库，不能指向正在运行的开发库或生产库。恢复后
执行 `alembic upgrade head`，启动服务并检查 `/healthz`、告警列表、事件详情和误报导出。
备份文件应加密、限制访问、配置保留周期，并定期验证实际可恢复性。

真实 PostgreSQL 集成测试默认关闭，避免普通测试误连开发数据库。确认 `.env` 指向专用
开发数据库后可显式运行：

```powershell
$env:RUN_POSTGRES_TESTS='1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_alert_postgresql.py" -v
Remove-Item Env:RUN_POSTGRES_TESTS
```

集成测试只创建带随机 ID 的事件并在结束时按精确 `eventId` 清理，不会清空数据库。
