# M33-T52 模型显示名称统一

人工状态：待人工复测；未代填人工验收通过。

原因：上传名称保存在模型资产name，但场景成员没有平级名称字段，移动端及多个后台模板直接显示modelId。
本任务为获权场景成员及项目分配读取投影提供modelName，精确匹配modelId/version；缺失名称显示“未命名模型”。
名称只影响读取展示，不写入场景、参数快照、审批修订或运行/签名身份；不按名称合并同名模型。
后台场景卡片、成员编辑、方案成员选择、逐成员参数审核、项目模型卡片和停用/移除确认使用共享名称规则。
视频流模型状态使用已有name，告警获权读取按精确版本补充名称；不会修改历史告警。

验证（2026-11-03）：

- 后端命令：PYTHONUTF8=1、DATABASE_URL为空、PYTHONPATH=tests，venv Python unittest test_model_display test_project_model_inventory test_project_scenes test_project_scene_authorization -q。
- 62项：49通过、13条件跳过（PostgreSQL opt-in），0失败，99.637秒。不使用业务数据库，未宣称执行PG用例。
- 新回归覆盖精确版本的中文上传名、缺名/不猜最新版本、只读投影不改变存储和修订、跨项目拒绝、告警历史不变。
- 前端：npm run test -- tests/model-presentation.test.ts tests/scenes.test.ts tests/project-business.test.ts tests/streams.test.ts tests/alerts.test.ts；5文件59测试全部通过。
- 实际Vue挂载验证无项目模型管理权限用户仍看到场景成员名称，特殊字符按文本转义。
- npm run build：vue-tsc --noEmit及production Vite构建通过，生成dist；没有重建页面布局。
- Harness unittest 34项全部通过，validate通过；complete后render并读回记录。

本任务未重启运行服务、未修改Default Project或其他业务数据、未安装或更新App。移动端另一个小任务顺序接入该展示契约；运行服务加载新版代码和移动端更新后方可做联合人工复测。
保留npm现有配置弃用提示和依赖中的Vue组件警告，不将这些提示视为功能测试失败；未增依赖。不提交或推送Git。
