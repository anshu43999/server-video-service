# M33-T13 验收记录

日期：2026-10-12；工程根：`E:/aiyolo/server-video-service`；本次仅绑定 M33-T13。

## 完成标准对应

| 完成标准 | 实现与证据 |
| --- | --- |
| 看板、趋势、视频墙明确项目范围 | 继续使用显式项目路径与生命周期能力；统计按项目过滤，JSON 列投影与游标逐批汇总；看板最新事件限制 20 条；全量 dashboard/projects/streams 浏览器回归通过 |
| 完整告警与误报导出 | 安全字段投影、项目上下文、真实数量、流式传输、临时文件清理、并发/容量限制、生成与传输重复授权；真实浏览器解析两个文件并核对内容 |
| 平台汇总和项目视图区分 | 新增 platform.observability.read；全局 metrics 仅输出机器资源和聚合数量，移除跨项目流明细；普通项目账号 403 |
| 审计查询、分页 | 元数据投影、7 个条件、时间校验、绑定作用域及过滤条件的游标、100 行上限、复合索引；双项目全量翻页不重复、不串项目 |
| 安全关联日志 | 服务端生成 requestId，返回响应头并串联审计；真实账号/项目/设备身份，固定路由模板；不记录请求数据，屏蔽 Uvicorn HTTP/WS 原始 URL |
| 留存及大数据量验证 | CLI 默认 dry-run、365 天默认/90 天最小、保留名单、分批事务与清理元审计、边界与重复执行；SQLite/PostgreSQL 双项目大样本通过 |

完整契约与运维用法见 `docs/project-reporting-observability.md`。前端按 frontend-design 技能沿用既有绿色工业风格、组件和响应式布局，补充审计检索表单、报表入口和平台汇总。

## 真实测试

| 项目 | 命令/范围 | 结果与日志 |
| --- | --- | --- |
| 前端单元 | admin-web 下 `npm run test -- --run` | 91 项 / 15 文件通过；`T13-unit.log` |
| 正式/预览构建 | `npm run build`、`npm run build:preview` | 两次 vue-tsc 和构建通过；`T13-build.log`、`T13-preview.log` |
| 浏览器全量 | `npm run test:e2e:production -- --workers=2` | 最终 66 项全部通过，1.9 分钟；`T13-browser-final.log` |
| 后端全量 | 空 DATABASE_URL，`.venv/Scripts/python.exe -m unittest discover -s tests -q` | 561 项，532 通过、29 条件跳过；`T13-backend-final.log` |
| 最后字段投影/下载释放专项 | `… discover -s tests -p test_project_reporting.py -v` | 11 项通过；`T13-reporting-final.log` |
| 最后看板专项 | `… discover -s tests -p test_dashboard_stats.py -v` | 3 项通过；`T13-dashboard-final.log` |
| PostgreSQL 报表/迁移/留存/性能 | `RUN_POSTGRES_TESTS=1`，`… discover -s tests -p test_project_reporting_postgresql.py -v` | 1 项复合场景实际通过；`T13-postgresql-final.log` |
| PostgreSQL/SQLite 模型分配存储回归 | `RUN_POSTGRES_TESTS=1`，`… discover -s tests -p test_project_model_assignment_storage.py -v` | 8 项通过，未跳过；`T13-model-storage.log` |
| PostgreSQL/SQLite 设备存储回归 | `RUN_POSTGRES_TESTS=1`，`… discover -s tests -p test_service_principal_storage.py -v` | 15 项通过，未跳过；`T13-service-storage.log` |
| Harness | `python -m unittest discover -s harness/tests -p test_*.py` | 完成前及完成后均 30 项通过；`T13-harness.log`、`T13-harness-final.log`，validate 通过 |

全量后端运行时为 561 项；之后对报表/看板 SQL 增加字段投影，并补充两项下载撤权/误报持久库投影测试，最终受影响范围 11+3 项及真实 PostgreSQL 专项重新通过。没有把这些重叠执行相加，也不声称重新跑过 563 项全量。全量 29 个条件跳过不当作通过；上表单独标明实际补跑的 PostgreSQL 场景。

早期失败已经修复：新增平台汇总面板导致旧浏览器选择器匹配两个区域；迁移的默认 fileConfig 禁用了请求日志；测试 WebSocket 替身不具备 state；PostgreSQL 自动比较需识别 SQLite 专属条件索引。测试种子显式提供旧迁移要求的项目创建时间。保留早期日志只用于追溯，最终以上表为准。未修改测试来绕过服务端鉴权或权限约束。

标准 git diff --check 对 Harness 自动生成 Markdown 双空格换行有提示；`git -c core.whitespace=-blank-at-eol diff --check` 通过，未直接编辑任务板。

完成记录生成后的 Harness 首次复验中，4 项测试因 Windows 临时目录 WinError 5 权限问题失败；按权限流程在沙箱外重新执行相同命令，30 项全部通过（0.060 秒），没有修改测试或产品代码来绕过失败。最终结果见 `T13-harness-final.log`。

## 数据量与性能

样本为两个项目，各 10000 条告警和 10000 条审计，共 20000 告警及 20000 审计。每条告警持有 4 KiB 合成证据字段，用于证明投影不会将图片复制进结果；SQLite 审计另带 1 KiB 原始变更载荷，查询不得返回该载荷。测量是本机单次基线，不是生产并发 SLA。

| 最终测量 | SQLite | PostgreSQL 随机 schema |
| --- | --- | --- |
| 一个项目看板 | 1697.6 ms | 936.8 ms |
| 一个项目 10000 条完整告警导出 | 2279.2 ms | 1328.0 ms |
| 顺序读取 100 页审计，每页 100 条 | 273.2 ms | 10155.7 ms |
| Python 分配峰值（统计与导出） | 2583549 bytes，约 2.46 MiB | 未测量，不作内存结论 |
| 输出文件 | 1140180 bytes | 实际完整 JSON 数量 10000 |

SQLite 开启 tracemalloc，PostgreSQL 未开启，因此两列不能直接用于数据库优劣比较。SQLite EXPLAIN 命中 `ix_project_audit_page_sqlite` covering index；两种数据库全部翻页检查 10000 个唯一 ID、终页 cursor=null，无另一项目 ID。所有操作符合测试的有界时间预算。最终 PostgreSQL migration upgrade/downgrade/re-upgrade 与 Alembic metadata check 通过，未产生缺失索引差异。

PostgreSQL 通过现有隔离测试工具创建随机 schema 并仅清理该 schema；没有升级或删除 public 业务表。留存 apply 仅对合成审计行执行；保留名单项目、等于 cutoff 的边界行和新的清理元审计均保留，第二次执行无旧记录可删。生产业务库没有执行留存删除。

## 浏览器与安全证据

`tests-e2e/reporting.spec.ts` 使用真实 Cookie、正式业务 handler 与隔离项目，不模拟成功响应；分别在 1440px/390px 验证：完整告警下载、误报处置与反馈下载、生成审计、按返回 requestId/账号/动作精确检索、空结果、清除条件、普通用户无按钮且 API 403。两个导出文件实际读取并解析，误报兼容数组一致，projectId/数量正确且无证据内容。

前端截图已实际查看，无水平溢出，输入和审计 ID 在窄屏可读：

- `M33-T13-audit-1440.png`
- `M33-T13-audit-390.png`

API/存储测试另覆盖：同名事件跨项目隔离，生成文件上限 413 后恢复正常，恶意查询串和操作者 header 不进入日志，日志/审计使用同一个服务端 ID，WebSocket 原始 URL 不进入日志，下载传输期间撤权中断并释放并发名额，误报 DB 投影保留安全相对图片引用，游标跨条件/跨项目拒绝，留存 dry-run/保留名单/边界/批次/重复执行。

既有浏览器故障、实时媒体和平台页面回归含 fixture；本轮真实报表流程不等同于真实模型推理、外部通知、现场媒体或 Android 联验。视频墙仍由既有浏览器资源/订阅测试覆盖，没有在本轮宣称完成现场网络视频压测。

## 已知边界和后续任务

- 在线导出每 worker 最多 2 个、最多 100000 行或 128 MiB；超限明确失败。浏览器仍需容纳 Blob，已传输数据不能因撤权被追回。
- 留存工具默认只预览，不自动定时执行。--apply 删除不能自行撤销，生产前需审定保留名单及备份恢复；业务专用历史表/证据不由本工具清理。
- 新索引已在 SQLite/PostgreSQL 隔离环境验证；生产建索引锁等待、数据回填、容量和恢复窗口仍需 T14/T17 演练。未部署，未迁移生产库。
- 全局 metrics 的明细消费者需迁移到显式项目接口；旧审计 cursor 需刷新，外部自带 requestId 不再被服务端信任。前端权限核验沿用正常 15 秒周期加网络时间，后端逐请求实时授权。
- 当前完成 T13；T14 迁移工具、T15 完整授权隔离矩阵、T16 全角色产品验收、T17 部署/恢复/回滚、T18 Android 联验仍待执行，没有简化或合并这些任务。
- 未提交或推送 Git，未修改 mobile-app，保留用户已有工作区改动。
