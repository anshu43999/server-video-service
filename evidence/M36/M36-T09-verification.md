# M36-T09 本机8080开发服务更新验收

日期：2026-10-20。用户授权：先更新当前运行服务。范围仅为本机开发实例，不是生产发布、Docker/Kubernetes部署或场景审批。

## 更新结果

- 已确认原实例使用项目 `.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080`；配置为 development，数据库为127.0.0.1:5432/aiyolo_dev，应用角色aiyolo_app。原进程没有reload，更新前健康接口streams=0。
- 通过Harness CLI新增、核对并启动M36-T09，依赖已完成M36-T08。既有生产/容器部署任务与门禁不变。
- 前端在独立暂存目录构建、类型检查通过，停服后整体切换dist；旧dist已保留。
- 停止经端口和命令行核验的原两个Python进程后执行pg_dump，自包含备份4,708,145字节；SHA256为`6c56ffbfc5116aae0da2486f07d752d875a96c19e7e4c030ec315bdfe713a4d6`。
- 在随机端口、仅回环监听的独立临时PostgreSQL集群恢复备份，28张表全部行数和排序行内容SHA256一致；恢复验证集群已停止。
- 真实开发数据库从20261019_15迁移至20261020_16；唯一约束现在包含project_id、scenario、parameter_platform。除alembic_version外，迁移前后全部业务表的行数和内容哈希一致。
- 按原监听地址和端口启动配套后端，健康为ok，PostgreSQL schema为ready；未改.env、模型注册文件和权重文件。

## 验证

1. 带RUN_POSTGRES_TESTS=1的M36-T08同范围后端89项测试全部通过，包含真实隔离PostgreSQL迁移/并发；运行51.353秒。未宣称全服务端回归通过，既有M33-T26不在本次关闭范围。
2. `npm run build -- --outDir dist-m36-t09-staging`：vue-tsc与production构建通过，切换后的HTML与暂存构建一致，全部入口JS/CSS返回200。
3. admin和gly真实登录成功，项目列表、模型分配、可用模型和场景查询均200。新双端批量接口使用空的无效请求返回422，并出现在活动OpenAPI中，证明路由已装载；没有提交有效授权变更。登录生成会话、读取可能记录审计，属于正常验收行为。
4. 已安装Chrome访问真实8080、真实Default Project和已发布helmet/1.0.0模型；1440px与390px均可在未保存草稿中同时勾选PC/移动端，取消退出。既有测试场景可见，无页面异常或服务端5xx；浏览器防护拒绝任何模型分配/场景写请求，实际写请求数为0。
5. 浏览器完成后再次核对accounts、projects、project_memberships、project_model_assignments、project_scenes、project_scene_members，全部仍与停服备份前哈希一致。原有一条分配未扩为双端，场景未被自动审批。
6. Harness34项单元测试通过。首次受Windows临时目录权限影响，按审批流程在沙箱外重跑通过；浏览器同样在获准后运行。首次页面标题定位匹配h1/h2而失败，收紧至h2后两种宽度全部通过，未修改产品代码。

## 可定位证据

- `evidence/M36/M36-T09-runtime-update.json`：版本、备份摘要、28张表基线、接口验证及健康。
- `evidence/M36/M36-T09-live-browser.json`、`M36-T09-live-smoke.cjs`：真实服务浏览器检查结果与可重复脚本。
- `evidence/M36/M36-T09-live-models-1440.png`、`M36-T09-live-models-390.png`、`M36-T09-live-scenes-1440.png`、`M36-T09-live-scenes-390.png`：真实页面截图。
- `tools/refresh_local_m36_service.py`：本次受限维护执行脚本，旧进程ID和旧迁移版本均有保护，不能当作通用重启工具重复运行。
- 私有备份目录：`E:/aiyolo/server-video-service/backups/M36-T09-20261020-123707/`。包含`aiyolo_dev-before.dump`、`frontend-before/`及迁移、备份、恢复、服务启动日志，已配置目录访问控制，且backups被Git忽略。

## 恢复边界与保留事项

- 当前运行正常，未执行回退。若需回退先停写、对回退时刻数据另做备份，评估更新后的新数据；不得直接将历史备份覆盖活库。
- 首先向独立恢复目标恢复并核对备份，再决定数据库切换；当前只演练独立恢复，没有清空或覆盖aiyolo_dev。
- 数据库降级要求同一场景尚无双端记录；一旦有双端记录，即使一端停用，20261020_16降级保护也会拒绝。不得删除授权绕过保护。前端回退须整体恢复frontend-before并与匹配后端、数据库版本配套。
- Default Project模型授权、场景批准和Android M104-T04真实消费验收不在本次操作范围。未执行多模型sync/async推理，未部署容器，未修改Android，未提交或推送Git。
