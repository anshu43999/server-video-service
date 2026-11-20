# M36-T06 跨项目自动化验收记录

日期：2026-10-19。范围为模型目标端能力、独立转换/发布、项目场景配置、授权目录、数据库迁移与管理后台。本记录不扩大到真实多模型调度。

## 新增验收资产

- `tests/fixtures/m36_api_contract.json`：冻结模型按端发布与场景 CRUD、批准、下载、预检的路径、方法、成功状态、请求模型字段及枚举。
- `tests/test_m36_api_contract.py`：从实际 FastAPI OpenAPI 提取稳定子集，与金样比较，并要求请求模型禁止未知字段。
- `tests/test_model_catalog.py`：补充旧 Manifest 未声明 supportedTargets 时只从真实有效产物派生 PC/移动端；移动产物缺失后仅保留 PC，PC 产物也缺失后不再声称支持任何端。

## 聚焦后端与数据库

命令启用 `RUN_POSTGRES_TESTS=1`，使用项目 `.venv`、隔离随机 PostgreSQL schema 和项目临时目录：

`test_conversion_api test_model_catalog test_project_scenes test_project_scene_authorization test_project_authorization test_database test_m36_api_contract test_api_prefix`

结果：76 tests passed，36.350 秒。覆盖：

- PC-only 跳过强制移动转换，mobile-only 不获得 PC 能力，双端可独立发布；转换失败、签名缺失、产物缺失/篡改、版本冻结和重试恢复。
- 旧 Manifest 兼容及有效产物派生；PC 激活、下载和哈希门禁。
- 多场景、精确版本、有序单/多模型成员、图片/视频适用性、single/sync/async 声明、CAS revision、项目隔离、角色能力、撤权、审计与旧 assignment 只读投影。
- PostgreSQL 实际 Alembic 升级到 `20261019_14`、表/约束、持久化重开、审批审计事务、失败回滚、独立 store 并发和非空 downgrade 拒绝。
- API 契约金样与 `/aiyoloapi` 前缀。

编译检查通过；Alembic 单一 head 为 `20261019_14`。

## 前端与浏览器

- `npm run typecheck`：通过。
- `npm run test`：17 files / 113 tests passed。
- `npm run build`：3601 modules，production build 通过。
- 场景真实生产构建浏览器：2 passed（1440px / 390px），覆盖创建、排序、批准、用户可见、撤销、成员移除、409 草稿保留、刷新恢复和键盘交互。
- 模型目标端生产构建浏览器：1 passed，覆盖 PC 独立发布和双端重复 supportedTargets 上传。
- 目视截图：`M36-T05-scenes-1440.png`、`M36-T05-scenes-390.png` 无横向溢出或关键控件遮挡。

## Harness

Harness 单元测试 34 passed；validate/render 通过。M36-T06 完成后再次执行相同门禁。

## 明确未验收

未执行真实多模型同步/异步推理、调度性能、GPU/CPU 容量、Android 真机/模拟器模型下载与推理、生产部署或生产数据库迁移。sync/async 在第一阶段仍只是受校验的配置声明；批准场景不会启动执行器或改变旧视频流。
