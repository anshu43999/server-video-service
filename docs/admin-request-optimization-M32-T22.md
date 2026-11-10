# M32-T22 管理后台第一批请求优化验收

日期：2026-11-09（Asia/Shanghai）。任务：`M32-T22`，用户批准新增并绑定；依赖 `M32-T21`。

范围依据：`E:/aiyolo/docs/admin-request-analysis-20261109.md` 第七节第一批。仅本地源码、测试和验收记录。第二批可控轮询/缓存与第三批后端单次请求成本均未实施。

## 1. 实施结果

- route、monitor、focus、pageshow、denied 与业务 401 共用同一在途身份/项目验证。`verify` 不再模拟项目重新进入；显式 `enter` 仍执行项目授权进入；`leaveForPlatform` 不重入旧项目。
- 同一身份、权限上下文内的平台导航不清空 scope。仅导航可复用距上次成功验证不足 15 秒的权限结果；原有 15 秒监控、focus/denied 权威复核保留。模型 pane 切换保留父组件、目录和查询状态，未加入 KeepAlive。
- 复核期间主内容 inert，并遮蔽敏感内容及传送到 body 的弹窗/浮层；阻止新写操作和上传，不自动重放。身份、角色、协议、项目/成员修订变化，失败、离线、跨标签会话变化仍清空上下文和资源；旧响应不能恢复数据。登录失败清除旧身份；退出未确认时显示错误而非永久加载。
- 转换任务首次历史快照、进度/日志变化及环境 check 不刷新模型目录。inspect/mobile 每个 job ID + attempt 的终态至多触发一次刷新；同一快照的多个终态合并。失败/中断仍复核目录，以覆盖部分产物变更，不根据 job 状态推断模型已校验或可发布。已知活跃任务离开后返回目录时仍刷新权威数据。
- 直接查看校准集不读取模型目录。模型目录在真正需要时读取；单纯校准集修改不触发目录刷新。
- 已确认 M32-T21 的 `/video/healthz` 修复存在，未重复改动；常规业务 `/aiyoloapi` 路由不加 `/video`。

## 2. 真实执行的请求计数

环境：本机 Chromium 运行真实前端，隔离 Vite 端口 5192；业务 API/WS 使用 Playwright fixture 拦截。下面是浏览器实际发起的请求计数，不是源码推算；不是生产 Network/HAR 或生产性能验收。原方案的优化前数值仍属源码推算，未重放旧版本取得可比较的实测基线，因此不报告实测下降百分比。

| 场景 | 实际结果 | 结论 |
|---|---|---|
| 目录 → 上传 → 校准集 → 目录 | models 合计 1；pane 导航额外 me/projects 各 0；搜索输入保留 | 消除该路径父组件重挂载和重复目录加载 |
| 校准集深链首次进入 | models 0；切到目录后 1 | 不再为纯校准查看加载模型目录 |
| 初始历史与运行进度变化 | models 保持首次 1 | 历史/进度不被当作产物变更 |
| 第一次完成、第二次 attempt 失败 | models 由 1 → 2 → 3；重复终态和子页重入不再增加 | 每个影响产物的终态 attempt 至多一次刷新 |
| 项目 → 平台 | 增加 me 1、projects 1；旧项目授权进入请求不增加 | 离开不再重新进入旧项目 |
| 真实墙钟静置 60.5 秒（无活跃转换） | 增量 me 4、projects 4、jobs 20、models 0 | 权限复核未降频；目录无重复，jobs 降频留待第二批 |
| focus + pageshow 同时触发，弹窗已打开 | me 仅增加 1；复核时弹窗不可见，成功后草稿保留 | 合并在途复核，不牺牲敏感内容保护 |

日志：`evidence/M32-T22-requests-final-r2.log`。另有虚拟时钟 60 秒测试验证定时行为，其 jobs 计数不作为真实吞吐量。首次启动仍包含会话 restore 的 me 与平台授权的 me；本次未改成跳过初始身份核验。

## 3. 测试与复现

以 `E:/aiyolo/server-video-service/admin-web` 为工作目录：

```powershell
npm run typecheck
npm run test
npx vite build --mode production --outDir ../.tmp/m32-t22/dist
npx vite build --mode preview --outDir ../.tmp/m32-t22/dist-preview
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE='C:/Users/45393/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'
npx playwright test --config playwright.requests.config.ts --output test-results-m32-t22-final-r2
npx playwright test --config playwright.requests-subpath.config.ts --output test-results-m32-t22-subpath-final
```

- 类型检查通过：`evidence/M32-T22-typecheck-final.log`。
- Vitest：29 文件、239 测试通过：`evidence/M32-T22-full-tests-final.log`。包含验证合并、15 秒周期、账号/角色/成员修订、隐藏恢复、离线恢复、跨标签失效、旧 REST/WS/媒体/XHR 取消、禁止写重放、终态刷新语义、失败登录及退出未确认错误态。
- 请求与安全浏览器回归：13 通过：`evidence/M32-T22-requests-final-r2.log`。包含真实 60.5 秒静置、A/B 快切与晚到响应、角色撤销、修订变化、跨标签登出和弹窗遮蔽。
- Cookie/子路径浏览器回归：7 通过、3 跳过：`evidence/M32-T22-subpath-final.log`。使用隔离内存账户/项目存储和真实本地 auth/project handlers，端口 4195/4196；不读取应用数据库。覆盖登录/导航/刷新/退出、`/video/healthz`、`/aiyoloapi`、503 展示/恢复与真正取消请求。跳过原因：direct 模式不适用代理斜杠重定向 1 项；测试代理未暴露 admin-next 的 2 项。
- production/preview 本地前端测试构建成功：`evidence/M32-T22-build-production.log`、`evidence/M32-T22-build-preview.log`。输出只在 `.tmp/m32-t22/`；未覆盖已有 `admin-web/dist` / `dist-preview`；不是 Docker 镜像构建。
- Harness 单元测试 34 通过；完成记录写入后再次执行 validate/render。最终门禁证据：`evidence/M32-T22-harness-final.log`、`harness/records/M32/M32-T22.md`。

测试过程中曾遇到本机浏览器默认版本缺失/子进程权限限制，以及测试代码正则转义和旧页面标题断言问题，均已修正后重跑；保留早期日志，不把失败尝试视为通过。最终使用已安装 Chromium，不下载浏览器。原有代理测试仍输出两条 ECONNRESET，但进程成功且全部断言通过；npm 用户配置和色彩环境警告也未作为失败忽略计数。

## 4. 本次改动文件

路径均相对于 `E:/aiyolo/server-video-service`。12 个产品文件、7 个测试/测试配置文件；Harness 和本报告单列。

| 文件 | 改动 |
|---|---|
| `admin-web/src/api/auth.ts` | 身份验证支持取消信号 |
| `admin-web/src/api/client.ts` | 复核期写保护，避免 401 二次验证 |
| `admin-web/src/api/projectScope.ts` | verifying 和写保护状态 |
| `admin-web/src/api/projects.ts` | 权威项目验证跳过递归 session check |
| `admin-web/src/app/projectMonitor.ts` | 共用验证、跨标签同步失效、online 恢复核验 |
| `admin-web/src/app/router.ts` | 平台 leave/verify 分离 |
| `admin-web/src/stores/projects.ts` | 在途合并、平台稳定上下文和 fail-closed 生命周期 |
| `admin-web/src/stores/session.ts` | 401 接入共享核验，登录/退出竞态保护 |
| `admin-web/src/layouts/AdminLayout.vue` | 复核期间遮蔽/禁用而非重挂载 |
| `admin-web/src/features/models/ModelsView.vue` | 按需目录加载、稳定 pane、保留目录状态 |
| `admin-web/src/features/models/ConversionPane.vue` | 使用终态变化语义，保留 3 秒轮询 |
| `admin-web/src/features/models/catalogChanges.ts`（新增） | 按 job/attempt 追踪目录变化 |
| `admin-web/tests/projects.test.ts` | 权限、隔离、取消、并发/错误态回归 |
| `admin-web/tests/session.test.ts` | 失败登录清除旧身份回归 |
| `admin-web/tests/catalog-changes.test.ts`（新增） | 首次快照/进度/终态/重试语义 |
| `admin-web/tests-e2e/request-optimization.spec.ts`（新增） | 13 项浏览器计数与安全回归 |
| `admin-web/playwright.requests.config.ts`（新增） | 请求测试独立服务配置 |
| `admin-web/playwright.requests-subpath.config.ts`（新增） | 隔离 Cookie/子路径测试配置 |
| `tests/admin_subpath_server.py` | 可选测试构建路径，默认行为不变 |

Harness CLI 修改：`harness/task-state.json`、`harness/TASK_BOARD.md`、新增 `harness/records/M32/M32-T22.md`。验收说明：本文件。证据为 `evidence/M32-T22-*.log`；浏览器输出目录均使用 `test-results-m32-t22*`，避免覆盖其他任务结果。

## 5. 安全、已有改动与限制

- HEAD 保持 `889b60fb3cfad0414c1994dcbad2388192d300ec`；未暂存、commit、push、reset 或 clean。开始前已有 34 个跟踪文件变更及大量未跟踪成果；本次未清理、还原或覆盖。转换后端/worker、models registry/已有删除、已有后端测试等不是本次实现；Harness 文件仅由 CLI 在既有状态上新增/完成 M32-T22。
- `app/main.py`、`app/model_catalog.py` 及模型完整性/哈希/发布门禁未修改；未使用缓存或状态推断替代校验。本次未重跑生产模型文件/NFS 完整性负载测试，也未声称修复历史 502 或内存问题。
- 未修改开发服务器、生产、数据库、Nginx 或 K8s，未构建/导出 Docker 镜像。仅创建和运行本机临时测试服务及静态测试构建。
- 产品/测试范围 `git diff --check` 通过。全仓严格检查会提示 Harness 生成的任务板状态行末两个空格；`harness.py` 既有生成器使用该 Markdown 换行格式。本次未手工编辑任务板或扩大修改生成器；允许行末空格后检查通过。
- jobs 仍为 3 秒；后台补偿、推送、候选账号加载、查询缓存、图片/视频预览策略未改。校准集配置等子面板数据仍可能重复读取，留给第二批。
- 数据/权限/离线变化为隔离 fixture 驱动；未改真实账户权限、上传真实模型、调用转换工作器或建立真实视频流。真实业务有数据、生产响应耗时、NFS/CPU/内存与全量 WS 恢复链路仍需后续独立授权验收。
- 本批验证的是重复加载行为与本地安全回归，不是生产端到端性能结论。下一步须用户确认后，为第二批选择/定义匹配 Harness 小任务再实施。
