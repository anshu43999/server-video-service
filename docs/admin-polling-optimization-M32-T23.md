# M32-T23 转换与推送轮询优化

日期：2026-11-09（Asia/Shanghai）。本任务是第二批的首个小任务；依赖已完成的 M32-T22。用户批准 M32-T23～M32-T26 定义后，通过 Harness CLI 登记四项，仅启动 M32-T23。M32-T24～M32-T26 保持 pending，不在本次记录中宣称第二批全部完成。

## 范围与实现

- 新增只供读取调用方使用的 VisiblePoller：同一端点最多一个未结束的读取；即使 transport 忽略 abort，也必须等旧 Promise 结束后才合并执行一次恢复读取。页面隐藏、离线或写操作暂停时取消读取和定时器，恢复可见/在线时立即核对；卸载与 scope 清理永久停止该实例，旧响应不可回写。
- 转换 jobs：queued/running（含环境 check）每 3 秒，空闲/全部终态每 30 秒。临时失败按 5/10/20/30 秒退避，封顶 30 秒；若服务端 Retry-After 要求更久则遵守。401/403/404/422 等非临时失败不自动定时重试；取消不展示为业务失败。
- 保留第一批 job ID + attempt 终态目录刷新语义，不将首次历史、进度或日志变化当成新模型；模型完整性/哈希/发布门禁未修改。
- 推送状态：pending > 0 时每 5 秒；空闲每 30 秒。明确测试已接受且回执未出现时，最多先快查 60 秒，之后仍保留“测试回执尚未确认”并转为空闲频率；若服务端仍有 pending 则继续 5 秒。失败/取消回执也属于终态，不能伪装成投递成功。
- 推送策略与状态分离：定时状态读取和显式投递测试不重读策略；保存/重置策略默认仍刷新权威配置。useManagement 的新可选参数默认 true，仅此类状态操作显式传 false。
- 转换写操作/上传、显式测试写操作均不自动重放。写后恢复 GET 核对，即使写响应不确定也不自动再次发送。15 秒权限核验、身份变化 fail-closed、跨项目隔离及旧请求取消机制保持。

## 真实计数与证据边界

环境为本机 Chromium + 真实前端，API/WS 由隔离 Playwright fixture 提供；没有调用生产 API、转换工作器或真实推送目标。墙钟测试与虚拟时钟测试分开记录，不把虚拟时间计数当吞吐量，也不将本地 fixture 耗时解释成生产响应耗时。

| 场景 | 本次实测 | 对比与解释 |
|---|---|---|
| 转换页真实静置 60.5 秒 | jobs 增量 2，models 增量 0；me/projects 各 4 | 第一批同类隔离墙钟测试 jobs 为 20，本次为 2，减少 18 次/90%；不是生产降幅 |
| 推送页真实静置 60.5 秒 | status 增量 2，policy 增量 0；me/projects 各 4 | 原 5 秒频率只作源码基线，不宣称有旧推送页实测比较 |
| 转换活跃 9.3 秒 | jobs 增量 3 | 保持 3 秒活跃更新；随后终态只新增一次 models 读取 |
| 隐藏/恢复（虚拟时钟 + 真浏览器请求） | 隐藏取消一个 jobs 请求，60 秒不再取；恢复新增一次 | 浏览器记录 net::ERR_ABORTED；没有显示取消为业务错误 |
| 临时失败（虚拟时钟） | 验证 5/10/20/30 秒退避及手动恢复 | 所有写入计数为 0；推进时间前等待权限响应，避免测试人为触发请求超时 |
| 显式推送测试（虚拟时钟） | 一次 POST；只刷新 status，policy 总计 1 | 匹配回执后降频；503 不确定写也不重放 |

第一批对照证据：evidence/M32-T22-requests-final-r2.log。当前最终证据文件：evidence/M32-T23-browser-final-r2.log 与 evidence/M32-T23-browser-results.json。JSON 附件只记录 fixture 场景、去敏路径/方法分类、资源时间和计数，不保存真实凭据或业务正文。

## 测试

- 类型检查：通过，evidence/M32-T23-typecheck-final.log。
- Vitest：31 文件、260 项通过，evidence/M32-T23-unit-final.log。覆盖单飞合并、ignored abort、隐藏/在线恢复、scope 停止、权限丢失、失败退避、Retry-After、写不重放、回执未确认和默认策略写后刷新。较第一批增加 21 项。
- 最终浏览器整套：19 项通过（2.7 分钟），evidence/M32-T23-browser-final-r2.log；包含 13 项第一批回归和 6 项新增轮询场景。
- Cookie/子路径：7 通过、3 按适用范围跳过，evidence/M32-T23-subpath.log。使用本地真实 auth/project handlers 和内存存储，未连接应用数据库。跳过项为 direct 模式的代理重定向断言 1 项、代理未暴露预览路径 2 项。
- 本地 production/preview 前端测试构建通过：evidence/M32-T23-build-production.log、evidence/M32-T23-build-preview.log。仅输出 .tmp/m32-t23/dist 与 dist-preview，不覆盖既有 dist，不是 Docker 构建。
- Harness 单元测试 34 通过：evidence/M32-T23-harness-tests.log；任务完成门禁证据为 evidence/M32-T23-harness-final.log，完成记录为 harness/records/M32/M32-T23.md。

早期浏览器运行有失败，保留 evidence/M32-T23-browser.log 和 M32-T23-browser-final.log。原因是一次跳过 30 秒虚拟时间，使同时发出的 15 秒权限请求尚未得到真实网络 fixture 回复就超时，触发正确的 fail-closed；不能删掉该保护让测试通过。改为按 1 秒分段推进并等待权限复核，同时等待对应错误序号的 UI 更新；两项针对性重跑通过（M32-T23-clock-fix.log）。最终必须以完整通过的整套结果为准。

原有代理测试继续输出两条 ECONNRESET，但 260 项断言和退出码均通过。npm 用户配置及颜色警告保留；未修改包管理配置或下载浏览器。

## 复现

在 E:/aiyolo/server-video-service/admin-web 执行：

    npm run typecheck
    npm run test
    npx vite build --mode production --outDir ../.tmp/m32-t23/dist
    npx vite build --mode preview --outDir ../.tmp/m32-t23/dist-preview
    $env:PLAYWRIGHT_CHROMIUM_EXECUTABLE='C:/Users/45393/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'
    npx playwright test --config playwright.polling.config.ts --output test-results-m32-t23-final-r2
    npx playwright test --config playwright.polling-subpath.config.ts

端口：Vite 5193；隔离 Cookie/子路径 fixture 4197/4198。每次使用独立测试输出目录，失败日志和第一批证据保留。仅启动本机临时验收进程，没有修改共享开发服务。

## 本次改动文件

以下相对路径均位于 E:/aiyolo/server-video-service。本次 4 个产品文件、7 个测试/配置文件；第一批及其他任务改动不重复算作本次成果。

| 文件 | 本次变更 |
|---|---|
| admin-web/src/api/visiblePoller.ts（新） | 单请求、可见性、退避与生命周期管理 |
| admin-web/src/features/models/ConversionPane.vue | jobs 自适应轮询、写操作暂停/恢复、真实频率说明；保留第一批改动 |
| admin-web/src/features/operations/PushView.vue | 状态自适应轮询、测试回执追踪、策略分离 |
| admin-web/src/features/management/useManagement.ts | 可选写后刷新开关，默认行为不变 |
| admin-web/tests/visible-poller.test.ts（新） | 调度/取消/恢复/退避单元测试 |
| admin-web/tests/polling-components.test.ts（新） | 转换及推送组件真实行为测试 |
| admin-web/tests/management.test.ts | 默认写后刷新与显式跳过回归 |
| admin-web/tests-e2e/polling-optimization.spec.ts（新） | 六项浏览器轮询场景及脱敏计数 |
| admin-web/tests-e2e/request-optimization.spec.ts | 第一批回归保留，仅更新空闲 jobs 的目标预算为 2 |
| admin-web/playwright.polling.config.ts（新） | 独立轮询浏览器测试服务及 JSON 报告 |
| admin-web/playwright.polling-subpath.config.ts（新） | 指向本任务隔离构建的子路径测试配置 |

另有本报告、evidence/M32-T23-*、harness/records/M32/M32-T23.md；harness/task-state.json 与 TASK_BOARD.md 只经 CLI 新增已批准任务和更新状态，保留其他任务内容。

## 未解决问题与边界

- M32-T24 告警补偿、M32-T25 共享查询/按需候选、M32-T26 图片/预览仍待办；告警全局 5 秒补偿本次未改，不能把整个项目页总请求说成每分钟 2 次。推送真实静置场景仍可见该后台告警流量。
- 回执未出现在最近 50 条中时保持未确认，最多快查一分钟后慢查；不代表已送达，也不自动重发。若测试期间其他任务仍 pending，按活跃频率继续。
- 取消浏览器请求不保证服务器已终止处理；这里验证的是客户端停止读取/拒绝旧响应，不能宣称撤销已经提交的后端作业。
- 未触发真实转换、上传真实模型、修改真实权限、发送真实通知或访问生产数据库；真实数据/真实设备场景和生产延迟、CPU/NFS、内存问题未验收。
- 未更改权限复核周期和模型完整性检查，未修改后端、数据库、Nginx/K8s、Dockerfile 或依赖；未构建/导出 Docker，未部署、commit/push、reset/clean。HEAD 保持 889b60fb3cfad0414c1994dcbad2388192d300ec，已有工作区变更不清理。
- 本次产品/测试 git diff --check 通过；全仓仍有 Harness 生成 Markdown 双空格的既有提示，不手工改写任务板。
