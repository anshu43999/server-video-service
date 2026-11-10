# M32-T30 管理后台请求优化联合回归与验收汇总

日期：2026-11-09（Asia/Shanghai）。任务依赖 M32-T29，2026-11-09T22:43:02+08:00 经 Harness CLI 启动。范围依据为 `E:/aiyolo/docs/admin-request-analysis-20261109.md`；复验 T22～T29，不代表 M32 大任务验收或生产发布通过。

## 1. 结论

本地联合回归通过，前序重复加载、受控轮询、候选懒加载、媒体并发和模型校验保护仍有效。**原方案并非全部目标已达成**：普通管理列表尚未普遍复用短期读结果；WS 完整性不足，项目静态页仍保留 5 秒 REST 补偿。不得把测试通过解释成这两个预算已达成。

本轮只新增/修正验收测试、隔离配置、证据与报告，未修改 `admin-web/src` 或 `app` 产品代码；未降低权限复核、项目隔离、旧请求取消或模型完整性门禁。未运行 Docker、开发服务器/生产部署、数据库、Nginx/K8s 修改及 Git stage/commit/push/reset/clean。

## 2. 证据分层

| 层级 | 本轮实际执行 | 不证明的事项 |
|---|---|---|
| 前端单元/组件 | Vue/TypeScript 与 Vitest；虚拟时钟用于重试、隐藏恢复等边界 | 不作为真实每分钟吞吐量 |
| 真实 Chromium + synthetic API/WS | 运行实际前端，Playwright 拦截业务，真实墙钟静置、导航、图片解码与取消 | 不是生产 Network、真实账户撤权或真实摄像机/转换服务 |
| 本地真实 HTTP/Cookie | 临时回环端口 4210/4211，内存账户/项目及真实 auth/project handler；模拟子路径代理 | 非实际 Nginx/生产网关；health/metrics 为测试返回 |
| 真实 ASGI/临时文件 | 实际模型 API、权限/隔离/校验代码；内存鉴权和临时模型文件 | 无生产数据库/NFS；ASGITransport 不是真实 TCP 断连 |
| 生产与长稳 | 未执行 | 未证明生产 p95、CPU/内存、NFS、多 worker 或历史 502 根因已解决 |

隔离前端使用 5210，独立业务回归使用 5212；未拦截的 API 只代理至 `127.0.0.1:1`，不会回退到现有 8080 服务。数据库 URL 显式清空，APK 后台开关关闭，PG 测试关闭。子路径 server 不启动 `app.main` lifespan 或真实模型；模型测试使用既有隔离 fixture。

新增观测只保存方法、去敏路径、白名单查询类别、阶段、状态、相对起止/耗时、资源 Initiator/传输大小与取消分类；不保存请求体、响应体、headers、Cookie、Token、密码或原始异常。trace 关闭。拦截流量的 transferSize/耗时不能解释成生产响应字节/后端性能。取消是独立结果维度，不是普通业务失败。

## 3. 首次进入、真实静置和 A→B→A

下表最终分类取自 `evidence/M32-T30-browser-final-results.json` 内 JSON 附件；`browser-results.json` 为较早的完整联合运行，保留未覆盖。最终观测将项目授权 detail 归为权限、`alerts?limit=20` 归为页面业务、无 limit 的全局 alerts 归为后台补偿。初轮仅这两处分类不同，总请求数相同。

| 场景/统计窗口 | 权限 | 业务 | 全局补偿 | 图片 | 取消/网络失败/HTTP错误 | 结果 |
|---|---:|---:|---:|---:|---|---|
| 成员页首次进入 | 5 | 1 | 2 | 0 | 0/0/0 | 总计 8，WS 建连 1；members 1，accounts 0 |
| 成员页静置 **60,512ms** | 8 | 0 | 12 | 0 | 0/0/0 | 总计 20；me/projects 各 4；无重复 members |
| 总览首次进入 | 5 | 3 | 2 | 0 | 0/0/0 | 总计 10；stats/streams/recent 各 1 |
| 总览→看板→总览 **57ms** | 0 | 0 | 0 | 0 | 0/0/0 | 未新增 HTTP/WS；复用原三份数据 |
| 成员→总览→成员 **80ms** | 0 | 4 | 0 | 0 | 0/0/0 | 总览必需三份数据 + 返回 members 1；成员缓存预算未达成 |

首次权限 5 次具体为 status 1、me 2、projects 1、项目授权 detail 1；没有将首次恢复身份的第二次 me 隐藏成零。所有阶段以请求开始时所属窗口计数，最后 pending 均为 0。空图片计数不等于有媒体场景通过，媒体另测。

完整联合套件中的其他真实墙钟观测：

| 场景 | 本轮实测增量/行为 |
|---|---|
| 上传页空闲 60.5 秒 | jobs 2；额外 models 0；me/projects 各 4 |
| 活跃转换 9.3 秒 | jobs 3；终态后目录仅刷新一次；不因进度或首次历史刷新 |
| 推送空闲 60.5 秒 | status 2；额外 policy 0；me/projects 各 4 |
| 健康 WS 静置 60.5 秒 | alerts 12；me/projects 各 4；维持一个 socket |
| 总览静置 60.5 秒 | stats/streams/recent 各 6；me/projects 各 4；全局 alerts 12，共 38 次增量 |
| 模型目录→上传→校准→目录 | models 合计 1；纯 pane 切换额外 me/projects 0；校准深链 models 0 |
| 图片证据 | 首屏可见懒加载，最多 3 个并发 handler；离页取消 3 个 pending；撤权清除详情与图片 |
| 合成 JPEG 预览 10.1 秒 | 正常帧增量 47 次；无帧后另一 10.1 秒仅 4 次，清除旧图并显示等待 |

以上不是优化前后同条件 A/B 抓包。本轮没有重放优化前版本，不将原方案源码估算写成实测降幅。前序 T22 曾实测 jobs 20 次/60.5 秒，本轮为 2，属于不同时间本地 fixture 记录，不能据此宣称生产降幅。

## 4. 原方案第八节目标预算逐项判定

| 预算 | 判定 | 依据/限制 |
|---|---|---|
| 同平台模型 pane 不重复上下文清理/鉴权 | **通过（本地）** | 父组件搜索状态保留，models 1，导航额外 me/projects 0 |
| 一次权限复核共用在途请求、不重新 enter 旧项目 | **通过（本地）** | 同时 focus/pageshow 合并；项目→平台只一对 me/projects；权限变更仍 fail closed |
| 必需读取并发有界，5 秒内返回普通列表复用 | **部分通过 / 普遍复用未达成** | 已接入 poller/cache/候选并发测试通过；总览回访 0 新读，但 members 在 80ms 回访重拉 1 次；未对所有普通页面逐一做并发/三段取证 |
| 纯校准集查看不读取目录 | **通过（本地）** | 深链 models 0；子面板配置/校准数据仍可能重复，非全局缓存 |
| 平台项目/成员未打开选择器不取 accounts | **通过（本地）** | 两页首屏 accounts 0；创建/添加时才取 1，撤权/关闭取消 |
| 转换空闲 jobs 约 2/min，无变化 models 0 | **通过（本地）** | 真实 60.5 秒 2/0，活跃 9.3 秒 jobs 3 |
| 项目静态列表约 10/min（WS 完整时） | **未达成，前置条件不满足** | 实测 20；后端 5 项特性测试再次确认过滤、丢队列、无重播、进程局部、结束状态不广播；必须保持 5 秒补偿 |
| 离开/隐藏停止、恢复合并，旧项目资源失效 | **通过（已覆盖场景）** | 定时器、候选、REST/WS/媒体取消，隐藏恢复、跨项目晚响应及跨标签登出回归；不是全站长稳证明 |
| health 路径正确，取消与真实错误区分 | **通过（本地回归）/生产未验证** | `/video/healthz` 与 `/aiyoloapi` 分离，503/取消/401/403/404/超时门禁覆盖；真实网关未改未测 |

## 5. 安全与模型完整性

116 项后端联合回归全部通过，包括模型目录来源/生命周期/下载/发布/分配契约，以及：

- 2 路受控执行、无等待队列；超时/取消不提前释放仍运行 worker 的额度；无关鉴权请求仍可完成。
- 同次请求重复文件只哈希一次，不跨请求缓存；同大小恢复 mtime 篡改、替换、删除、哈希中变化和最终指纹检查。
- 旧列表校验不替代后续下载/激活/发布的完整检查；每个引用独立检查期望哈希、长度与权限。
- 检查期间登出、降权、成员移除、项目/分配/registry 修订变化丢弃旧结果；跨项目不串数据。
- request/read/worker 关联与白名单日志；不输出敏感输入、路径、异常原文；hashCompleted 不冒充校验通过。
- WS 覆盖缺口的 5 项测试是“确认缺口仍存在”，不是“完整覆盖通过”。

再次运行 `tools/measure_catalog_api.py`：真实 ASGI + 临时 64MiB 合成文件，5 次 catalogMs 为 111.459、59.744、59.583、60.220、59.817；中位 **59.817ms**，每次 hashCalls 均为 **1**。同时调度的无关 auth/status 完成时间中位 14.857ms（包含计划中的 5ms 等待与本机调度，不是纯端点耗时）。冷首轮/样本小/浏览器任务并行影响，不能和历史数字做生产性能推断，也未验收 NFS、内存或 p95。

## 6. 本轮测试结果与复现

| 检查 | 结果 | 证据 |
|---|---|---|
| Vue typecheck | 通过 | `evidence/M32-T30-typecheck.log` |
| 新/修改 E2E 与配置 strict tsc | 通过，最终版本 | `evidence/M32-T30-acceptance-typecheck-final2.log` |
| 全前端单测 | **34 文件 / 298 项通过**，7.09s | `evidence/M32-T30-vitest.log` |
| T22～T26 联合浏览器 + 新分段观测 | **49 通过**，404.529s，0 failed/flaky | `evidence/M32-T30-browser.log`、`M32-T30-browser-results.json` |
| 最终分类/回访缺口/截图目录复验 | **4 通过**，含新增 members 特性测试；其中 3 项与联合运行重复 | `evidence/M32-T30-browser-final.log`、`M32-T30-browser-final-results.json` |
| 既有流/告警业务回归 | **7 通过**，15.2s | `evidence/M32-T30-regression.log`、`M32-T30-regression-results.json` |
| 真实 Cookie/子路径 | **7 通过，3 适用性跳过**，15.6s | `evidence/M32-T30-subpath.log`、`M32-T30-subpath-results.json` |
| 模型/日志/WS 后端联合回归 | **116 通过**，35.663s | `evidence/M32-T30-backend.log` |
| ASGI 64MiB 测量 | 5 样本完成，完整哈希每次 1 | `evidence/M32-T30-catalog-api.log` |
| production / preview 本地 Vite 构建 | 两者通过，仅 `.tmp/m32-t30/` | `evidence/M32-T30-build-production.log`、`M32-T30-build-preview.log` |
| Harness 完成门禁 | **34 项通过**，0.070s，validate/render通过；完成时间23:00:22+08:00 | `evidence/M32-T30-harness-*.log` |

浏览器总计 67 次通过执行，其中 3 次为重复复验，即 64 个不同用例；另有 3 个适用性跳过，不混入通过数量。子路径跳过为 direct 不适用代理 slash 重定向 1 项，模拟生产代理不提供 admin-next 的 2 项；不代表生产验证豁免。

前端 cwd：`E:/aiyolo/server-video-service/admin-web`：

```powershell
npm run typecheck
npm run test
npx tsc --noEmit --target ES2022 --module ESNext --moduleResolution Bundler --strict --skipLibCheck --esModuleInterop --types node,vite/client tests-e2e/request-acceptance.spec.ts tests-e2e/media-optimization.spec.ts playwright.acceptance.config.ts playwright.acceptance-subpath.config.ts playwright.acceptance-regression.config.ts
npx vite build --mode production --outDir ../.tmp/m32-t30/dist
npx vite build --mode preview --outDir ../.tmp/m32-t30/dist-preview
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE='C:/Users/45393/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'
# 重跑先选新的安全 run 名，勿覆盖已有证据。当前完整集已含补充用例，共 50 项。
$env:ADMIN_ACCEPTANCE_RUN='rerun-1'
npx playwright test --config playwright.acceptance.config.ts
# 本轮 final 使用 --grep 'segmented initial|real-clock|detail shares'，4 项。
npx playwright test --config playwright.acceptance-regression.config.ts
npx playwright test --config playwright.acceptance-subpath.config.ts
```

后端 cwd：`E:/aiyolo/server-video-service`：

```powershell
$env:DATABASE_URL=''; $env:RUN_POSTGRES_TESTS='0'
$env:APP_APK_WORKER_ENABLED='false'; $env:APP_APK_EXTERNAL_ENABLED='false'
$env:PYTHONPATH='tests'
.venv/Scripts/python.exe -m unittest test_catalog_telemetry test_catalog_hashes test_catalog_reads test_catalog_read_api test_model_catalog_source test_model_catalog test_model_marketplace_api test_model_version_lifecycle test_model_download test_model_marketplace_automation test_model_marketplace_contract test_project_model_inventory.ProjectModelInventoryApiTests test_project_reporting.ReportingApiTests.test_request_logs_use_server_identity_and_never_raw_input test_project_reporting.ReportingApiTests.test_recent_alert_limit_and_transport_logs_are_safe test_alert_sync_coverage -v
.venv/Scripts/python.exe tools/measure_catalog_api.py
```

## 7. 改动文件和证据保留

以下路径相对 `E:/aiyolo/server-video-service`：

| 文件 | 本轮变化 |
|---|---|
| `admin-web/playwright.acceptance.config.ts`（新增） | 综合套件、隔离 5210、封闭漏拦截代理、独立 run 证据、关闭 trace |
| `admin-web/playwright.acceptance-subpath.config.ts`（新增） | 4210/4211 临时 HTTP、独立构建目录、无数据库/worker |
| `admin-web/playwright.acceptance-regression.config.ts`（新增） | 5212 独立端口，仅选 7 项既有业务回归 |
| `admin-web/tests-e2e/request-acceptance.spec.ts`（新增） | 分段去敏观测、真实 60 秒、总览和成员 A→B→A、缓存未达成特性验证 |
| `admin-web/tests-e2e/media-optimization.spec.ts`（已有未跟踪文件） | 仅两处截图路径改为 `test.info().outputPath`，不再固定写 T26 证据 |
| `docs/admin-request-acceptance-M32-T30.md` | 本报告 |
| `harness/task-state.json`、`harness/TASK_BOARD.md` | 仅 Harness CLI 新增/启动/完成 T30 并 render，不手工修改状态 |
| `harness/records/M32/M32-T30.md` | CLI 完成记录及如实风险补充 |

证据为 `evidence/M32-T30-*`，浏览器目录 `admin-web/test-results-m32-t30*`。未覆盖既有 `admin-web/dist`/`dist-preview`；构建不是 Docker。

**证据保留偏差：**第一次复用媒体测试时，其中两处原有固定截图路径在 22:50:52 重写了 `evidence/M32-T26-detail-desktop.png` 与 `evidence/M32-T26-detail-narrow.png`。发现后立即改用本次测试输出目录并复验；最终新截图在 `admin-web/test-results-m32-t30-final/`。两张旧截图未被 Git 跟踪，不能声称其原始字节已保留或已经恢复；T26 其他日志、JSON、报告未改。本轮没有删除文件，也没有用新截图冒充原 T26 运行证据。

已有产品/测试脏改、模型 registry 修改及模型删除均未清理、覆盖或提交。HEAD 为 `889b60fb3cfad0414c1994dcbad2388192d300ec`，索引为空；最终复核写入 `evidence/M32-T30-harness-final.log`。

## 8. 遗留问题与下一任务建议

1. 普通列表五秒回访复用尚未普遍实现；members 已实测重读。**建议下一任务为 M32-T31（待定义/批准）：普通管理列表短期查询复用与安全失效**。先限定成员/平台项目等明确页面，以账号、项目、权限修订、查询参数隔离；保留写前后及撤权失效、取消与并发边界。任务未新增、未启动，本轮不改产品。
2. 项目静态页 20/min 而不是 10/min；WS 过滤/丢失/跨 worker/结束状态缺口仍在，可靠补偿不得改为 30 秒。WS 协议补齐属于另一个独立任务，不和列表缓存混做。
3. 尚未对原方案的每一个页面做完整三段 Network 取证；系统/项目知识筛选、App 版本配置缓存、空流页降频等建议未由本轮宣称实现。总览静置仍 38/min，本次主要减少切换与无用候选读取。
4. 没有生产抓包、真实摄像机/业务图片、上传转换 worker、真实数据库/NFS、Linux、多 worker、TCP 断连及长稳验证。不能声称历史超时、502 或内存问题已解决。
5. 后端每进程两路额度、不可强杀阻塞 I/O、非事务文件指纹以及同步日志器可能堵塞/丢日志的边界保留；仅接入的读路径得到受控执行，不代表所有接口已异步化。
6. 浏览器仍出现已有 Element Plus 数字属性传入字符串的 Vue 警告；未扩大到 UI 修复。既有回归未 mock WS 时连接被隔离代理拒绝（`127.0.0.1:1`），不会连接真实服务，相关 7 项不作为 WS 成功验证；WS 由独立 7 项浏览器及 5 项后端测试验证其现状。
7. 单测既有代理取消输出 ECONNRESET；npm home/sass_binary_site 废弃提示、色彩环境警告与 Starlette/httpx 警告仍保留，所有断言/退出码均成功。两张 T26 截图覆盖偏差见上节，不以“全部已有成果未动”掩盖。
8. 任何后续提交/推送、Docker 构建导出或生产变更必须分别授权并走 Git 优先发布流程。本任务不执行 `accept-major M32`，不自动启动下一个任务。
