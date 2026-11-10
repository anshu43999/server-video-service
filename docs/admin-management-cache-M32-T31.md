# M32-T31 普通管理列表短期查询复用与安全失效

日期：2026-11-09（Asia/Shanghai）。任务依赖 M32-T30，经用户批准新增，并于 23:11:23+08:00 通过 Harness CLI 启动。实际工程为 `E:/aiyolo/server-video-service`。依据 `E:/aiyolo/docs/admin-request-analysis-20261109.md` 及 T30 实测缺口，只补齐项目成员、平台项目两页，不代表全站缓存或 M32 大任务验收。

## 1. 实施范围与安全边界

- 沿用已有 `ReadCache`，新增独立的管理列表缓存：10 秒 TTL、最多 32 个已完成条目，仅标签页内存，不写 localStorage、IndexedDB 或服务端。TTL 从成功读完成计时。
- 缓存 key 包含会话阶段、登出确认状态、账号、角色、平台角色、契约版本、scope enabled/generation/projectId、项目权限快照或平台可访问项目快照、业务标签和查询参数。相同内容的权限复核不会仅因对象引用变化导致重读。
- 首次挂载用 `loadInitial()` 允许短期复用；显式刷新始终失效再读。同一上下文在途读取合并；每个消费者独立取消，最后消费者退出才取消底层请求。
- 平台账号、平台项目、项目成员和负责人移交写入，在实际 HTTP 客户端写前、写后（包括错误、超时、取消）使管理缓存失效。不缓存写结果，不自动重放不确定写入。未改变无关业务的缓存策略。
- 写开始取消旧读并推进序号；成功后权威刷新，409、5xx、网络/超时等仍要求刷新核验。补齐了“刷新中发起写入且失败”释放 loading 的边界，避免刷新按钮永久禁用。
- scope 清除立即清空显示、取消读写、清共享缓存；上下文修订变化立即移除旧数据并读新结果。generation、序号、signal、context 多重检查丢弃晚响应；缓存命中也在交付微任务中再查取消和条目身份。
- 候选账号仍按需加载；未改权限 15 秒复核、告警 5 秒 REST 补偿、项目隔离、模型完整性校验。缓存只用于显示数据，不代替鉴权或版本检查。

**TTL 不是自动刷新间隔。** 长时间停留时不会每 10 秒重拉成员/项目列表；过期只使下一次读取不能复用。其他用户修改展示数据，在手动刷新、下一次过期读取或相关权限修订触发前可能暂未显示；权限安全依然由原有监控与服务端校验承担。

## 2. 已取得的真实测试证据

| 层级 | 本轮结果 | 证据与限制 |
|---|---|---|
| 全前端单测 | 35 文件、315 项通过，7.80 秒；其中新缓存测试 17 项 | `evidence/M32-T31-vitest-verified2.log`；虚拟时钟边界不冒充真实分钟流量 |
| Vue/测试 TypeScript | 通过 | `M32-T31-typecheck-verified2.log`、`M32-T31-e2e-types-verified2.log` |
| 修 loading 前完整浏览器联合回归 | 58 项通过，448.642 秒，0 failed/flaky | `M32-T31-browser-final-results.json`；不是最终源码覆盖的唯一证据 |
| 最终源码完整浏览器联合回归 | **59 项通过，425.043 秒，0 failed/flaky** | `M32-T31-browser-verified.log`、`M32-T31-browser-verified-results.json`；含新增 9 项管理列表场景 |
| 最终产物真实 Cookie/子路径 | 7 通过、3 适用性跳过，16.072 秒 | `M32-T31-subpath-verified-results.json`；direct 不适用代理 slash 1 项，代理不提供 admin-next 2 项 |
| 后端模型/权限/日志/WS 回归 | 116 项通过，84.170 秒 | `M32-T31-backend.log`；真实 ASGI/临时文件与内存鉴权，不连接数据库 |
| 本地 production / preview Vite 构建 | 两套通过 | `M32-T31-build-production-verified.log`、`M32-T31-build-preview-verified.log`；产物在 `.tmp/m32-t31-verified/`，不是 Docker |
| Harness 完成门禁 | CLI completed 于 23:41:50+08:00；34 项通过（0.062 秒），validate/render 通过 | `M32-T31-complete.log`、`M32-T31-harness-tests.log`、`M32-T31-harness-validate.log`、`M32-T31-harness-render.log`；补充风险后再次 validate |

最终浏览器运行实际 Vue 前端与本机 Chromium，业务 API/WS 为隔离合成 fixture；路径、计数、取消和真实墙钟来自本次运行，**不是生产 Network 或真实账号/摄像机验收**。HTTP/Cookie 子路径层使用临时内存服务，不启动产品 lifespan；不是实际 Nginx。后端 116 项包括模型来源、生命周期、下载、发布、分配、完整哈希、授权失效、日志去敏与 WS 缺口保护；WS 特性通过表示缺口被如实检测，不能据此放宽 REST 补偿。

测试端口为 5213、4213、4214，仅本机临时测试进程。前端漏拦截仅代理至 `127.0.0.1:1`，不连接既有开发服务。数据库连接显式清空，PG 测试与 APK worker/external 关闭；trace 关闭。新增证据不保存凭据、Cookie、Token、请求体、真实账号或原始异常输入。

最终浏览器 59 项与子路径 7 项为 66 项通过执行，另有 3 项适用性跳过；前面的 58 项及初轮子路径为重复回归，不叠加成独立用例数量。最终核对临时 5213/4213/4214 无监听；HEAD 仍为 `889b60fb3cfad0414c1994dcbad2388192d300ec`，索引为空。

## 3. 请求改善与边界实测

| 场景 | 实测结果 | 解释 |
|---|---|---|
| 平台项目→平台账号→平台项目 | 最终运行回访 35ms；返回列表额外读 0；显式刷新 +1 | 中间账号页的 1 次 accounts 为该页面必需，不是候选预取；focus 权限复核仍正常 |
| 成员→总览→成员 | 最终运行 77ms，返回 members 额外读 0 | T30 保存的 80ms 回访实测为 +1；本轮窗口仍有总览必需业务读 3 次，并非整个 A-B-A 零请求 |
| 成员页真实静置 60,502ms | 总请求 20：权限 8、告警 REST 补偿 12、额外 members 0 | 保留 me/projects 各 4 次，不缩减安全补偿来达成缓存预算 |
| 总览→看板→总览 | 最终运行 59ms，无新增 HTTP/WS | 既有看板缓存回归仍有效 |
| 成员离页 10.1 秒再返回 | members 总 2（首次、到期返回）；accounts 0 | 无新增成员后台 timer；过期后重新读取 |
| 成员写 200 / 409 / 503 | 各场景写 1 次，members 总 2；之后短期回访无新增 | 成功自动刷新，失败人工核验；无重放 |
| 平台写成功、随后权限项目修订 | platform/projects 总 3 | 首次、写后、权限修订后分别读取，不复用旧修订 |
| 平台刷新在途时写返回 503 | 写 1、platform/projects 总 3，刷新按钮可用并恢复最新数据 | 覆盖本轮边界修复，旧 pending 结果不恢复 |
| 项目 A 慢读→B→A | A 成员读 2、B 读 1，旧 A 请求取消 1 | 切项目清理缓存，重入 A 必须新读 |
| 平台角色撤销 | 旧项目列表从 DOM 移除，未新读平台项目 | 不以短期命中继续展示旧身份数据 |

这些结果证明所覆盖两页的短期重复加载已消除；不报告虚构的全站/生产百分比。T30 与本轮为各自保留的本地 fixture 运行，不是生产同条件 A/B 性能测试。原方案源码推算仍只作为设计背景。

## 4. 失败证据与修复链

1. 初始类型检查中正则转义错误：保留 `M32-T31-typecheck-initial.log`，改为明确的 RegExp 后通过。
2. 最初 8 项新浏览器测试 4 通过、4 失败，原因是测试导航误用 `accounts`（正确为 `platform/accounts`）及确认按钮文案定位错误；保留 `M32-T31-browser-focused.log`/JSON。修正 fixture 定位后相关场景通过，没有用生产功能改动迎合错误测试。
3. 补充边界测试真实复现加载态卡住：`M32-T31-cache-edge-initial.log` 为 15 通过、1 失败。原因是写入取消旧读并推进 readSequence，旧读 finally 不再负责清理 loading；现由写开始同步释放。最终 315 项单测和新增浏览器恢复场景均通过。
4. 后续类型检查发现测试中对 unknown 直接访问 `.kind`：保留 `M32-T31-typecheck-verified.log`，改用匹配对象断言，最终 typecheck、strict E2E tsc、全单测通过。
5. 所有初测、红测试及中间结果保留；最终证据使用 verified/verified2 新名称，没有把旧运行覆盖为通过。

## 5. 本轮改动文件

以下路径相对 `E:/aiyolo/server-video-service`，只描述本轮增量；这些文件部分已有历史未提交修改或为未跟踪文件，不能把整份 Git diff 归为 T31。

| 文件 | 本轮变化 |
|---|---|
| `admin-web/src/api/readCache.ts` | 管理缓存实例、管理写路径失效、缓存命中交付时取消检查 |
| `admin-web/src/api/client.ts` | 管理相关 HTTP 写入前后失效；原有 dashboard 失效保留 |
| `admin-web/src/features/management/readContext.ts`（新增） | 身份/scope/权限快照 key |
| `admin-web/src/features/management/useManagement.ts` | 可选共享读、初始/刷新区分、修订清理、取消/晚响应保护及写失败加载态恢复 |
| `admin-web/src/features/management/MembersView.vue` | 只给成员列表接入短期查询复用 |
| `admin-web/src/features/management/PlatformProjectsView.vue` | 只给平台项目列表接入短期查询复用 |
| `admin-web/tests/management-cache.test.ts`（新增） | 17 项缓存、真实 ApiClient 失效、身份隔离与写失败边界单测 |
| `admin-web/tests-e2e/management-cache.spec.ts`（新增） | 9 项真实 Chromium 场景与去敏计数附件 |
| `admin-web/tests-e2e/request-acceptance.spec.ts` | 将 T30 成员回访缺口特性断言更新为本轮 0 新读；T30 保存证据不改 |
| `admin-web/playwright.management-cache.config.ts`（新增） | 联合套件独立端口、run 目录与隔离代理 |
| `admin-web/playwright.management-cache-subpath.config.ts`（新增） | 独立构建/端口/证据，最终 run 参数防止覆盖旧证据 |
| `docs/admin-management-cache-M32-T31.md` | 本报告 |
| `harness/task-state.json`、`harness/TASK_BOARD.md` | 仅 Harness CLI 管理 T31 状态与 render |
| `harness/records/M32/M32-T31.md` | 完成后由 CLI 生成，附测试与如实风险 |

证据为 `evidence/M32-T31-*`、`admin-web/test-results-m32-t31-*`；本轮构建只写 `.tmp/m32-t31/` 和 `.tmp/m32-t31-verified/`，正式 `dist`/`dist-preview` 不改。不触碰已有模型 registry/删除项，不清理其他任务产物。

## 6. 复现命令

前端 cwd：`E:/aiyolo/server-video-service/admin-web`。重跑请先选未用过的安全 run 名，日志也使用新名称。

```powershell
npm run typecheck
npm run test
npx tsc --noEmit --target ES2022 --module ESNext --moduleResolution Bundler --strict --skipLibCheck --esModuleInterop --types node,vite/client tests-e2e/management-cache.spec.ts tests-e2e/request-acceptance.spec.ts playwright.management-cache.config.ts playwright.management-cache-subpath.config.ts
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE='C:/Users/45393/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'
$env:ADMIN_MANAGEMENT_RUN='rerun-1'
npx playwright test --config playwright.management-cache.config.ts
npx vite build --mode production --outDir ../.tmp/m32-t31-rerun-1/dist
npx vite build --mode preview --outDir ../.tmp/m32-t31-rerun-1/dist-preview
npx playwright test --config playwright.management-cache-subpath.config.ts
```

后端 116 项命令沿用 T30 报告列出的隔离 unittest 集；本轮证据见 backend.log。Harness 完成后在服务端 cwd 执行 `python -m unittest discover -s harness/tests -p "test_*.py"`、`python harness/harness.py validate`、`python harness/harness.py render`。

## 7. 遗留问题和授权边界

- 仅两个管理列表完成短期复用；其他普通列表、系统/项目知识筛选、App 配置及空流页优化不在本任务范围。
- WS 事件完整性前置条件仍不足，5 秒 REST 补偿与 15 秒权限复核保留；项目静态页约 20 请求/分钟的既有预算差距不能宣称已达 10/min。
- 未验证生产 Network、真实摄像机/转换 worker、数据库/NFS、多 worker、Linux、TCP 断连和长期稳定性；不宣称历史超时、502、内存问题已解决。
- 既有 Vue 数字属性类型警告、代理取消 ECONNRESET、npm 配置废弃提示及后端库警告仍存在，不扩大至无关修复。
- 未构建/导出 Docker；未变更开发服务器、生产、数据库、Nginx 或 K8s；未 stage/commit/push/reset/clean。未执行 accept-major，不自动定义或启动后续任务。任何发布仍须另获授权并遵守 Git-first 流程。
