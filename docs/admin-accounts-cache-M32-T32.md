# M32-T32 平台账号列表短期复用与安全失效

日期：2026-11-10（Asia/Shanghai）。依赖 M32-T31，经用户批准后通过 Harness CLI 新增并于 09:00:55+08:00 启动。实际工程为 E:/aiyolo/server-video-service；本轮只扩展平台账号列表，不是全站缓存或 M32 大任务验收。

## 1. 实施结论与范围

产品只修改 admin-web/src/features/management/AccountsView.vue：引入既有 useManagementReadContext('platform')，以 platform-accounts 标签接入 useManagement 的可选缓存，初次挂载由 refresh 改用 loadInitial。显式刷新按钮仍调用 refresh；账号创建/更新、当前账号变更后的权限复核和密码清除逻辑均保留。

没有重新实现缓存、API 客户端、权限监控或后端接口。T31 已有管理写前后失效包含 platform/accounts，故直接复用，不添加重复失效层。公共机制由新增定向单测和既有回归验证。

- 缓存仅标签页内存、TTL 10 秒，复用现有最多 32 个已完成条目的上限。key 包含账号、角色、会话、scope/generation、权限项目快照与业务标签；无跨身份共享。
- 10 秒是读取复用期限，不是定时刷新频率；长期停留仍靠显式刷新、后续过期读取或权限修订触发。其他人的账号元数据变更可能短暂未显示，列表不作为权限裁决依据。
- 显式刷新重新读取；账号写前后（成功、409、5xx、网络不确定等）使相关列表缓存失效。写入不自动重放；不确定结果须刷新核验。
- 旧读取消、最后消费者释放、序号/generation/context 晚响应检查、撤权清空保留。当前账号降权/停用成功仍调用 projects.revalidate(true)，不继续使用旧列表。
- 密码属于局部表单，不作为缓存输入；提交成功/失败、关闭弹窗和卸载时继续清除。只缓存列表 GET DTO，不缓存创建账号的写响应。新增测试用合成字段证明写响应不会流入读缓存。
- 候选账号仍按需并每次打开读取，不用账号页短期缓存替代负责人候选的最新结果。权限 15 秒、告警 REST 5 秒及模型完整性校验均未修改。

## 2. 测试结果

| 检查 | 结果 | 证据（相对工程根目录） |
|---|---|---|
| 改动前组件基线 | 9 项：6 通过、3 个预期缺口失败 | evidence/M32-T32-accounts-baseline.log |
| 接入后定向单测 | 44 项通过 | evidence/M32-T32-unit-initial.log |
| 最终全前端单测 | 36 文件、327 项通过，16.47 秒；新增账号测试 12 项 | evidence/M32-T32-unit-final.log |
| Vue 和严格 E2E TypeScript 检查 | 通过 | evidence/M32-T32-typecheck-final.log、M32-T32-e2e-types-final.log |
| 最初账号浏览器定向运行 | 9 通过、4 个测试选择器错误失败；证据保留 | evidence/M32-T32-browser-focused.log、M32-T32-browser-focused-results.json |
| 最终完整浏览器联合运行 | 72 项通过，567.919 秒，0 failed/flaky | evidence/M32-T32-browser-final.log、M32-T32-browser-final-results.json |
| 真实 Cookie/子路径 | 7 通过、3 适用性跳过，24.827 秒 | evidence/M32-T32-subpath-final-results.json |
| 后端权限、模型、日志和 WS 保护 | 117 项通过，145.506 秒 | evidence/M32-T32-backend.log |
| 本地 production / preview 构建 | 两套通过，仅隔离临时目录 | evidence/M32-T32-build-production.log、M32-T32-build-preview.log |
| Harness 完成门禁 | CLI 于09:21:11+08:00完成；完成后34项通过（0.076秒），validate/render通过 | evidence/M32-T32-complete.log、M32-T32-harness-tests.log、M32-T32-harness-validate.log、M32-T32-harness-render.log |

改动前组件基线确实测得第二次挂载重复 accounts 调用，并未把原方案源码推算当作 Network 实测。另一个基线失败证明尚不存在目标缓存条目。接入后这些测试均变绿。初始浏览器 4 个失败均为精确 label 匹配未命中原生 select，未到写操作；改为弹窗内明确 select 定位后，角色、启停、当前账号降权/停用均已通过。没有为迎合测试而改产品表单或放松安全断言。

## 3. 浏览器实测改善

| 场景 | 已取得的观察 | 边界 |
|---|---|---|
| 账号→平台项目→账号 | 最终联合运行真实 55ms；返回 accounts 额外 0，手动刷新 +1 | 中间项目页自己的项目读取是必要业务，不宣称整个窗口零请求 |
| 同内容 focus 权限复核 | auth/me 正常增加，accounts 不重复 | 不关闭撤权监控换取请求下降 |
| 离开账号页 10.1 秒后返回 | accounts 总 2：首次和到期返回 | 无新增账号列表 timer |
| 创建返回 200/409/503/网络断开 | 每个场景写 1 次、accounts 总 2；短期回访不再新增 | 错误/断开 fixture 有意允许服务器状态已变化，只有 GET 能核验；绝不重放 |
| 修改其他账号角色、启停 | 写 1 次，accounts 总 2，回访仍复用最新版本 | 显式刷新和业务写不会复用旧结果 |
| 当前账号降权/停用 | 追加权威 auth/me，列表和刷新入口移除 | 未将旧缓存继续展示给变化身份 |
| 离页取消慢列表 | 原 accounts 取消 1，返回新读 1，晚响应不恢复 | 取消单独计数，不当作业务失败 |
| 项目负责人候选 | 账号页读 1；进入项目列表不额外读；两次打开创建项目各新读 1 | 候选按需且不被页面缓存替代 |
| 账号页真实静置 60,509ms | 最终增量 accounts 0、me 4、projects 4 | 列表无新增轮询；8 次权限请求保持，不是生产每分钟性能基准 |

未运行优化前版本的生产 A/B 抓包，不报告生产百分比或历史 502/内存问题已解决。请求优化证据来自实际本机 Chromium 加合成 API/WS；并非生产账户或真实服务端性能。

## 4. 环境隔离与证据边界

- Chromium 使用临时 Vite 回环端口 5215，API/WS 全部由用例拦截；漏拦截仅代理到 127.0.0.1:1，不连接已有 8080 服务。trace 关闭，保存去敏路径、次数、合成场景、取消结果和耗时，不保存密码、Cookie、Token、请求体或真实业务数据。
- 子路径为本地临时 HTTP 4215/4216 和隔离构建目录，使用内存账户、真实 Cookie/路由处理；不是实际 Nginx。3 项跳过分别是 direct 不适用代理 slash 重定向，以及代理不提供 admin-next 的两个用例。
- 后端 117 项为既有 116 项模型/权限/日志/WS 回归加 ProjectManagementMemoryTests。显式 DATABASE_URL 为空、RUN_POSTGRES_TESTS=0、APK worker/external 关闭；没有运行需要 SQLite 迁移的 ProjectManagementDatabaseTests，没有连接或修改开发/生产数据库。
- 后端真实 ASGI 与临时模型文件测试保留完整校验、发布/下载/分配、撤权隔离和受控执行。WS 缺口特性测试通过只表示缺口仍被检测，不能据此降低 REST 补偿。
- Vite 产物仅在 .tmp/m32-t32-final/dist 与 dist-preview。未覆盖正式 dist/dist-preview，不涉及 Docker 镜像构建或导出。
- 保留所有基线、失败和最终结果，使用 T32 专用证据名及输出目录，不覆盖 T31 或其他任务证据。

## 5. 改动文件清单

以下路径相对 E:/aiyolo/server-video-service。

| 文件 | 本轮增量 |
|---|---|
| admin-web/src/features/management/AccountsView.vue | 唯一产品文件：接入已有平台上下文和 platform-accounts 标签，挂载用 loadInitial |
| admin-web/tests/accounts-cache.test.ts（新增） | 12 项真实组件/缓存/ApiClient 单测，含密码清除、写响应隔离、三类列表写前后失效 |
| admin-web/tests-e2e/accounts-cache.spec.ts（新增） | 13 项真实 Chromium 验证与请求计数，含真实 60.5 秒静置 |
| admin-web/playwright.accounts-cache.config.ts（新增） | T32 独立端口和 run 证据，联合既有 59 项与新增 13 项 |
| admin-web/playwright.accounts-cache-subpath.config.ts（新增） | 独立临时端口、构建目录及 Cookie/子路径证据 |
| docs/admin-accounts-cache-M32-T32.md（新增） | 本报告 |
| harness/task-state.json、harness/TASK_BOARD.md | 仅 Harness CLI 新增、启动、完成与 render |
| harness/records/M32/M32-T32.md | CLI 完成记录，补充真实风险 |

其他历史脏改及模型删除状态保留，不归为本任务增量。开始 HEAD 为 889b60fb3cfad0414c1994dcbad2388192d300ec，索引为空；最终核对见 evidence/M32-T32-harness-final.log。不 stage/commit/push/reset/clean。

## 6. 复现

前端 cwd：E:/aiyolo/server-video-service/admin-web。重跑请选择未使用的 run 名，并给日志独立文件名。

```powershell
npm run typecheck
npm run test
npx tsc --noEmit --target ES2022 --module ESNext --moduleResolution Bundler --strict --skipLibCheck --esModuleInterop --types node,vite/client tests-e2e/accounts-cache.spec.ts playwright.accounts-cache.config.ts playwright.accounts-cache-subpath.config.ts
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE='C:/Users/45393/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'
$env:ADMIN_ACCOUNTS_RUN='rerun-1'
npx playwright test --config playwright.accounts-cache.config.ts
npx vite build --mode production --outDir ../.tmp/m32-t32-rerun-1/dist
npx vite build --mode preview --outDir ../.tmp/m32-t32-rerun-1/dist-preview
npx playwright test --config playwright.accounts-cache-subpath.config.ts
```

后端沿用 T30/T31 报告列出的 116 项隔离 unittest 集，另加 test_project_management_api.ProjectManagementMemoryTests。Harness 完成后从服务端 cwd 执行单测、validate、render。

最终浏览器 72 项与子路径 7 项共 79 项通过执行，另有 3 项适用性跳过；最初定向运行是重复执行，不重复计入独立用例数量。测试后回环端口 5215/4215/4216 无监听。成员页回访113ms仍无额外members读取；项目静态页60,505ms仍为权限8+补偿12，本轮未以放宽安全监控换取指标。

## 7. 遗留问题

1. 账号列表短期显示快照不是实时账户状态或授权依据；其他页面尚未普遍复用，知识筛选、App 配置、空流页等不在本任务范围。
2. WS 完整性缺口未改；权限15秒、告警5秒保留，项目静态页约20请求/分钟不能宣称降到10。
3. 未验证生产 Network、真实摄像机/转换 worker、数据库/NFS、多 worker、Linux、真实 TCP 断连或长稳；本地通过不代表生产总体验收。
4. 已有 Vue 数字属性警告、测试代理取消 ECONNRESET、npm 配置弃用提示、色彩环境和后端库警告未扩大修复。
5. 未修改开发服务器、生产、数据库、Nginx/K8s，不 Docker、不提交推送。不 accept-major、不自动启动下一任务。任何发布须另获授权并遵循 Git-first 流程。
