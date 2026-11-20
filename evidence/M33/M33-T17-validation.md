# M33-T17 部署升级与恢复演练进展

日期：2026-10-13。范围：仅 server-video-service；未修改 Android、线上数据库或 MinIO。
状态：**隔离 PostgreSQL 演练与本地回归通过，但完整部署恢复验收未通过，T17 不记完成**。

## 本轮交付

- 生产 Compose/Kubernetes 默认 RUN_DATABASE_MIGRATIONS=false；容器入口与部署脚本拒绝生产自动迁移，避免绕过备份/恢复/停写。
- deploy/deploy.sh backup-db 采用 umask 077，通过 PGDATABASE 而非 argv 传递连接 URI。
- 发布操作手册：docs/m33-t17-release-runbook.md。覆盖 Docker/Kubernetes 切换、备份/恢复、默认项目回填、旧版回退条件、写入后不可自动无损回退的边界、停机评估、密钥/设备凭据轮换、TLS、审计留存、监控告警与排障。关联部署/安全文档已更新。
- 离线工具 tools/rehearse_multi_project_release.py：UTF8 临时 PostgreSQL 17.11 仅绑定 127.0.0.1，私有临时目录（Windows ACL 限 OWNER RIGHTS/SYSTEM/Administrators），不使用线上 URL；源备份复制后操作。结束核对原备份全部文件哈希并停止/清理本轮目录。
- 实际发现并修复 _06 迁移中 projects/project_memberships 时间列缺少 server default：旧版升级表新增成员返回 409，底层 NotNullViolation 指向 project_memberships.created_at。ORM 空库建表未发现。现迁移补齐默认值，API 显式写时间兼容早期预发布已迁移库，增加 SQLite/PostgreSQL 及 API SQL 列断言。未改线上 schema；已 stamp 的数据库不会自动补默认值，见数据库迁移文档。

## 可复现演练与真实结果

在 E:\aiyolo\server-video-service 执行：

    .\.venv\Scripts\python.exe tools/rehearse_multi_project_release.py --bundle backups\M33-T14-offline-rehearsal-v2 --postgres-bin D:\PostgreSQL\bin --run-regressions

最终退出码 0。输入为 T14 格式 2 私有旧库快照，非名字带 final 的格式 1 清单。
快照 18 张旧版表逐行哈希、结构及序列恢复由迁移工具核对；关键数为 1 个账号、9 条告警、176 条回执、1 条流，其中 167 条孤立回执仅在临时副本归档。
原生 pg_dump/pg_restore 独立数据库对账一致；升级 20260920_05 → 20261012_11，重复执行安全。

最终程序输出字段（真实运行，不是预测）：

| 字段 | 结果 |
| --- | --- |
| nativeBackupRestored / rollbackLegacyMatched | true / true |
| postgresRegressionTests | 19 |
| sourceBundleUnchanged / temporaryClusterRemoved | true / true |
| lossyDowngradeRefused / repeatedUpgradeSafe | true / true |
| restoreSeconds / upgradeSeconds | 1.92 / 3.31 |
| projectCreated / sessionSurvivedRestart | true / true |
| freshAuthorizationWorker / postgresRestarted | true / true |
| auditRetentionVerified / memberRevoked | true / true |
| deviceRotated / archiveBlocksIngest | true / true |

真正停止并重启临时 PostgreSQL 后，全新 Python 进程使用生产鉴权/项目/凭据路由验证持久 Session 和轮换凭据，不只是清连接池。
成员移除后原 Session 访问项目为 404，设备旧密钥为 401，归档阻止新凭据上报为 403，跨项目为 404。
审计预览不删除、法律保留排除目标、显式执行仅删除新造的 400 天演练审计，未操作线上审计。
项目/设备产生后有损 downgrade 被拒绝，事务保持目标版本。最后才向另一空库恢复旧版备份，176 条回执及所有旧状态对账一致。

19 项专项模块：test_multi_project_migration_postgresql、test_default_project_rollout_postgresql、test_service_principal_storage、test_project_reporting_postgresql。
包含 SQLite 凭据基类，不将 19 项全部称为 PostgreSQL 用例；数据库用例启用 RUN_POSTGRES_TESTS / RUN_POSTGRES_MIGRATION_TESTS，仅用临时实例独立随机 schema。

| 其他范围 | 命令摘要 | 结果 |
| --- | --- | --- |
| 后端全量 | 测试进程 DATABASE_URL=' '、MINIO_ENDPOINT=' '；.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py' -q | 594 项：563 通过、31 条件跳过；312.218 秒，退出码 0 |
| API 兼容及生命周期 | -m unittest discover -s tests -p test_project_management_api.py -q | 8 通过，16.586 秒，含全量启动后新增时间列断言 |
| Docker 部署配置 | -m unittest discover -s tests -p test_docker_deployment.py -q | 16 通过，最终 backup-db 改动后重跑 |
| Kubernetes 配置/YAML | -m unittest discover -s tests -p test_kubernetes_deployment.py -v | 7 通过 |
| 演练进程/格式保护 | -m unittest discover -s tests -p test_multi_project_release_rehearsal.py -v | 3 通过 |
| Shell 语法 | C:/Program Files/Git/bin/bash.exe -n deploy/deploy.sh | 退出码 0 |
| Harness | python -m unittest discover -s harness/tests -p 'test_*.py' | 30 通过 |

31 个条件跳过不计通过，数据库专项另启用运行。未修改前端代码，未重跑浏览器验收；不声称本轮再次通过 T16。
出现既有 Starlette/httpx、SQLite datetime 适配器弃用警告。

## 失败排查与数据安全

早期访问被备份 ACL 拒绝后，获授权只读访问。错误格式 1 清单被拒绝，未升级。
Windows pg_ctl 后台进程继承 PIPE 导致等待超时，现改为 DEVNULL，并在启动失败时也检查临时实例状态；仅停止精确定位的本轮回环实例。
成员新增失败在临时库定位到时间默认值后修复，最终通过。

早期脚本直接调用 restore，更新了源备份旁的 restore-verification.json 校验元数据，没有改写 manifest、业务 JSONL 或证据。
最终工具改为在私有副本调用 restore，最终全文件哈希前后相同。不能将最终 sourceBundleUnchanged 解释为早期运行从未更新校验元数据。
备份内容未输出、未提交。最终 m33-t17-* 实例/目录全部清理，原有 PostgreSQL 进程保持不动。旧预备未启动集群另行核对后清理。

## 尚缺的完整发布验收与解除条件

1. 本机无 Docker/kubectl。配置/YAML 测试不是实际镜像启动/重启、PVC/卷恢复、旧完整镜像切回、TLS/媒体及监控通知链路验收；需要可操作的隔离部署环境、旧新不可变镜像与实际存储副本。
2. 原生备份来自临时恢复后的应用数据，不是生产云数据库全局角色/授权/扩展/PITR 恢复。模型、校准、转换卷、对象存储一致恢复以及部署切流、监控告警仍需证明；没有缩减 T17 范围来记完成。
3. 线上旧库 167 条孤立回执的原告警恢复或原文归档/退出在线查询仍待用户决定；本轮未授权线上处置。
4. 在线 MinIO 尚无新可读性通过证据；离线备份图片不代表线上桶和对象可用，需目标环境逐项读取/核对。
5. 真实停写窗口、完整容量/恢复耗时、告警路由与跨端切换尚未执行；1.92/3.31 秒仅是本机小快照耗时，不能当作生产停机预算。Android 联验 M33-T18 未开始。

本轮不生成 M33-T17 完成记录，通过 Harness block 记录外部条件，保留 16/18 已完成计数。未提交或推送 Git。
