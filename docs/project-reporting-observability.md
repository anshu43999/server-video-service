# 项目报表、审计与运维可观测性

任务：M33-T13；日期：2026-10-12。当前文档补充 T07/T11/T12；账号、项目成员和生命周期授权仍使用 m33-v1 内核。

## 数据口径与权限

| 功能 | 路径（`/aiyoloapi` 下） | 权限 | 返回范围 |
| --- | --- | --- | --- |
| 看板统计与趋势 | `/projects/{id}/dashboard/stats?range=today|7d|30d` | project.read | 一个项目的事件、处置、类别、复核和会话汇总；system 为空 |
| 项目运行汇总 | `/projects/{id}/metrics` | project.read | 一个项目的会话数及接收/处理/丢弃帧；无机器资源或跨项目明细 |
| 平台运行汇总 | `/metrics` | platform.observability.read | `scope=platform`、机器资源与所有运行会话的聚合数字；不返回项目或流 ID |
| 视频墙/流明细 | `/projects/{id}/streams` 及媒体接口 | project.streams.view | 当前项目的获准流；停用/归档不挂载实时视频墙 |
| 完整告警导出 | `/projects/{id}/alerts/export` | project.exports.create | 当前项目全部告警的安全字段投影 |
| 误报导出 | `/projects/{id}/alerts/false-positives/export` | project.exports.create | 当前项目全部误报反馈；兼容 `/alerts/export/false-positives` 项目路径别名 |
| 项目审计 | `/projects/{id}/audit` | project.audit.read | 当前项目的审计元数据 |
| 平台审计 | `/platform/audit` | platform.audit.read | 平台账号/治理审计；不混入项目明细 |

平台超级管理员拥有新的 platform.observability.read，项目负责人和用户均不具有该能力。平台诊断中的原跨项目流明细列表已被汇总替代；需要明细时显式进入对应项目，由服务器记录进入审计。旧依赖 `/metrics.streams[project/stream]` 的自定义消费者应改用项目接口，不再提供全局明细兼容回退。

看板时间范围按服务器本地日界线转换为 UTC 查询，返回 from/to/generatedAt；趋势仍保留已有桶数和严重度映射。统计与复核使用数据库逐批游标和 JSON 字段投影，避免读取内联证据或将全部事件堆在 Python 内存中。看板最新事件请求带 `limit=20`，按当前项目取最近记录；统计总数仍覆盖选定时间范围，不因最新事件条数而截断。告警中心原列表接口省略 limit 的兼容行为保留，完整列表的交互分页不是此处的审计服务端分页。

## 导出约定

前端“导出告警”“导出误报”均导出当前项目全部记录，不受列表筛选影响，页面提交前即提示范围。普通用户没有导出按钮，伪造 HTTP 请求也返回 403；不可见项目返回 404，停用/归档由有效 capability 拒绝导出。

JSON 包含 format、projectId、generatedAt、count、scope=entire-project、evidenceIncluded=false。告警在 events 中，误报保留 entries/trainingEntries 两个兼容数组。只导出明确允许的业务字段；不包含证据内容、凭据、原始 URL、自由备注和任意原始载荷。误报保留安全相对 image/screenshot 引用用于关联，不能包含协议、查询串、绝对路径或父级跳转；真实图片仍需通过项目鉴权证据接口读取。

生产数据库使用单条 SELECT 的游标快照，每批最多 500 行；先完成整个文件，再返回 200。临时文件超过 1 MiB 后落盘，并在成功、异常、取消、传输失败时关闭清理；不持久化报表资产。不生成一半成功、一半截断的“有效”文件。每个 worker 最多两项同时生成/传输，忙时 429；上限为 100000 行或 128 MiB，超过返回 413，不静默少导出。超过在线上限需运维执行有项目条件的离线归档，不属于浏览器报表容量承诺。

每 500 行生成和每 256 KiB 传输前重新认证账号、项目成员、生命周期及导出能力；生成期间撤权返回失败，已开始传输后撤权中断剩余传输，已发送字节不能撤回。Content-Length 使客户端能识别不完整文件。每次成功生成记录 export.alerts/export.false_positives 审计及行数；该记录证明服务端生成完成，不证明客户端已保存到磁盘，下载完成状态需结合请求日志的 completed。

响应提供 Cache-Control: no-store、X-Project-Id、X-Export-Row-Count 和 X-Request-Id。前端使用项目 generation 门禁和 120 秒超时；切换项目后旧下载不会触发新项目文件保存。浏览器仍需容纳最大 128 MiB Blob；多 worker 总并发还应由入口层限制。

## 审计检索与分页

两个审计接口共享以下可选条件：action、actorAccountId、requestId、outcome（SUCCESS/DENIED/FAILED）、targetType、since、until。文本条件为精确匹配；时间必须带时区，采用包含边界，反向范围返回 422。前端本地时间转 UTC，查询/清除条件后从第一页开始。

limit 默认 25、最大 100，按 occurredAt 与 auditId 倒序 keyset 分页。游标绑定项目作用域与全部筛选条件指纹，不能跨项目或变更条件后继续翻页；它不是授权凭据，每页重新鉴权。cursor 格式已更新，旧游标返回 422，应刷新首屏。查询仅选取元数据列，不读取 change_summary 中可能存在的业务快照。平台和项目结果分别查询，不能通过 cursor 访问另一作用域。

迁移 `20261012_11` 增加项目事件时间索引和审计时间/ID 复合索引。SQLite 另有 julianday 表达式索引，避免旧秒精度时间格式导致游标重复；PostgreSQL 使用原生时间索引。Alembic 自动比较会跳过不适用于当前数据库的条件索引。迁移仅增删索引，不删除审计或业务数据；大表建索引仍需在 T17 评估锁等待与维护窗口，未承诺生产零停机。

## 审计留存

提供运维 CLI `tools/retain_project_audits.py`，只作用于持久数据库的 project_audit_events 和 platform_audit_events。默认保留 365 天，最低 90 天；默认只统计，必须明确传入 --apply 才删除。本次只在测试数据库/随机 schema 执行过删除，未在业务库运行。

```powershell
# 只预览；使用部署环境的数据库配置，不在命令行明文填写凭据
.\.venv\Scripts\python.exe tools/retain_project_audits.py --days 365

# 备份并核准保留清单后，由运维明确执行
.\.venv\Scripts\python.exe tools/retain_project_audits.py --days 365 --batch-size 500 --hold-project PROJECT_ID --apply
```

--hold-project 可重复，保留名单中的项目记录不删除；未知项目直接拒绝，避免拼写错误造成误删。仅删除严格早于 cutoff 的记录，等于边界的记录保留。每批 1–5000 行（默认 500），锁定后删除与新增 audit.retention 元记录在同一事务提交；异常回滚当前批，之前批已提交，可安全重跑。并行操作可能跳过其他进程锁住的行，后续重跑处理。若数据库有维护触发器拒绝删除，则保留失败并交由运维处理，不绕过触发器。

CLI 不自动调度、不提供 Web 删除入口，也不清理告警处置、模型参数、规则等业务专用历史表或证据资产。保留名单应来自组织的正式保留策略，生产执行前确认备份可恢复；误删只能从备份恢复，工具不承诺撤销。完整备份/恢复与调度部署演练仍由 T17 完成。

## 安全日志与排障

RequestTelemetry 输出 JSON 行：event、requestId、accountId、projectId、servicePrincipalId、transport、固定路由模板、status、completed、durationMs。ID 取已认证/已解析上下文，不信任客户端操作者字段；不可见项目不会记录客户端原始项目字符串。请求 ID 由服务器生成，覆盖传入 X-Request-Id，并在响应头返回，同一值进入业务审计。调用方需要用响应 ID 查日志和审计，不能继续假设任意自带 ID 会被服务端采用。

不记录请求 URL、查询串、headers、Cookie、Token、请求/响应 body、RTSP 来源、证据内容或异常对象。Uvicorn 原始 access 日志被过滤，WebSocket 接入日志中的原始 URL 替换为固定说明；完整关联信息见结构化请求日志。Alembic 不再禁用已存在的日志器，迁移后请求日志仍可用。身份尚未确认的登录/匿名请求可以没有 accountId，仍有 requestId；连接异常可表现为 completed=false。

排障顺序：取 X-Request-Id → 查同 ID 请求日志 → 在项目审计使用 requestId 查询 → 根据平台/项目权限进入相应诊断。不要把 Authorization、Cookie、RTSP 完整 URL 或证据贴进工单。保持既有 Docker 日志轮转；代理日志应使用去查询串的 URI，不启用第三方 WebSocket/HTTP 库的凭据级 wire/debug 日志。应用日志过滤不代替外部代理的日志配置。

## 验证和边界

复现命令、测量结果、截图与条件跳过项见 `evidence/M33/M33-T13-validation.md`。SQLite 和 PostgreSQL 测试均以双项目、各 10000 条告警及审计验证统计、分页、导出和留存；不是生产最大容量或多人并发 SLA。PostgreSQL 使用随机独立 schema，测试结束删除仅测试数据，不迁移 public。

T14 仍负责实际默认项目回填与回滚工具，T15 完整隔离矩阵，T16 整体多角色产品验收，T17 生产快照升级与恢复演练，T18 Android 联验。本轮不提交/推送 Git，不部署，不修改 Android 工程。
