# M39-T01 多成员运行授权验收

日期：2026-10-22。范围：本地服务端实现及隔离自动化验收。未修改 Default Project、生产、开发库或正在运行的服务，未发布模型，未提交或推送 Git。

## 交付

- `app/project_scenes.py`：复合授权绑定账号、项目、场景修订、方案、输入、目标、客户端能力及方案顺序内每个模型成员的精确版本、全部目标产物 ID/SHA-256/大小、批准参数修订与规范化摘要。单成员保持原调用兼容；多成员要求 resolve v3 和匹配的 sync/async 能力。
- 开始逐项验证，整体签发；续期/心跳重新验证并一次性轮换令牌。失败校验消费原令牌，恢复权限不能复活。作用域错误不消费其他合法作用域的令牌。停止支持重复及旧修订/已过期授权。
- 客户端 `Idempotency-Key` 防重复开始，重复请求返回 409，不再次签发或回传令牌；服务端 `X-Request-ID` 仅用于审计关联。轮换令牌只消费一次；响应丢失需重新开始，不允许重放旧令牌。摘要、撤销历史和最小审计持久化，不持久化 bearer 原文。
- PostgreSQL 项目/账号锁协调权限与场景写入；轮换、签发和审计同事务，审计异常回滚。完整权限修订及成员关系创建身份防止禁用后恢复、删除后重建使旧令牌复活。
- `20261022_21` 迁移保留历史，去除会因替换模型成员而级联删除授权历史的外键。旧令牌缺少权限修订证明，升级时撤销、要求重新开始；存在授权记录时拒绝降级。SQLite、PostgreSQL 均验证升级重跑、历史保留与降级保护。
- [版本契约](../../../docs/project-scene-runtime-grants-v2.md)、[可执行 API/参数金样](../../../docs/project-scene-runtime-grants-v2-golden.json) 已更新。参数规范化覆盖 UTF-8、Unicode 键排序、有限十进制、负零和无损长数值金样。

## 测试结果

每组使用 `.venv/Scripts/python.exe -m unittest discover -s tests -p <pattern> -v`；普通轮次显式设置 `DATABASE_URL=''`、`RUN_POSTGRES_TESTS=0`，不继承 `.env` 业务库。发现数包含继承 fixture 带入的兼容回归，不表示独立业务场景数。

| 普通轮次 pattern | 发现 | 跳过 | 结果/日志 |
|---|---:|---:|---|
| `*scene*.py` | 165 | 31 | 通过；[日志](m39-regression-allsceneall.py.log) |
| `test_project_authorization.py` | 11 | 0 | 通过；[日志](m39-regression-test_project_authorization.py.log) |
| `test_account_auth.py` | 4 | 0 | 通过；[日志](m39-regression-test_account_auth.py.log) |
| `test_model_parameters*.py` | 13 | 0 | 通过；[日志](m39-regression-test_model_parametersall.py.log) |
| `test_assignment_targets*.py` | 16 | 4 | 通过；[日志](m39-regression-test_assignment_targetsall.py.log) |
| `test_project_model_assignment*.py` | 26 | 5 | 通过；[日志](m39-regression-test_project_model_assignmentall.py.log) |
| `test_database.py` | 6 | 0 | 通过；[日志](m39-regression-test_database.py.log) |

普通轮次共发现 241、执行通过 201、跳过 40；跳过主要为需要隔离 PostgreSQL 的既有专用测试，未声称全仓测试完成。新增多成员独立普通轮次另有 [42 项日志](m39-unit-final.log)，其中 13 项等待隔离 PostgreSQL，已由下表对应轮次执行。

隔离轮次运行 `tools/accept_m39_postgres.py`：显式初始化角色 `aiyolo_app`，端点 `127.0.0.1:53056/postgres`，精确目录 `.tmp/m39-pg-if96zfg9/pg-data`，进程 35420。连接身份及 data_directory 检查通过，全部测试后无剩余 schema，临时实例已停止，端口已关闭。机器可读结果见 [postgres-result.json](postgres-result.json)。未连接 `127.0.0.1:5432/aiyolo_dev`。

| 隔离轮次 pattern | 发现 | 跳过 | 结果/归档日志 |
|---|---:|---:|---|
| `test_scene_composite_runtime_grants.py` | 42 | 0 | 通过；[日志](postgres-test_scene_composite_runtime_grants.py.log) |
| `test_scene_execution_parameters.py` | 51 | 1 | 通过；[日志](postgres-test_scene_execution_parameters.py.log) |
| `test_project_scenes.py` | 18 | 0 | 通过；[日志](postgres-test_project_scenes.py.log) |
| `test_project_scene_suite_persistence.py` | 4 | 0 | 通过；[日志](postgres-test_project_scene_suite_persistence.py.log) |
| `test_database.py` | 6 | 0 | 通过；[日志](postgres-test_database.py.log) |

隔离轮次共发现 121、执行通过 120；唯一跳过是 SQLite 基类中只允许 PostgreSQL 行锁的测试，同名 PostgreSQL 派生测试实际通过。覆盖独立 store 竞争同令牌仅一方续期成功（测试移除共享进程锁，只由 DB 仲裁）、等待项目锁时撤权/修订先提交、部分成员拒绝、重放、跨项目/账号/方案/输入、精确快照变更、审计回滚及迁移。

Harness 单测 34 项通过，见 [日志](m39-harness-tests.log)。完成记录后重跑曾被 Windows 临时目录沙箱 ACL 阻止；正常权限重跑 34 项全部通过，见 [最终日志](m39-harness-final.log)。最终 `validate`、`render` 通过；受控文件 `git diff --check` 通过。

## Android M108-T04/T05 接入及边界

1. 多成员请求 `clientContractVersion=3`，仅声明实际实现的执行模式；安装和 resolve 返回值均不授予运行权限。
2. 使用 grant v2 完整有序 `scope.members` 核对已安装精确版本、全部产物和批准参数摘要；不能用首成员兼容投影替代完整集合。
3. 持久化最新轮换令牌后再发下一次心跳；任何拒绝或两分钟到期立即停止使用并退休旧结果。账号/项目/方案切换也应停止旧会话。开始重试使用独立幂等键，409 不代表获得授权。
4. 不在客户端推理前依赖安装授权、能力声明或过期 grant；调度、结果合并、帧/结果身份及迟到回调退休由 Android 后续任务实现和验收。

现有架构限制：撤权在续期时校验，不会向离线客户端推送；已发租约最多继续到两分钟到期。文件模型注册表仅共享进程锁，跨服务进程的模型发布/撤回与签发不构成同一数据库事务；每轮续期重读现态，但不承诺跨进程立即撤销。需要该保证时应另行实现共享事务注册表或撤权通道。幂等/停止历史清理窗口为一天，客户端不得长期复用旧开始键。

本次未部署迁移、重启本地服务或验收 Android 推理；服务更新需遵守部署最后门禁。Android 接入和联调任务仍需继续执行。
