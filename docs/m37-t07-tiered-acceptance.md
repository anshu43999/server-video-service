# M37-T07 服务端分级上传验收（2026-10-20）

范围按工作区 `harness/decisions/20261020-m37-m105-acceptance-scope.md`：不验收智能复核、供应商或复核重试，不删除/停用其实现。上传恢复、鉴权、真实远程 PostgreSQL/MinIO 与清理仍验收。

## 实际链路与证据

`tools/accept_tiered_alert_upload.py` 启动真正的独立 uvicorn 进程，走 TCP HTTP、真实登录/项目成员权限、完整 Alembic 迁移的随机隔离 PostgreSQL schema 和项目已配置的远程 MinIO。只重定向模型注册表的文件位置；不替换路由、授权、数据库或对象存储。每次运行新建唯一对象前缀，退出仅删除自己创建的具体对象和隔离 schema；不重置业务表，不搭 Docker MinIO。

最终服务端专项证据：`evidence/M37/M37-T07-run5/result.json`、`worker.log`、两张 JPEG。35 个 HTTP 检查全部通过：L1 OPEN/重放、4 个不可变身份冲突、乱序 L2 无孤立动作、误报/处置幂等冲突、L1 不覆盖已处置结果或已上传证据、L3/L4 独立上传/重放/读取/冲突、伪签名、超限、摘要不符、无事件上传、v1 inline 拒绝、跨项目/撤权/恢复、首次处置提交后 TCP 丢响应并重放、看板 OPEN 分母及来源分组、到期删除与显式保留。

DB 对账：金样主事件与延迟事件共 2 条、动作共 2 条；来源统计加入一个 OPEN 图片事实后共 3 条、2 已处置，分母不遗漏 OPEN。MinIO 主事件恰好 2 个对象，逐个核对 DB 引用、实际对象字节数、SHA-256、读取内容。到期缩略图先 dry-run/标记，24h grace 后删除；原图显式保留，重复清理无重复删除。测试最终移除剩余 1 个自身原图，前缀对象余数 0。

## 修复及回归

- 伪造图片签名原先返回 422，按冻结向量修正为 415 `unsupported_media_type`，摘要不符仍 422 `digest_mismatch`。
- v1 L1 原先仍走 legacy inline 路径；现在拒绝图片 data URL、本地路径、caller object key 及混入处置。没有契约 header 的旧客户端兼容行为保留。
- v1 事实使用数据库事务/项目及事件行锁，校验不可变身份，避免并发首插重复 creator、身份覆盖、L1 覆盖已上传证据/处置。新增远程 PostgreSQL 并发断言。
- 验收 worker 使用 stdin 正常结束 uvicorn lifespan，释放转换目录锁；不是改弱产品文件锁。

服务端 52 项通过（含真实 PostgreSQL、MinIO）；后台 18 files / 119 tests 通过、vue-tsc 与 Vite 构建通过。原始输出分别在 `evidence/M37/M37-T07-regression.txt`、`M37-T07-admin-tests.txt`、`M37-T07-admin-build.txt`。后续 Android 对同一工具的 `--android` 扩展单独记录，不以此服务端结果替代 API27/Room 证据。

## 冻结文件与可执行映射

未修改契约 SHA-256 `47daddcfc8ac33b642a09163cd309986a3f13f7e0b6afd72070b1837565e8d8e`，金样 SHA-256 `0b89c23c9b163fb076039c7db7cdb28c971d796873f35061f476d796eaf4b1bd`。两端使用固定 project/event/operationIds。

原金样图片 hash `aaaa…`/`bbbb…` 是示意占位值，不是可解码 JPEG 的真实摘要。工具明确写 `materializedFixtures` 映射并输出确定性真实 JPEG，双端必须复用这些实际字节/摘要；不得宣称图片字节数等于占位金样值。主事件 thumbnail：21018 bytes / `6a7e7b936c2c757d57c632eb1c2bf17b122ab7a57c758e6f9d9c495d8df53da8`；original：321165 bytes / `18aa470b94b605c70eb7e6e495a2080849f72e110bb077d1368abeffc9ded331`。后者是 L4 测试对象，不声称是符合 300 KiB 压缩目标的端侧主图。

权限差异明确保留：旧 error vector 把 unauthorized-project 写成 403/project_access_denied；现有 M33 项目隐匿规则对非成员/撤权项目返回 404/project_not_found，专项测试精确断言该 404，不改成泄露项目存在性的 403。能力不足的可见项目仍走既有 403。**这不是所有原始 error vector 逐字通过的声明**；需要后续修订金样时一起修正描述，冻结原件没有被悄悄覆盖。

## 成本口径与边界

固定 8h/1000事件，主图300KiB、缩略图48KiB、L4最大5MiB、触发10%、全包重传2%、250班/年、每天1班用于稳态容量、服务端90天、本地完成7天、待同步30天人工处理。`result.cost` 给逐项字节计算，`tests/test_tiered_acceptance_tool.py` 验证年化/节省率公式。

- 压缩主图复用为 L4 的情境：单班图片有效载荷 313344000 → 81469440 bytes，年化 78336000000 → 20367360000 bytes，估算下降74%。90天远端对象容量 27648000000 → 7188480000 bytes。
- 旧策略全传5MiB最大原图的上界情境：单班 5347737600 → 584908800 bytes，年化1336934400000 → 146227200000 bytes，估算下降89.0625%。不与上一情境混算。
- 本地完成媒体7天估算2494464000 bytes；全部待同步累积30天时10690560000 bytes，**不是强制删除上限**：30天需用户确认，继续不确认可继续增长。旧本地策略未生效，不能虚构有限的改造前稳态容量或节省百分比。
- 这些是固定假设的图片 payload 估算，不是完整 HTTP 流量测量，不含 TLS/header/JSON/multipart 开销。实测35请求（含重放和负向5MiB超限向量）请求 body 6623636、响应 body 695282 bytes，p50 10.178ms/p95 318.234ms。逐请求字节/摘要/时延在 trace。小样本 loopback 加远端 DB/MinIO 的延迟，不是生产容量或旧服务端性能对照，不从这些数推导 p95 改善率。

## 保留失败证据

run1 为 Windows Temp 沙箱权限拒绝，尚未处理任何 HTTP；获准后 run2 揭示伪签名状态码缺陷。run3 修复后通过23项。run4 新增看板向量时工具误写路径 `/dashboard`（实际 `/dashboard/stats`）导致404，修正工具而非产品后 run5通过35项。所有失败目录保留；没有据此直接把任务标为失败或删除断言。

## Android联合结果补记

最终 `evidence/M37/M37-M105-joint-final/result.json` 通过35个服务端HTTP步骤和5个API27独立进程阶段，含真实断网、Room恢复、撤权暂停、重新授权和原图v2续传。`androidReconciliation`逐项验证Room/DB/MinIO的3个对象摘要/长度一致，无多余对象；动作仍2条。到期缩略图删除1个，退出移除剩余自身原图2个，余数0。单轮17.45s；p50 13.009ms/p95 323.194ms。新迁移head为当时的20261020_17。

服务端最终补充503分支回归后53项通过，日志 `evidence/M37/M37-M105-final-regression.txt`。503为显式单测故障注入，不称为远程MinIO真实宕机；正常上传/读取/清理真实连接远端。Android 877项JVM、36项媒体设备回归、Debug/Lint及Harness通过；详细记录 `E:\aiyolo\mobile-app\docs\m105-t08-tiered-acceptance.md`，完成记录 `E:\aiyolo\mobile-app\harness\records\M105\M105-T08.md`。两侧复用本报告的金样映射及同一result.cost，不额外变更成本假设。

本次两次失败产生的确切临时目录已清除（仅空隔离注册表/测试锁，可重建）；所有失败证据目录仍保留。没有清理业务表或业务对象，也没有生产部署。
