# M32-T25 共享查询与候选按需加载

日期：2026-11-09（Asia/Shanghai）。任务：M32-T25。仅本地代码、测试和证据；未构建/导出 Docker，未部署，未修改数据库、开发服务器、生产环境、Nginx/K8s，未 stage/commit/push/reset/clean。M32-T26 不在本次范围内。

## 基线与任务绑定

- 继续已启动的 M32-T25（owner codex），依赖 M32-T24 已完成；没有重复启动或手改 Harness 状态。
- 已阅读工作区 AGENTS、服务端 README、Harness README/任务定义、ADR-004、Git 优先发布流程及工作区请求优化方案。未涉及 Android 工程。
- Git HEAD：`889b60fb3cfad0414c1994dcbad2388192d300ec`。开始时索引为空，工作区存在前序请求优化及其他任务的源码、测试、模型文件改动；全部保留。本报告只列 T25 贡献，不把整个脏工作区归入本任务。
- T22 稳定导航/权限验证、T23 自适应轮询、T24 断线对账已存在，未重复实现。T24 的 WS 全量覆盖缺口仍存在，继续保留 5 秒 REST 补偿，未启用 30 秒降频。

## 实现

1. 总览与看板共用页面内存 ReadCache，TTL 为响应完成后 10 秒，已完成缓存最多 32 条；相同 key 在途合并、返回独立快照。key 包含账号/角色、平台或项目上下文、scope generation、项目和成员修订、能力集合及查询参数。不缓存身份裁决，不写 localStorage/sessionStorage。
2. 切统计周期只请求该周期统计，streams/recent 独立。切换布局按缓存剩余 TTL 继续刷新，不额外延长快照寿命；手动刷新明确失效并重读。保留 recent `limit=20` 权威查询，不截取不完整的全局 WS 列表冒充完整窗口。
3. 消费者独立取消；最后一个消费者离开取消底层请求。scope 清理全部缓存/显示，失效前发出的迟到结果不回填。预期取消不显示业务失败。
4. JSON/二进制/XHR 写请求开始和结束均定向失效，失败或结果不确定也失效，不自动重放写操作。告警写清 stats/recent；流、模型、分配、场景、规则写清 stats/streams。当前是标签级定向失效，不是跨页数据订阅框架。
5. 平台项目创建/成员添加才读取 accounts；编辑/移交保留页面已有必要字段。普通负责人仍按原授权填写账号 ID，不披露全平台账号。规则绑定弹窗才读来源；可见审计仍首屏读取。
6. 场景列表不预取项目模型，详情、编辑、成员配置、审核需要时读取。模型分配弹窗每次打开重读 available。项目模型首屏仍读 models+assignments；若停用分配缺少模型元数据，保留 available 补全名称、状态和产物信息，不盲删这次必需查询。
7. 候选为表单局部数据，关闭、撤权和卸载时取消/清除；错误可显式重试。加载/失败时不能提交依赖候选的表单，也不误报“没有账号”“模型已停用”。候选不是授权结果，版本冲突、服务器权限与模型完整性门禁保留。

## 测试与实际请求计数

方法：真实本地 Chromium 执行前端代码，API/WS 路由指向隔离 fixture；计数来自实际浏览器请求，不是源码推算。权限变化、503、迟到响应和写操作均由测试 fixture 注入，不接触真实业务库。快速导航/TTL 边界采用 Playwright 或 Vitest 虚拟时钟；60.5 秒稳态项明确使用墙钟。没有优化前同条件抓包，不将源码估算当作实测基线。

| 场景 | 验证结果 |
|---|---|
| 总览→看板→7d→总览，10 秒内 | today 统计 1、7d 统计 1、streams 1、recent 1；切布局和回切未重复读，切周期仅新增统计 |
| 手动刷新 | 当前周期统计、streams、recent 各增加 1 |
| 60.5 秒总览静置 | 统计、streams、recent 各增加 6；me/projects 各增加 4；保留原实时性/撤权检测频率 |
| 平台项目/成员首屏 | accounts 均 0；对应添加/创建弹窗首次打开才变为 1 |
| 规则首屏 | 来源候选 0，可见审计 1；绑定弹窗来源候选增加 1 |
| 场景/空项目模型首屏 | 场景 models 0；项目模型 available 0；打开相关弹窗各增加 1 |
| 停用分配缺少列表元数据 | available 1；仍显示停用项名称及真实目标端状态，不退化为“状态未知” |
| fixture 场景写后返回总览 | stats/streams 各变为 2，recent 仍为 1；仅一次 PATCH，统计显示更新后的 44 |
| 撤权/跨项目 | 候选请求 ERR_ABORTED、弹窗消失；A 的迟到统计不覆盖 B，重入 A 发起新读 |

测试状态：

- Vue/TypeScript typecheck 通过；新增 Playwright 文件独立 strict TypeScript 检查通过。
- Vitest：33 文件、289 项通过；覆盖缓存隔离/TTL/并发/取消/迟到、写前后失效（200/503 与 XHR）、候选生命周期及已有功能。
- 综合浏览器套件：37 项全部通过（5.1 分钟，T22/T23/T24 回归 26 + T25 新增 11），零失败、零 flaky；包含四组真实 60 秒级计时场景。
- `/admin/`、`/admin-next/` 两套隔离本地 Vite 构建通过，输出 `.tmp/m32-t25/`，未覆盖既有 dist。
- Cookie/子路径浏览器：7 通过、3 适用范围跳过；独立 4201/4202 端口及隔离内存账户，未读取应用数据库。
- 模型完整性：4 项通过，覆盖完整来源、产物缺失、SHA-256 不匹配、必需元数据缺失；临时目录测试。未修改 `app/model_catalog.py`、`app/main.py` 的校验逻辑。
- Harness 完成门禁：2026-11-09 19:27:29 +08:00 CLI complete 成功；Harness 单元测试 34 项通过，validate/render 通过。T26 仍 pending；最终 HEAD 未变、索引为空。

初次浏览器 6 通过/2 失败：测试冻结了 Element Plus 关闭动画，以及撤权后未执行“重新验证项目”的既有门禁流程。已修正测试交互（不 force click、不放宽权限）；针对性复测通过，最终完整重跑另存日志。单测中既有代理取消场景输出两条 ECONNRESET，但 289 项全部通过；npm 仍提示本机 home/sass_binary_site 配置项将来废弃，未改用户配置。

## T25 改动文件

以下路径均相对 `E:/aiyolo/server-video-service/`：

产品（9）：

- `admin-web/src/api/readCache.ts`（新增）：10 秒内存缓存/并发合并/失效。
- `admin-web/src/api/client.ts`：写前后缓存失效；保留此前权限与 health 修复。
- `admin-web/src/features/dashboard/useDashboard.ts`：共享数据、周期拆分、剩余 TTL 和取消。
- `admin-web/src/features/management/useCandidates.ts`（新增）：局部候选加载/清除。
- `admin-web/src/features/management/PlatformProjectsView.vue`：负责人候选懒加载。
- `admin-web/src/features/management/MembersView.vue`：添加成员账号候选懒加载。
- `admin-web/src/features/operations/RulesView.vue`：绑定来源按需读取。
- `admin-web/src/features/models/ProjectModelsView.vue`：按需候选及必要元数据 fallback。
- `admin-web/src/features/scenes/ScenesView.vue`：模型候选按可见用途读取。

测试（6）：

- `admin-web/tests/read-cache.test.ts`（新增）。
- `admin-web/tests/candidates.test.ts`（新增）。
- `admin-web/tests/dashboard.test.ts`（扩展）。
- `admin-web/tests-e2e/shared-queries.spec.ts`（新增）。
- `admin-web/playwright.shared-queries.config.ts`（新增）。
- `admin-web/playwright.shared-queries-subpath.config.ts`（新增）。

记录：本报告、CLI 维护的 `harness/task-state.json` / `harness/TASK_BOARD.md`、`harness/records/M32/M32-T25.md`；上述状态文件未手工改写。

证据（均位于 `evidence/`）：`M32-T25-typecheck.log`、`M32-T25-e2e-types.log`、`M32-T25-unit-final.log`、`M32-T25-browser-initial.log`、`M32-T25-browser-final.log`、`M32-T25-browser-results.json`（含去敏请求计数/资源耗时附件）、`M32-T25-build.log`、`M32-T25-build-preview.log`、`M32-T25-subpath.log`、`M32-T25-model-integrity.log`、`M32-T25-complete.log`、`M32-T25-harness-tests.log`、`M32-T25-harness-validate.log`、`M32-T25-harness-render.log`。

## 未解决问题与边界

- 未做生产 Network/HAR、响应字节、p95、CPU/NFS 或真实模型负载压测；本地 fixture 请求减少不证明历史 502/超时/内存问题已解决。
- 10 秒内存快照是有界短缓存，不是实时事件流；候选每次打开重取，写操作仍由服务器裁决。内存缓存仅试点总览/看板，不宣称所有列表都已缓存。
- 总览静置频率没有降低；本任务消除导航/切周期/未打开表单的冗余请求。账号列表、模型校验每次必要读取的单次成本未优化。
- WS 不具备完整变更覆盖，继续 5 秒补偿；降为 30 秒仍需单独补齐协议与验收。证据图片/视频预览控制属于 M32-T26，本次未实现。
- 未运行连接真实数据库的全量服务端集成/多 worker/视频长稳测试；模型校验仅本地针对性回归，不宣称三端发布验收完成。
- 工作区原有改动（含模型文件删除、转换及数据库测试等）未整理或提交；部署必须后续按 Git 优先流程另行授权。
