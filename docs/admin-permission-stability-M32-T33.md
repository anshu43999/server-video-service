# M32-T33 后台权限复核视觉稳定性修复

日期：2026-11-10（Asia/Shanghai）。实际工程：E:/aiyolo/server-video-service；前端：admin-web。

## 授权与任务边界

用户授权修复请求优化后页面闪烁，并在说明与M27-T08业务文件不重叠、共享Harness及Git风险后明确要求开始。本轮按该单任务规则例外，经CLI新增并启动M32-T33，依赖已完成的M32-T32；不改全局工作规则，不启动第二个本轮小任务，不改变M27-T08状态。Harness每次从当前状态执行CLI，保留另一任务；没有stage/commit/push/reset/clean。

仅修复前端权限复核展示，保留既有未提交成果；没有修改转换后端、Dockerfile、依赖约束、模型registry/权重、数据库、开发服务器或生产。正式admin-web/dist、dist-preview不覆盖。

## 根因与改动

此前projects.verifying同时承担网络复核和遮蔽展示：每15秒置true，AdminLayout添加body.permission-verifying，隐藏正文、项目栏、告警通知和teleport弹窗；同时插入占文档流的提示段落。DOM不必重建也会整页闪烁。原对话诊断曾测得正文top 163.171875→204.96875→163.171875，即约41.8px跳动；该数据来自原对话工具输出，没有对应报告/截图文件，本轮不杜撰历史证据。

本轮仅三个产品文件增量：

1. **src/stores/projects.ts**：新增permissionBlocking视觉风险状态；verifying/projectScope.verifying仍对每次复核保持写屏障。revalidate默认仍是阻断型，仅明确background=true且已有成功验证、有效项目ready或platformReady时允许连续显示。高风险调用在返回共享在途Promise之前先升级遮蔽；后来的低风险调用不能撤销升级。hard继续清空/取消旧上下文，重建epoch，拒绝晚响应。
2. **src/app/projectMonitor.ts**：15秒周期、普通focus/pageshow、短时恢复使用常规后台复核；denied（包括既有403/404/WS拒绝入口）使用阻断型。业务401经既有session verifier默认阻断型。persisted pageshow（bfcache恢复）丢弃可能错过会话事件/计时器的旧上下文。长隐藏、离线、跨标签旧逻辑保留。
3. **src/layouts/AdminLayout.vue**：body遮蔽及main inert由permissionBlocking驱动；aria-busy仍反映verifying。高风险提示改为fixed，不挤动正文；顶栏状态预留宽度，切项目按钮保持固定文案。RouterView epoch:path不变，不用KeepAlive、延时隐藏或关闭安全遮蔽掩盖问题。

写入与上传仍由现有ApiClient/projectScope拒绝，绝不排队重放。常规复核可继续编辑草稿，但提交会显示“正在复核权限”，复核结束后必须由用户再次明确提交。

## 风险分类与安全契约

| 触发 | 展示 | 请求和失效 |
|---|---|---|
| 有效上下文的15秒周期/普通focus/pageshow/短隐藏返回/过期平台导航 | 正文及teleport连续可见、保持焦点草稿 | me/projects共享在途；写屏障不变 |
| 未建立可信上下文、业务401、403/404、WS权限拒绝、显式默认revalidate | 立即遮蔽正文及teleport，main inert | 共享在途但先升级风险；无变化才恢复 |
| 跨标签、离线、项目切换、hard、自身账号修改、长隐藏、bfcache | 清空旧内容/卸载弹窗 | generation/epoch推进、取消旧资源，晚响应不恢复 |
| 账号/角色/契约/当前项目修订成员权限变化、me/projects错误或超时 | 清除旧内容，提示或登录 | 保留401/403语义；失败不自动回到旧业务页 |

auth/me、auth/projects各自原有15秒请求超时保持，不新增无限等待或重试。单次顺序me+projects仍可能接近两个超时窗口；未声称零延迟撤权。无客户端事件的服务端变更，仍由15秒复核加网络处理时间发现；实际请求始终受服务端鉴权裁决。告警REST补偿5秒不降频，知识筛选/刷新接口不动，模型完整性和旧请求隔离不动。

## 已实跑证据

所有路径相对服务端根；后续重新运行须换run及日志名。不是生产Network或真实业务账号验收。

- 红测试：evidence/M32-T33-browser-red.log，真实Chromium在旧产品源码上因main仍为inert失败；原focus“遮蔽成功”测试按新风险分类更新，另新增401/403/404升级遮蔽测试，不是删除安全覆盖。
- 初始单测红记录：M32-T33-unit-red.log。2项新状态契约失败；失败测试未及时清理monitor还导致5项连带失败，随后补afterEach清理，未将其冒称5项产品缺陷。
- 首轮定向：45项单测最终通过（M32-T33-unit-focused2.log）。中间pageshow模拟未带persisted属性导致1项失败，改用显式属性；真实Chromium使用真实PageTransitionEvent。
- 新增Chromium：13项通过，0 failed/flaky，87.294秒（M32-T33-browser-focused2-results.json）。第一次运行缺少测试函数闭合括号导致解析失败，保留focused日志；修正后严格tsc及真实运行通过。
- 逐帧取证：1440px采样1319帧（复核中114帧），390px采样1323帧（复核中119帧）；main top分别163.171875和144.078125，正文及弹窗最大位置变化均0px；每帧可见、同一节点、焦点/选区/草稿/滚动不变。真实15秒timer，auth/me人为延迟800ms；每次额外me/projects各1，models 0，业务写0。该延迟不是实际服务延迟。截图在admin-web/test-results-m32-t33-focused2/的两个real用例目录，before.png/during.png；桌面和窄屏均人工图像核对。
- 非零scrollY=450的focus+pageshow合并、401/403/404在途升级及恢复、提交写拒绝无重放、me/projects超时晚响应、离线/跨标签/bfcache/长隐藏失效均覆盖。
- 完整联合Chromium：85项通过，0 skipped/failed/flaky，678.353秒（M32-T33-browser-final-results.json）。包含原有72项及本次新增13项，未降低真实60秒窗口的请求预算断言。
- 完整回归逐帧结果：1440px采样1328帧、复核中95帧；390px采样1314帧、复核中117帧。正文及弹窗最大位移均0px，可见性/同一节点/焦点异常帧均0；选区、草稿、滚动及导航次数断言通过。原始逐帧附件保存在完整JSON的frame-stability附件内；最终截图在admin-web/test-results-m32-t33-final/对应real用例目录，已图像核对。
- 完整回归日志审计发现原request-optimization夹具health缺database、平台metrics缺system，虽然85项断言通过，诊断页仍有未处理渲染错误。仅补齐该测试夹具，取消请求用例增加诊断内容与pageerror为空断言，未改诊断页产品逻辑。受影响13项全量补跑通过，0 skipped/failed/flaky，88.740秒（M32-T33-browser-fixture-final-results.json）；补跑日志无Unhandled error/TypeError/ReferenceError，严格E2E/config tsc再次通过（M32-T33-e2e-types-fixture-final.log）。重复运行不计为新增用例；联合与子路径合计92个通过、3个适用性跳过。
- 全前端单测：36文件329项通过，26.20秒（M32-T33-unit-final.log）。Vue typecheck及严格E2E/config tsc通过（M32-T33-typecheck-final.log、M32-T33-e2e-types-final.log）。
- production/preview本地构建通过（M32-T33-build-production.log、M32-T33-build-preview.log），仅.tmp/m32-t33-final/dist和dist-preview，不是镜像。
- 真实HTTP/Cookie/子路径：7通过、3适用性跳过，20.5秒（M32-T33-subpath-final-results.json）。direct不适用代理slash一项；模拟代理不开放admin-next两项。端口4228/4229，内存服务、不启产品lifespan或数据库。
- 后端隔离回归：MemoryProjectAuthorizationTests、CapabilityMatrixTests、ProjectManagementMemoryTests及5项AlertSyncCoverageTests，共8通过，5.729秒（M32-T33-backend-memory.log）；DATABASE_URL显式空、PG及APK worker/external关闭。WS测试确认既有缺口存在，不能据此放宽REST补偿。没有把T32的117项历史结果当本轮结果。
- Harness预完成单测34项通过（M32-T33-harness-precomplete.log），完成前validate及限定文件git diff --check通过。

## 完成登记与收尾门禁

2026-11-10 14:08:56（Asia/Shanghai），通过Harness CLI完成M32-T33，记录为harness/records/M32/M32-T33.md，命令输出为evidence/M32-T33-complete.log。完成操作前后读取M27-T08并比较，完整任务对象未变，仍为in_progress，startedAt保持2026-11-10T13:29:28+08:00。本轮未操作另一任务的产品文件或Git发布流程。

完成后重新执行Harness单元测试34项通过（0.104秒，M32-T33-harness-final.log）、validate通过（M32-T33-validate-final.log）、render成功（M32-T33-render-final.log），并回读T33状态为completed及完成记录。测试端口5228/4228/4229已无监听；正式dist/index.html和dist-preview/index.html最后修改时间仍分别为2026-11-09 15:00:46、15:00:54。没有覆盖正式产物、提交/推送代码或部署；真实业务数据与生产环境验收仍不在本轮覆盖范围内。

## 本轮文件清单

- 产品：上述admin-web/src/stores/projects.ts、src/app/projectMonitor.ts、src/layouts/AdminLayout.vue。
- 测试：admin-web/tests/projects.test.ts（2项状态契约）、tests-e2e/request-optimization.spec.ts（普通focus契约更新、诊断夹具完整性及无页面异常断言）、新增tests-e2e/permission-stability.spec.ts（13项）。
- 独立测试配置：新增admin-web/playwright.permission-stability.config.ts及playwright.permission-stability-subpath.config.ts。测试Vite端口5228，strictPort、reuseExistingServer=false；未拦截API仅到127.0.0.1:1，WS由fixture截获；trace关闭。
- 文档：本文件。Harness/task-state.json、TASK_BOARD.md及records/M32/M32-T33.md仅由CLI更新/生成。
- 证据：evidence/M32-T33-*与admin-web/test-results-m32-t33-*，不覆盖以前任务证据。

Git整文件diff含前序未提交工作，不能全部归为T33；尤其projects.ts和projects.test.ts。本轮没有变更ApiClient、projectScope、session或后端产品代码。

## 周期刷新核查与限制

模型refresh不重新置loading；转换jobs轮询不更改初始化phase；流轮询使用loadStreams(true)；告警后台刷新不切首屏loading；看板刷新保留旧统计并更新按钮状态。因此所查健康轮询没有同类整页v-if替换；错误、显式筛选/初次加载的状态切换有业务含义，不扩大改造。未宣称逐页所有局部组件永不变化。

保留既有Vue数字prop类型警告、npm配置弃用和取消连接ECONNRESET日志，未扩大到无关修复。新测试为真实浏览器加合成API/WS；未调用用户现有8080、真实模型/摄像机、转换worker、生产/数据库或远端服务。用户实际业务数据、多标签长期运行、真实网关延迟及生产需人工复测/另行授权；本地通过不代表生产已修复。

当前源码不自动更新由FastAPI托管的旧dist。既有Vite开发服务可能按其正常HMR读取改动；本轮没有重启用户服务或覆盖正式产物。正式发布仍需另获Git-first提交/构建及生产授权。

## 复现命令

前端cwd：E:/aiyolo/server-video-service/admin-web。先确认5228/4228/4229空闲；重跑使用未占用的新run和日志名，不能覆盖本轮证据。

```powershell
npm run test
npm run typecheck
npx tsc --noEmit --target ES2022 --module ESNext --moduleResolution Bundler --strict --skipLibCheck --esModuleInterop --types node,vite/client tests-e2e/permission-stability.spec.ts tests-e2e/request-optimization.spec.ts playwright.permission-stability.config.ts playwright.permission-stability-subpath.config.ts
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE='C:/Users/45393/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'
$env:ADMIN_STABILITY_RUN='rerun-1'
npx playwright test --config playwright.permission-stability.config.ts
npx vite build --mode production --outDir ../.tmp/m32-t33-rerun-1/dist
npx vite build --mode preview --outDir ../.tmp/m32-t33-rerun-1/dist-preview
npx playwright test --config playwright.permission-stability-subpath.config.ts
```

后端与Harness cwd：E:/aiyolo/server-video-service。只运行隔离内存类，不运行数据库测试类。

```powershell
$env:DATABASE_URL=''; $env:RUN_POSTGRES_TESTS='0'
$env:APP_APK_WORKER_ENABLED='false'; $env:APP_APK_EXTERNAL_ENABLED='false'; $env:PYTHONPATH='tests'
.venv/Scripts/python.exe -m unittest test_project_authorization.MemoryProjectAuthorizationTests test_project_authorization.CapabilityMatrixTests test_project_management_api.ProjectManagementMemoryTests test_alert_sync_coverage -v
python -m unittest discover -s harness/tests -p 'test_*.py'
python harness/harness.py validate
python harness/harness.py render
```
