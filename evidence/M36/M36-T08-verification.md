# M36-T08 双端独立分配验收

日期：2026-10-20。任务 owner：codex-dual-target。

## 交付

- 同一项目 scenario 按 server/android 分别保存 assignmentId、参数快照、参数修订和 CAS；选择一次精确版本，双端变更同事务提交，任一失败整批回滚。遗漏目标不变，显式停用可在产物丢失时完成。
- 旧单端 API 仅操作指定平台；Android rollback 不影响 PC。已有授权不自动复制另一端。双端未指定 target 的 assignment 详情返回可解释的 409，而不是任意选端。
- 项目目录按精确版本合并端部署，独立参数和产物授权；启用 Android 优先作为旧字段投影，否则选择启用 PC。停用端无下载产物，不影响另一端。
- 场景按请求端判断 single 能力；同版本双端可分别预检，同端多成员和 sync/async 继续返回不支持。不新增真实多模型推理执行器。
- 前端沿用绿色工业管理台与 Element Plus，双端勾选、参数预览、原子确认、逐端卡片和停用确认，冲突保留草稿且禁止自动重试。

## 最终验证

1. `RUN_POSTGRES_TESTS=1`，`PYTHONPATH=tests`，`.venv/Scripts/python.exe -m unittest test_assignment_targets test_assignment_targets_migration test_project_model_assignment_storage test_project_scenes test_project_scene_authorization test_m36_api_contract test_project_model_assignments test_model_marketplace_api test_model_download test_stream_model_binding -q`：**89 tests，全部通过，无跳过**。日志 `M36-T08-final-backend.log`。
2. SQLite 与随机隔离 PostgreSQL schema 验证真实 Alembic 20261019_15→20261020_16：保留历史 ID/快照/修订，无隐式移动授权，双端记录（含停用端）阻止降级，移除额外测试记录后可降级并重新升级。没有对 public/真实项目执行迁移。
3. 双端 PostgreSQL 并发使用两个独立仓储锁和参数锁模拟不同进程，首次插入仅一个提交，另一方 CAS 冲突，最终双端各 revision=1。首次参数导入移到批量项目锁之前，消除自锁。单独日志 `M36-T08-postgresql-batch.log`：3 tests passed。
4. 前端 `npm run test -- --reporter=dot`：**18 files / 119 tests passed**，日志 `M36-T08-frontend.log`；`npm run build` 含 vue-tsc 类型检查和生产构建通过，日志 `M36-T08-build.log`。
5. 使用已安装 Chrome，`npm run test:e2e:production -- tests-e2e/assignment-targets.spec.ts tests-e2e/scenes.spec.ts tests-e2e/project-business.spec.ts --workers=1`：**7 passed**，日志 `M36-T08-browser.log`。覆盖1440px/390px双端批准、单端撤销且PC继续可下载、普通用户权限、双端场景添加去重、按端resolve、旧PC配置/参数/流绑定、场景多模型拒绝、草稿冲突保留、跨项目与撤权。真实产品鉴权/路由，隔离内存业务和合成产物，无推理执行。
6. Harness：34 tests passed，validate/render通过，日志 `M36-T08-harness.log`。
7. 已人工查看窄屏模型卡片和桌面场景截图；两端信息分离，窄屏无横向溢出。截图以 M36-T08 命名，未覆盖既有任务截图。

## 执行中的问题与保留项

- Windows沙箱的TemporaryDirectory权限导致首轮测试无法执行，获准在沙箱外运行隔离测试后通过。Playwright默认浏览器版本缺失，改用已安装Chrome完成验收，未安装依赖浏览器。
- 初轮67项回归定位旧发布fixture未带M36-T07哈希绑定验证、场景迁移测试用当前ORM冒充历史schema；修正fixture及真实版本迁移路径后最终集通过，不降低产品校验。
- 扩大至98项时发现 `test_project_business_configuration.ProjectBusinessApiTests` 的两个既有参数接口404失败。与M33-T26已登记问题一致，本任务未改动对应fixture，也未宣称全服务端测试通过。详情 `M36-T08-regression.log`；本任务相关分配/参数/场景和浏览器真实流程均在最终集通过。
- 不操作8080服务进程、不自动批准真实场景、不改Default Project真实授权、不执行真实数据库迁移。生产/本地运行实例启用须按既有部署门禁备份数据库、迁移到20261020_16并运行配套后端。当前前端构建通过不等于8080后端已升级。
- Android M104-T04、真实设备/权重推理与后续多模型调度不属于本任务交付，保留原任务状态。未提交或推送Git。

## 代码与文档

`app/project_model_assignments.py`、`app/main.py`、`app/project_scenes.py`、`app/project_business.py`、`app/database.py`；迁移 `alembic/versions/20261020_16_assignment_targets.py`；界面 `ProjectModelsView.vue`、`TargetSelection.vue`、`ScenesView.vue`；契约 `docs/project-model-assignments.md`、`docs/project-scenes.md`、`docs/admin-project-scenes.md`、`docs/model-capabilities-and-scenes-v1.md`。
