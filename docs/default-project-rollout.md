# 默认项目迁移与回滚操作流程（M33-T14）

本工具负责把空库或 `20260920_05` 旧单项目数据库迁移至当前 Alembic head。
已完成的 `20261012_11` 数据库不重新执行默认项目归属迁移；完成备份和恢复验证后，使用 Alembic 的增量 `upgrade head`。
历史 T14 验收记录中的目标版本不改写；T20 单独验证新版本兼容性。审批实例标识在同环境恢复中保留，复制为另一环境必须停用复制的注册/审批并重新分配实例标识，禁止直接启用。
默认项目 ID 固定为 `00000000-0000-0000-0000-000000000001`，从不选择第一个项目。
命令入口为 `tools/migrate_default_project.py`，不由应用启动或容器入口自动执行。

## 当前验收状态

工具及真实旧库快照的隔离升级/归档/回滚演练已通过；这只验收迁移工具，**不代表在线旧库已升级或批准数据处置**。在线切换须另走部署升级和联合验收流程。
2026-10-13 对现有本地业务库只读检查发现：176 条投递回执中，167 条缺少对应告警。
新的项目复合外键要求父告警存在；工具报告 `orphan_delivery_receipts`，普通 apply 在任何升级前拒绝。
有明确的 `--archive-orphan-receipts` 独立选项，仅在已验证完整备份后，原行逐字节归档且候选哈希再次匹配时，
才在同一迁移事务中从在线回执表移出，留下审计收据。此选项已经在真实快照的隔离副本验证，未用于在线旧库。

## 预检查与备份

所有命令在 `server-video-service/` 中执行。通过受保护环境变量提供连接串，避免命令行、日志暴露密码。
必须显式设置 `MIGRATION_DATABASE_URL`；工具不会自动选择 `.env` 中的业务数据库。
MinIO 只读配置沿用既有 Settings；本地证据根通过可重复的 `--evidence-root` 明确列出。

```powershell
.\.venv\Scripts\python.exe tools/migrate_default_project.py inspect
.\.venv\Scripts\python.exe tools/migrate_default_project.py prepare --bundle backups/rollout-001 --evidence-root evidence/server-alerts
.\.venv\Scripts\python.exe tools/migrate_default_project.py verify --bundle backups/rollout-001
```

inspect 输出版本、表行数、账号数量和阻塞代码，不输出业务内容或凭据。
prepare 不修改源库，采用一致性读事务，将全部已知业务表按主键顺序写入 JSONL，并记录行数和 SHA-256。
格式 2 清单保存列、主键、结构签名、账号映射、序列状态、证据归属与孤立回执的原始归档文件；失败目录不会覆盖或复用。
早期格式 1 备份可以用作经过校验的证据缓存，但不能直接 apply/restore。
manifest/checkpoint 采用临时文件加原子替换，只有存在可通过校验的 manifest 才是完整备份。
备份内部可能包含密码散列、会话、RTSP 配置、通知凭据及图片，必须放在受限 ACL 的私有目录。
`backups/` 已被 Git 忽略，不能把备份上传到测试证据或提交仓库。
如在线 MinIO 临时不可读，仅可用此前完整备份中与当前事件引用和源 `sha256` 精确一致的对象字节；
本地可变路径不采用缓存。工具会报告复用数量与源备份哈希，不会因此假称在线 MinIO 已恢复。

这是一套已知应用结构的可移植业务备份，不替代 PostgreSQL 原生完整备份。
自定义表、视图、触发器会拒绝；恢复时检测索引、约束和列等结构漂移。
角色/授权、扩展、函数、RLS 策略、模型文件及平台文件目录的完整备份仍按部署恢复流程操作。
生产使用前必须另存并验证原生数据库备份和平台文件备份，T17 负责完整部署恢复演练。

## 账号与业务行映射

- legacy username 通过固定 UUIDv5 规则映射为不可变 accountId，原密码、禁用状态和会话数据保留。
- admin 映射为 PLATFORM_ADMIN 与默认项目 PROJECT_OWNER；operator 映射为 NORMAL_USER 与 PROJECT_USER。
- 存在账号但无启用管理员时拒绝升级，不能自动指定普通用户为负责人。
- 12 张项目业务表回填固定 project_id，复合主键/外键由既有 Alembic 基线实现。
- 项目业务 JSON 增加一致的 projectId；如果旧载荷已经声明其他项目，拒绝猜测归属。
- 全局转换、标定等平台数据原样保留。不会根据旧设备令牌自动授予设备身份，也不会自动发布或分配模型。

## 证据归属和恢复

逐项验证告警和误报的有效图片引用。已知旧 MinIO 对象名必须与 eventId 的 SHA-256 相符，
已分区对象还必须属于固定默认项目；桶、校验和、图片类型及 8 MB 上限均检查。
本地引用只能解析到操作员指定根目录内的唯一文件，路径穿越、缺失、歧义和未明确导入的外部 URL 均失败。
旧告警证据 API 引用按同一 eventId 解析到实际对象或文件，不能任意抓取 URL。

图片字节复制到备份的内容寻址 assets 目录，归属清单分别记录 eventId 和 projectId。
迁移时将旧外部图片转换为数据库中的 inline `snapshotUri`，由现有项目鉴权接口读取。
这样原对象不会被改写，也无需依赖旧全局静态目录；之后可显式运行既有 MinIO 图片迁移工具再次外置。
这会增加 JSON/数据库容量，停机窗口和磁盘预算必须计入图片 base64 开销，不能当作生产大数据容量验收。
投递回执和历史审计内的脱敏通知摘要不是证据存储，保留其原始摘要而不把占位字符串当成文件。

恢复到旧结构时，同样从备份恢复图片字节为 inline 引用，不添加项目字段。
原始 JSONL 和图片文件仍保留，恢复对账只接受这项明确的引用形式转换，其余原列逐行一致。

## 先演练恢复，再迁移

停止所有写入方：API、后台任务、设备上传、推理告警和外部写库任务。
`--maintenance` 是操作员对停写状态的确认，不能代替真正停机。
设置 `MIGRATION_RESTORE_URL` 指向独立空数据库或独立空 schema，不能指向源库：

```powershell
.\.venv\Scripts\python.exe tools/migrate_default_project.py restore --bundle backups/rollout-001 --maintenance
.\.venv\Scripts\python.exe tools/migrate_default_project.py apply --bundle backups/rollout-001 --maintenance
.\.venv\Scripts\python.exe tools/migrate_default_project.py reconcile --bundle backups/rollout-001
```

restore 通过旧版 Alembic 重建结构，按依赖顺序每批 100 行恢复，保留 PostgreSQL 序列已用值，
核对完整结构和每行数据，然后写入与备份哈希绑定的 restore-verification。
apply 必须看到这份恢复验证记录；缺失、备份损坏、来源不匹配、源数据/结构发生变化或预检查阻塞都拒绝。
如已经批准孤立回执历史归档，需在全新备份及恢复验证后，显式追加 `--archive-orphan-receipts`。
工具逐行保存孤立回执原文，清单记录数量和 SHA-256；删除前在停写事务中再次核对完全相同的候选集合。
仅删除真正没有父告警的这些行，且删除、数据库升级及审计收据同一事务提交，失败回滚后回执仍在线。
平台审计收据保存归档数量、哈希和文件名；归档文件留在受保护的完整备份内，不发布到接口。
升级后在线回执数与归档数分别核对，回滚从完整备份恢复全部原始回执。
这些校验和保证意外损坏可检测，不是抵御能改写整个备份目录的攻击者的数字签名；目录必须可信。

PostgreSQL apply 使用事务、表锁与 10 秒锁等待限制；SQLite 使用显式写事务，提交前检查外键。
DDL、回填、逐行对账和平台 migration.default_project 审计收据属于同一事务。
异常、中断或对账失败回滚整次操作；重复执行根据数据库收据识别已完成，不以 checkpoint 文件代替事实。
提交成功但 checkpoint 尚未更新时，重试返回 already-applied，不能重复写入。
reconcile 用于停写验收期间；重新开放业务写入后数据变化会导致它失败，不应以此覆盖或回滚新业务数据。

## 灰度兼容

默认关闭。仅为无显式项目上下文的旧人类账号入口设置：

```text
LEGACY_PROJECT_ID=00000000-0000-0000-0000-000000000001
LEGACY_PROJECT_UNTIL=<明确时区的 ISO-8601 截止时间，当前距截止不得超过 7 天>
```

请求仍需有效账号、成员关系和能力；禁用账号、移除成员、项目生命周期限制继续生效。
路径/请求头明确给出的项目不会被替换。设备凭据始终要求显式项目。
只允许系统恰好存在固定默认项目；出现第二个项目（含停用/归档）立即关闭缺省映射，绝不挑选首个可访问项目。
到期、格式不正确、空白显式项目头均拒绝。重启不会延长绝对截止时间。
每次回退生成结构化 WARNING，并通过 HTTP Warning/Sunset 响应头提示迁移；日志不包含原始 URL、令牌或证据。
平台超级管理员无项目的模型目录保持平台管理语义；普通账号的旧模型目录遵循同一灰度规则。
其他未使用项目上下文解析器的旧接口不会因为这两个设置获得新授权。

## 回滚边界与真实数据阻塞处理

不对业务库执行就地覆盖、不自动删除新项目、不逆向合并升级后产生的数据。
切回旧版本需要停写、保留升级后数据库、用验证过的备份恢复到另一空库，再按部署流程切换连接。
恢复点之后的新写入需单独审核、归档或重放；本工具不声称无损自动合并。
由于升级会留下迁移审计，不能用删除审计的方式强行通过旧 Alembic downgrade 门禁。

真实旧库的 167 条孤立回执优先从可信历史备份恢复原始告警并校验证据；若不可恢复，
可按上述可回滚方案归档。隔离真实快照已经验证：原库前后全部业务表哈希及结构一致，
升级副本的在线回执 9 条，归档原文 167 条，回滚副本恢复完整 176 条，重复执行不重复迁移。
在线 MinIO 健康请求在沙箱内外均超时；隔离演练只使用此前已校验并与当前引用哈希一致的 7 个证据字节，
**不能证明在线对象当前可读取**。业务库本身未停写或执行升级，归档是否退出在线查询仍需明确批准。

## 可复现的只读快照恢复演练

```powershell
.\.venv\Scripts\python.exe tools/rehearse_default_project_snapshot.py --bundle backups/snapshot-rehearsal-001 --evidence-bundle backups/previous-verified-evidence --upgrade-copy
```

脚本只读源库、创建随机 PostgreSQL schema 恢复和升级（仅 `--upgrade-copy`），
验证孤立回执归档、重试、回滚与源库前后哈希/结构，然后只清理自身随机 schema。
私有备份保留。外部 MinIO 不可用时，仅可复用精确内容绑定的旧备份证据；
不能把隔离缓存演练等同于在线 MinIO 可用性验收。
