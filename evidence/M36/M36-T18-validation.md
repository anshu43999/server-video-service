# M36-T18 联合方案后台配置与真实授权回归

日期：2026-10-21。任务：M36-T18。Android 消费任务：M108-T08。

## 交付内容

- 场景套件维护精确版本/目标端成员及图片/本机相机连续帧输入；方案选择成员并声明 single/sync/async。状态区分停用、待批准、待核验、客户端未支持与可使用（仍需在线预检），不把配置或批准描述为服务端推理。
- 成员“配置待审参数”入口按 sceneId/memberId/sceneRevision 定位，服务端推导模型版本及平台，不要求旧式模型分配。读取需要场景管理权限，保存还需要模型分配权限；参数 CAS、项目事务锁内授权/场景绑定重验、审计保留。
- 待审档案按项目/模型版本/平台共享；编辑不改变获准快照。显式重新批准核对逐成员参数，冻结方案 parameterSources 并递增场景 revision；旧 resolve/下载/参数链接失效。配置编辑自动清批准，无改动保存不写入。
- 前端保持现有绿色工业管理台及组件体系；已视觉检查1440px和390px截图，浏览器断言无水平溢出，并覆盖键盘 Enter/Escape、三角色可见性和修改重审流程。

## 实际测试

| 层级 | 结果 | 证据 |
|---|---|---|
| 前端完整单测 | 18文件、125项通过 | M36-T18-frontend-tests.log |
| 类型检查与生产构建 | 通过 | M36-T18-frontend-build.log |
| 生产构建浏览器 | 1440px/390px共2项通过 | M36-T18-browser-tests.log；M36-T18-scenes-{1440,390}.png；M36-T18-scenes-edited-{1440,390}.png |
| 后端相关回归 | 96项发现，91通过、5项PG专属跳过，无失败 | M36-T18-backend-tests.log |
| 参数入口及事务保护专项 | 22项通过（与后端回归有重叠，不重复累加） | M36-T18-profile-guard-tests.log |
| 独立PostgreSQL及迁移/并发回归 | 15项全部通过，无跳过；含上述基础持久化测试、参数/审批竞态及事务内撤权检查 | M36-T18-postgres-tests.log |
| 真实HTTP/PG双项目三角色 | 90次业务请求按预期通过，另3次退出登录；包括预期403/404/409拒绝 | ../../harness/evidence/M36/M36-T18-live-postgres-http.json |
| 验收客户端自身回归 | 4项通过：空Bearer、204空响应、外站URL拒绝、安全错误轨迹 | M36-T18-runner-tests.log |
| Harness单测 | 34项通过 | M36-T18-harness-tests.log |

后端回归命令：`PYTHONPATH=tests` 下运行 `.venv/Scripts/python.exe -m unittest test_project_scenes test_project_scene_authorization test_project_scene_installation test_project_scene_suite_contract test_scene_execution_parameters.SceneExecutionApiTests test_scene_execution_parameters.SceneParameterSqliteTests test_project_scene_suite_persistence test_m36_api_contract test_model_parameters_api -v`。PG测试由下面的隔离验收器显式覆盖环境并执行，不复用应用 `.env`。

浏览器使用已安装的 Chromium，通过 `PLAYWRIGHT_CHROMIUM_EXECUTABLE=C:/Users/45393/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe` 指定可执行文件；运行 `npm run test:e2e:production -- tests-e2e/scenes.spec.ts`。该环境配置仅作用于测试进程，不改仓库依赖或下载浏览器。

## 真实环境与结果

验收器：`tools/accept_m36_t18_live.py`。worker：`tests/m36_t18_server.py`，仅重定向存储构造位置，业务路由/权限/数据库为真实实现，不mock授权结果。

- 本次临时目录：`.tmp/m36-t18-a9be27501fe348e09453db620d0e348f`。PostgreSQL `127.0.0.1:54532/postgres`，显式 `initdb -U aiyolo_app`；服务 `127.0.0.1:54533`。已核对实际 data directory 和数据库角色。
- 使用两份已获内部测试发布授权的2.0.0/3.0.0模型版本副本，不调用发布接口、不改变源模型状态。模型ID：`uploaded-06b4dd2f10544673ab723226f91c34a7`。
- 隔离创建admin/gly/ptcy等效平台管理员/项目负责人/项目用户账号及两个项目，各有同ID混合套件，4成员、图片sync及视频async两方案。没有使用或变更开发项目账号。
- 每方案按输入只返回两位适用成员，逐成员核对项目/版本/平台/参数revision/快照，全部下载权重及Manifest并核对SHA256，不只抽查首成员。
- 项目A待审参数改为0.21，原获准值与项目B不漂移；重审后A场景revision变3、参数revision变1，旧场景revision拒绝。
- 旧v1/v2、缺失/不匹配执行模式、错误输入、旧修订、错误版本/平台/产物、普通用户写入被拒绝；配置编辑、撤销审批、成员撤权、临时副本模型撤回均使对应访问失效，未影响项目B的独立授权。
- SQL实证：2场景、4方案、8成员、1个项目自定义参数档案、23条项目审计；每方案有2份参数来源。审计requestId与HTTP关联，无旧式独立模型分配记录。JSON包含完整快照与去凭据请求轨迹。
- `passed=true`、`postgresRegressionExitCode=0`、`temporaryPortsClosed=true`、`sourceRegistryUnchanged=true`。本次精确服务进程和PG目录已停止，未停止其他实例。临时失败尝试日志保留，最终JSON仅以上述成功运行作为通过证据。

## Android M108-T08交接

- 套件契约仍为 `suiteContractVersion=2`；多成员resolve为 `resolveContractVersion=3`。请求须同时携带 `clientContractVersion=3` 和包含方案确切模式的 `supportedExecutionModes`。
- 响应 `members[]` 是完整配置集合，各带 `memberId/modelId/version/target`、参数revision/快照、精确产物摘要及项目/场景revision绑定。`artifacts[]`用于核验元数据，下载使用成员 `executionModel.artifacts[].url`；参数使用 `parameterUrl`。不能退回未授权的公共模型URL。
- `resolutionOnly=true`、`runtimeAuthorization=false`；安装/配置预检不产生离线运行授权，不证明Android调度器、同步/异步推理或告警合并已完成。实际运行仍须遵守当前项目、场景修订、成员发布状态及在线授权门禁。
- 真实可核验JSON：`harness/evidence/M36/M36-T18-live-postgres-http.json`，可按 projectId/sceneId/revision/planId/memberId 关联快照、SQL及审计；隔离服务已关闭，JSON中的临时链接不是可复用的长期环境。
- 文档 `docs/project-scene-suite-v2.md` SHA256：`0839DA9EA02E97009D6189457C821AB97EF2C4A80A1D09B23A227D7710DA2D6F`。
- 既有金样 `tests/fixtures/project_scene_suite_v2.json` 未改，SHA256：`3F523E5712C6001292877A381FCD86FAC873F6518C090BB19EF8DA8C5330928C`。

## 范围与遗留边界

不执行容器/生产部署、不更新127.0.0.1:8080开发服务或5432/aiyolo_dev、不改Default Project、不额外发布模型、不提交/推送Git。浏览器fixture仅证明交互及业务契约；HTTP/PG验收证明真实配置/权限/持久化，不证明真实模型推理。Android多模型图片/相机同步异步运行由M108后续任务验收，不是本服务端任务前置。共享待审参数不是独立方案参数覆盖，界面和文档已明确说明。
