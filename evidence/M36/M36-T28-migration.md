# M36-T28 开发库相机策略迁移

日期：2026-11-04（Asia/Shanghai）。状态：数据库迁移完成，功能待人工复测。用户明确授权迁移，后端由用户重启。

- 目标：127.0.0.1:5432/aiyolo_dev，角色aiyolo_app；从应用现有配置读取，未输出连接凭据或修改.env。
- 版本：20261102_32 → 20261104_33。仅增加project_scene_plans.camera_policy，可空JSON列。
- 备份：backups/M36-T28-20261104-184018/aiyolo_dev-before-20261104_33.dump，6,977,206字节。SHA256：9a1471f4f534c76697a2c1b0946ee79e18735023565987e7091b0240cfbc6b0f。
- 已通过pg_restore目录检查和完整归档解析；未实际恢复到另一实例，不将可解析等同恢复演练通过。备份位于Git忽略目录，含业务数据，仅本机保管。
- 迁移在事务内执行，锁等待上限5秒、单语句上限60秒；失败会回滚，未使用stamp或删除旧数据。
- 迁移前后project_scenes 4条、project_scene_members 8条、project_scene_plans 2条、project_scene_plan_members 4条；排除新增列后的全行SHA256逐表一致。既有计划新增列保持SQL NULL，由应用使用默认配置。
- 已通过新连接确认提交后的版本、JSON列类型和nullable属性。完整脱敏日志：M36-T28-migration.log；执行脚本：M36-T28-migrate.py（仅允许来源版本32，禁止重复迁移）。
- 未改Default Project业务配置及批准状态，未重启后端、未重新发布管理端、未安装App、未提交或推送Git。

## 后续人工操作

用户重启后端并刷新新版管理端；在项目空间→识别场景→运行方案→移动相机运行设置核验字段。修改配置后更新方案、保存场景变更并重新批准；新版App使用获批配置。界面和真实设备测试仍待人工复测。
