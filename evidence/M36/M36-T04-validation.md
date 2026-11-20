# M36-T04 验证记录

日期：2026-10-19。场景授权与目录实现位于 app/project_scenes.py，使用 project.scenes.manage / project.scenes.approve，接口见 docs/project-scenes.md。

## 交付

- 创建为草稿、编辑清除批准；独立批准/撤销携带 CAS revision 与原因，写事务内重新核对成员和账号权限，成功审计同事务提交。
- 读取按当前项目、批准/启用状态、inputType 和 target 过滤，携带 revision、精确版本、每端就绪与执行能力。用户无权通过直接详情访问草稿或不可用场景。
- 场景作用域下载只授予获准精确版本和目标端，每次请求重新校验；不扩大旧模型 assignment/流运行权限。旧 assignment 的只读兼容场景保持实时授权。
- resolve 为只读预检；单成员 single 返回 resolutionOnly=true，多成员/sync/async 返回 execution_mode_not_supported，不启动推理或丢弃成员。

## 实际测试

环境：项目 .venv，PYTHONPATH=tests，项目临时目录，RUN_POSTGRES_TESTS=1。

1. test_project_scene_authorization + test_project_scenes + test_project_authorization：39 tests passed，58.273 秒。
2. 增加持久化批准审计、事务内撤权与混合目标/单成员 sync 拒绝用例后，test_project_scene_authorization + test_project_scenes：31 tests passed，58.001 秒。其中场景存储在 SQLite 和隔离 PostgreSQL 均测试，包含实际 Alembic 升级及跨 store 并发。
3. Harness 单测、validate/render 与编译检查见完成记录。

覆盖：普通用户无法批准/修改、无批准不下载、批准后目录与下载可用、撤销即时拒绝、参数编辑重新批准、输入/目标过滤、模型撤回/哈希改变、删除成员后旧 token 失效、跨项目隔离、过期 revision、旧分配启停、不改变旧流、真实数据库审计持久化与回滚。

## 边界

未部署、未提交 Git、未测试 Android 真机或真实模型质量/性能。多模型运行排除在本阶段，resolve 仅预检；旧流仍只消费原 assignment 参数快照。目录撤权对后续请求生效，已开始传输的字节不能追溯收回。
