# M33-T48 场景参数快照契约修复

日期：2026-11-02。状态：**待人工复测**；不代表人工验收通过。

## 修复

- `ProjectModelAssignments.save` 的数据库和内存分支均保留 `schemaVersion`、`source`、`updatedAt`，连同原有精确身份、参数修订、继承修订、检测和告警参数一起冻结。
- 场景批准仍只复制项目模型已经冻结的快照，不读取或猜测最新全局/项目参数；审计列表及操作者身份不进入移动端消费快照。
- 不增加旧格式读取兜底，不改变审批、CAS、授权、产物或运行准入；不迁移、不清空、不自动改写 Default Project。

## 测试与证据

- `backend-regression-final.log`：116 项，85 通过、31 项隔离 PostgreSQL 开关未启用而跳过，0 失败。覆盖项目模型、快照持久化、场景 API/参数/契约和审批后冻结。
- `ProjectModelInventoryPostgreSqlTests.log`：隔离 PostgreSQL 8/8 通过，含继承/自定义元数据、跨服务实例 CAS 与迁移边界。
- `SceneParameterPostgresTests.log`：隔离 PostgreSQL 11/11 通过，含重启、批准快照、并发审批/参数修改、审计与撤权。
- `postgres-result.json`：一次性集群位于项目 `.tmp/m33-t48-pg-*`；数据目录与端口经连接验证，随机测试 schema 全部清理、集群停止且端口关闭。未使用 `.env` 应用连接。
- `android-catalog.json`：读取现有已发布 PC/移动端模型的真实产物元数据，在独立 SQLite 中经“分配项目模型→新建混合端场景→批准→用户目录投影”生成，未手工补字段，含 2 成员、0 方案。
- `android-parser.log`：使用 Android 已编译的真实 `ProjectSceneSuite`/参数解析器读取上述目录，得到 `PARSE_OK scene=metadata members=2 plans=0`。它验证配置读取，不代表模型安装、运行或业务精度验收。
- `harness-tests.log`：Harness 34/34 通过。
- `installation-regression.log`：安装准备及其继承的场景 API 回归 30/30 通过。

初次 SQLite bootstrap 被 Settings 的 PostgreSQL-only 校验拒绝，未执行产品测试，保留 `backend-regression.log`；随后显式禁用应用全局数据库，仅在测试自建数据库运行。PostgreSQL 首轮被 Windows 沙箱限制，失败材料保留在 `postgres-sandbox-failure.*`；取得隔离集群启动权限后上述 19 项通过。

## 现有场景复测前提

本次代码修复不会改动已批准、已存储的不完整快照。加载新后端代码后，有权负责人需按当前参数修订重新保存项目模型，再明确重新审批场景新修订；不得通过关闭 App 校验、伪造 source 或读取最新参数冒充已批准快照。

本任务未重启用户服务、未安装 App、未提交或推送 Git。
