# 告警处置闭环与误报回流（M11-T09 / M29）

服务端提供只读告警查询与管理员处置接口。告警快照由运行时调用
`app.alerts.disposition.alert_disposition_store.register(event)` 登记。

当配置了 `DATABASE_URL` 时，告警事件、检测结果、参数快照、证据引用、处置历史和
误报反馈均写入 PostgreSQL；服务重启后仍可查询。未配置数据库时才使用明确的进程内
存储，仅适合单元测试或无数据库诊断运行，进程退出后数据会丢失。数据库连接和表结构
状态可通过 `/healthz` 查看。

## 权限

- `GET /api/alerts`、`GET /api/alerts/{eventId}` 和误报导出允许管理员或操作员动态 Session，
  移动端可通过 `X-Video-Service-Token` 兼容头传递动态访问令牌。
- `POST` 处置接口只允许管理员动态 Session。操作人从 `X-Operator-Id`（兼容
  `X-Actor`）读取，不接受请求体中的 actor，避免伪造审计身份。

## 管理后台告警中心

告警中心直接读取 `GET /api/alerts` 返回的持久化事件，不使用本地示例告警。导航徽标和
“全部、严重、重要、一般”筛选数量均由同一批真实事件计算；空库显示 `00` 和明确空状态，
查询失败则清空列表并显示“告警数据不可用”，不会继续展示旧数据。

点击列表项后，详情、证据截图和事件元数据均来自对应 `eventId`。复核状态通过
`GET /api/alerts/{eventId}/verification` 获取；确认告警、标记误报和发起复核使用同一个
真实 `eventId` 调用服务端接口。严重筛选对应 `CRITICAL`，重要对应 `MAJOR`，其他级别归入
一般。

## 处置接口

```text
POST /api/alerts/{eventId}/acknowledge
POST /api/alerts/{eventId}/false-positive
POST /api/alerts/{eventId}/close
```

请求体可带 `actedAtUs`（测试/回放用；缺省取服务端 UTC 微秒）、`screenshot`、
`evidence`、`effectiveThresholds`、`detectionResults` 和 `note`。响应事件的
`disposition` 含当前状态、操作人与时间戳，以及追加的 `history`。

## 误报数据集导出

`GET /api/alerts/false-positives/export` 返回
`aiyolo-false-positive-v1` JSON。每条 entry 包含截图引用、生效阈值、原始检测
结果、来源/主体和规则版本，可直接交给标注或再训练流水线。导出前递归移除
token/secret/password/authorization 等字段，并将 Windows、Unix 和 `file:` 绝对
路径转换为 `evidence/<basename>`；不会泄漏服务端工作目录。

误报动作会将事件置为 `ENDED`，但保留原始事实字段和完整操作历史，便于审计。

## 本地启动与迁移

在服务端目录执行：

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\start-server.ps1
```

服务启动后检查 `http://127.0.0.1:8080/healthz`。当数据库已配置且迁移完成时，响应中的
`database.status` 应为 `ok`，`database.schema` 应为 `ready`。未初始化数据库不会静默
创建表，需先执行 Alembic 迁移。

## 备份与恢复

生产环境使用 PostgreSQL 原生逻辑备份，示例命令中的密码通过 PostgreSQL 凭据管理或
`PGPASSWORD` 注入，不写入脚本、日志或仓库：

```powershell
pg_dump --no-password --format=custom --file=aiyolo_dev_20260914.dump --dbname="$env:AIYOLO_PG_URL"
pg_restore --clean --if-exists --dbname="$env:AIYOLO_RESTORE_PG_URL" aiyolo_dev_20260914.dump
```

这里的 `AIYOLO_PG_URL` 使用 PostgreSQL 原生 `postgresql://...` URL；服务的
`DATABASE_URL` 可以使用 SQLAlchemy 的 `postgresql+psycopg://...` URL，不能把后者原样
传给 `pg_dump`。恢复 URL 必须指向预先创建的独立验证数据库。

恢复到新实例后，先执行 `alembic upgrade head`，再启动服务并检查 `/healthz`、告警列表、
事件详情和误报导出。恢复前应停止写入或使用数据库快照，避免备份处于半事务状态；生产
备份需加密、限制访问并定期执行恢复演练。

## 数据库不可用时

配置了 `DATABASE_URL` 但 PostgreSQL 不可连接时，服务不会自动切换到内存存储，避免形成
两套不一致的告警数据。启动时不可用会阻止服务启动；运行中断连时 `/healthz` 返回
HTTP 503、`status=degraded` 和 `database.status=unavailable`。应恢复数据库或修正连接
配置后重启服务。只有删除 `DATABASE_URL` 并明确以诊断模式启动，才会启用内存回退。
