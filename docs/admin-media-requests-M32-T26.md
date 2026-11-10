# 管理后台证据图片与预览请求控制（M32-T26）

日期：2026-11-09（Asia/Shanghai）。任务：`M32-T26`，依赖已完成的 `M32-T25`；用户确认继续后于 19:28:55 +08:00 通过 Harness CLI 绑定，owner `codex`。

## 范围与安全边界

- 依据 `E:/aiyolo/docs/admin-request-analysis-20261109.md` 和 Harness 的 T26 定义，控制证据图片、详情/原图及 PC 同源 JPEG 预览请求。未重新实施 T22–T25。
- 仅本地产品代码、测试、任务记录和证据；两套 Vite 构建仅用于本地验收，输出 `.tmp/m32-t26/`。没有构建/导出 Docker，没有修改开发服务器、生产、数据库、Nginx 或 K8s。
- 未 stage/commit/push/reset/clean。开始 HEAD 为 `889b60fb3cfad0414c1994dcbad2388192d300ec`，索引为空；保留原有转换、模型文件、测试及此前请求优化改动。最终状态另在本报告完成门禁处确认。
- 权限撤销复核、项目代次隔离、旧请求取消、同源鉴权及模型完整性校验保留；告警 WS 仍不具备完整变更覆盖，继续 **5 秒 REST 补偿**，不启用 30 秒降频。

## 实现

### 证据图片

- 缩略图以 IntersectionObserver 和标签页可见性决定加载，不预读视口外图片；详情仅在打开且图片区域可见时读取。无 IO 的环境降级可见，不会因此无法展示证据。
- 缩略图、详情及原图共享标签页内的 **3 路未结算请求额度**。取消排队项即移除；底层传输忽略 abort 时，槽位保留至实际 settle，防止取消/重开造成无限重叠。
- 图片身份包含项目、事件和证据元数据；同内容列表刷新不重复读取，版本变化会刷新缩略图。详情原图版本选择、采集标注、处置备注及 AI 建议逻辑保留。
- 离开可见区域、标签页隐藏、卸载或权限/project scope 清理时取消请求、释放 Blob URL，迟到响应不恢复旧图片；observer 的旧目标和卸载后回调被忽略。
- 不增加图片缓存或持久化。重新滚回/显示时重新读取，以释放私密图片和内存为优先；不宣称来回滚动总请求数一定下降。

### PC 预览

- 每帧解码成功后间隔 200ms 请求下一帧，单实例最多一个未结算 fetch；慢解码期间不继续获取即将丢弃的帧。
- 204、503 等暂时失败、坏 JPEG/解码失败采用 500/1000/2000/5000ms 上限退避，成功解码后重置。请求或解码 5 秒超时清除旧画面，不把旧图标成实时。
- 标签页隐藏、预览离开视口或 offline 时暂停并释放图片；恢复时仅发起一次新读取。重复 online/visibility 信号不会绕过帧率和退避定时。
- 401/403/404 停止该预览并触发既有权限复核，不自动重试终态拒绝；换项目/源后旧响应不回填。
- StreamsView 和 StreamTile 接入相同生命周期。当前正式 Dashboard 未使用 StreamTile，因此不宣称已实测当前大屏四路并发预览。

## 实测及解释

使用真实本地 Chromium、真实 PNG 与 canvas 生成的 160×90 JPEG；业务 API/WS 是隔离 fixture，不连接生产或真实摄像机。以下不是方案中的源码推算，也不是生产负载基准。

| 场景 | 观察结果 | 能证明的改善/边界 |
|---|---|---|
| 10 条带图告警，1400×1000 视口 | 初始读取 9 张可见图，第 10 张滚动后读取 | 未访问的视口外图片不预取；不是所有分辨率固定减少 1 张 |
| 证据请求挂起，随后打开详情/原图 | 同时最多 3 路，队列等待 | 缩略图和详情共用额度；不代表远端收到取消后计算立即停止 |
| 真实 10.1 秒有效预览窗口 | 45 次新读取 | 本地运行低于 5fps 上限；不做视频画质/生产延迟推断 |
| 随后真实 10.1 秒无帧窗口 | 4 次新读取 | 等待期退避有效，旧图清除；不是与历史源码估算做百分比比较 |
| 隐藏、离页、撤权、切项目 | 浏览器请求取消，图片/详情清理，旧项目响应不回填 | 保留权限隔离与取消语义 |
| 503 与坏 JPEG | 自动恢复并重新解码显示；403 停止 | 暂时故障与授权终态分开处理 |
| 桌面及 390×844 详情 | 图片和标注可读，无横向溢出，原图版本接口读取成功 | 已目视两张截图；截图内容/标注是测试夹具，不代表真实检测准确性 |

这些计数来自已运行的媒体用例；最终全套重跑的 JSON 和日志是交付时的可定位证据。没有同条件旧版本 A/B 测试，不宣称百分比性能提升。

## 测试结果

- Vue typecheck：通过。
- 新增 e2e 与三份配置的独立 strict TypeScript 检查：通过（`--types node,vite/client`）。
- Vitest：**34 文件、298 项通过**，含新增媒体/可见性 9 项；备注、AI 建议、原图选择既有用例保留。
- 既有媒体业务浏览器回归：**7 项通过**，覆盖未保存设置、切源取消、重连、无帧、空告警、列表失败、并发处置冲突。
- 两套本地隔离 Vite 构建：通过；Cookie/子路径 **7 通过、3 适用范围跳过**。跳过项是 direct 项目不适用前缀跳转，以及生产代理 fixture 不暴露 `/video/admin-next/` 的两项，非通过。
- 模型完整性：**4 项通过**，临时目录覆盖完整来源、缺产物、SHA-256 不匹配、缺必需元数据。未修改模型校验逻辑，也未连接数据库。
- 综合浏览器最终重跑（T22–T25 37 项 + T26 10 项）：**47 项全部通过，8.2 分钟**；最终 JSON 为 expected 47、unexpected 0、skipped 0、flaky 0。
- Harness complete 于 **2026-11-09 19:57:49 +08:00** 成功；随后 Harness 单测 **34 项通过**，validate/render 通过。

### 失败与修正记录

- 初次全单测 287 通过、2 失败：happy-dom 无真实布局，不派发 IntersectionObserver；为原有可见详情用例显式模拟 intersection。另修正测试重复使用已消费 Response body 的问题；没有删除原图/备注断言。
- 测试类型检查发现可选 fetch init、fixture 生命周期字符串/修订类型问题，已给测试项目夹具使用明确 AccessibleProject 类型；独立 tsc 的 Vite 环境类型参数已补齐。
- 首次综合浏览器 **46 通过、1 失败**：撤权后的图片/详情已移除，但后续权威复核将瞬时文案替换为项目选择页。测试改为验证“尚未进入项目”、详情/行/图片清空及 pending 请求取消等持久安全结果，而非依赖瞬时文案；未改变权限逻辑。原失败日志/JSON/trace 保留。
- 单测代理取消场景仍输出两条 `ECONNRESET`，测试通过；本机 npm `home` / `sass_binary_site` 配置项警告及 `NO_COLOR` 提示保留，未修改用户环境。

## T26 改动文件

### 复现命令

在 `E:/aiyolo/server-video-service/admin-web` 执行：

```powershell
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE='C:/Users/45393/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'
npm run typecheck
npx tsc --noEmit --target ES2022 --module ESNext --moduleResolution Bundler --strict --skipLibCheck --esModuleInterop --types node,vite/client tests-e2e/media-optimization.spec.ts playwright.media.config.ts playwright.media-regression.config.ts playwright.media-subpath.config.ts
npm run test
npx playwright test --config playwright.media.config.ts --output test-results-m32-t26-final
npx playwright test --config playwright.media-regression.config.ts
npx vite build --mode production --outDir ../.tmp/m32-t26/dist
npx vite build --mode preview --outDir ../.tmp/m32-t26/dist-preview
npx playwright test --config playwright.media-subpath.config.ts
```

模型校验在服务端工程根目录执行 `.venv/Scripts/python.exe -m unittest discover -s tests -p test_model_catalog_source.py -v`。上述服务仅监听本地独立测试端口；没有启用数据库测试。

### 文件清单

以下均相对 `E:/aiyolo/server-video-service/`；并非工作区全部脏文件清单。

产品（8）：

- `admin-web/src/api/useVisibleElement.ts`（新增）：视口和标签页可见性、旧回调防护。
- `admin-web/src/features/alerts/evidenceRequests.ts`（新增）：共享三路队列/取消/项目代次校验。
- `admin-web/src/features/alerts/EvidenceThumbnail.vue`（新增）：可见缩略图加载和 Blob 释放。
- `admin-web/src/features/alerts/AlertsView.vue`：整页 eager 缩略图加载替换为独立可见组件。
- `admin-web/src/features/alerts/AlertDetailDialog.vue`：详情/原图共用额度与可见性生命周期。
- `admin-web/src/features/streams/preview.ts`：帧率、解码背压、退避、超时、暂停和单飞。
- `admin-web/src/features/streams/StreamsView.vue`：视口暂停与失败恢复状态。
- `admin-web/src/features/dashboard/StreamTile.vue`：相同可见性和解码失败控制。

测试及测试配置（6）：

- `admin-web/tests/media-requests.test.ts`（新增，9 项）。
- `admin-web/tests/alert-advice-dialog.test.ts`（适配可见布局模拟）。
- `admin-web/tests-e2e/media-optimization.spec.ts`（新增，10 项）。
- `admin-web/playwright.media.config.ts`（综合 47 项）。
- `admin-web/playwright.media-regression.config.ts`（既有业务 7 项，不覆盖历史截图）。
- `admin-web/playwright.media-subpath.config.ts`（独立端口/构建目录）。

记录：本报告；Harness CLI 维护 `harness/task-state.json`、`harness/TASK_BOARD.md` 与 `harness/records/M32/M32-T26.md`，不手改状态绕过门禁。

证据均在 `evidence/`：`M32-T26-typecheck.log`、`M32-T26-e2e-types.log`、`M32-T26-unit-final.log`、`M32-T26-browser-final.log`、`M32-T26-browser-results.json`、`M32-T26-browser-first-full.log/json`、`M32-T26-browser-regression.log`、`M32-T26-build.log`、`M32-T26-build-preview.log`、`M32-T26-subpath.log`、`M32-T26-model-integrity.log`、`M32-T26-detail-desktop.png`、`M32-T26-detail-narrow.png`。初次定位日志亦保留。

## 未解决问题与验收边界

- 没有生产 Network/HAR、响应字节、p95、CPU/NFS、真实摄像机或视频长稳测试；未证明历史 502/超时/内存问题已解决。
- 图片离开视区即释放，重新进入会重读；没有共享已解码图片或跨页图片缓存。浏览器不支持 IntersectionObserver 时降级可见加载，仍保留三路额度。
- 共享额度是标签页内证据请求限制，预览单飞是每实例限制；不宣称跨标签/跨浏览器/服务端全局限流。
- 若底层传输永久不 settle，即使忽略 abort 也不放开并发槽位，牺牲可用性以避免无界重叠；标准浏览器 fetch 的 abort 场景已验收。
- WS 覆盖不足继续保留 5 秒补偿；后端查询、模型校验单次成本和其他第三批优化未进入本次范围。
- 工作区其他既有脏改未整理或提交；部署需另行授权并遵循 Git 优先发布流程。本任务不等同三端发布验收。

## 完成门禁

- Harness `M32-T26` 状态已为 `completed`，记录 `harness/records/M32/M32-T26.md`。仅完成当前小任务，没有启动第三批或执行大任务发布验收。
- complete 后 Harness 34 单测、validate/render 均通过；日志为 `evidence/M32-T26-complete.log`、`M32-T26-harness-tests.log`、`M32-T26-harness-validate.log`、`M32-T26-harness-render.log`。Harness 单测输出的 M00 Deployment task 是测试临时夹具，不是启动真实部署任务。
- 最终 Git HEAD 仍为 `889b60fb3cfad0414c1994dcbad2388192d300ec`，索引为空；本次产品/测试 tracked 文件 `git diff --check` 通过。包含 Harness 生成任务板时，`TASK_BOARD.md:367` 的 Markdown 双空格换行触发 trailing whitespace；未手改生成任务板或扩展修改 renderer。Git 另有既有 CRLF 转换提示。原有脏改和模型删除状态保留，未整理他人改动。
