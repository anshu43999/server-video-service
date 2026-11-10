# M32-T24 告警同步与断线补偿优化

日期：2026-11-09（Asia/Shanghai）。仅本地代码、测试和验收证据。任务依赖 M32-T23；M32-T25/T26 未启动。

## 结论与降频门禁

**WS 全量事件覆盖验收不通过，未启用正常连接时 30 秒 REST 补偿。** 保留默认 5 秒补偿；不是把测试通过冒充覆盖完整。新增后端测试通过，意味着成功复现下列缺口：

1. management 订阅仍在线时，禁用投递、移除 management 通道或提高最低严重级别，均可使已存储告警不进入 WS。
2. 订阅队列有界，队列满时丢弃旧项，无丢失标记。
3. 断线期间事件不向新订阅重放；必须 REST 对账。
4. 订阅仅在进程内；另一 worker 的订阅收不到此进程投递。此项为两个真实通道实例的隔离测试，并非已部署多 worker 实测。
5. ServerAlertRuntime 广播 CONFIRMED，但 ENDED 转换只持久化、不再次广播。

另经源码检查，app/main.py 的 _dispose_alert 只返回处置结果，没有向其他浏览器广播；前端增加 REST 恢复 ENDED/ACKNOWLEDGED 的回归测试。不改变投递策略含义，不绕过过滤，不扩展为后端跨进程事件总线。

## 本次实现

- AlertSync：断线（open → backoff/offline/stopped）立即请求 REST；握手及重连 open 立即对账。终止性 4401/4403/4404/4429 不触发补偿，停止同步并保留既有权限失效处理。
- 将固定 setInterval 改为读取结束后单次定时：默认等待 5 秒，再读取。断线/重连触发立即核对时重置旧定时，避免刚对账完又被旧定时重复读取。该 5 秒不含网络响应耗时，不保证网络拥塞下墙钟每 5 秒完成。
- 同步器在途读取单飞；若断线/重连发生在旧快照读取期间，合并为旧读取结束后一次新的对账，不能只复用旧 Promise 而错过窗口。多次状态抖动合并为一个待补偿标记。
- 回调/微任务核对代次；stop/权限清理后不再启动读取，旧连接终止回调不能关闭新代次。已有 API scope 取消、store 响应代次隔离、消息去重保持。
- 15 秒权限核验、模型完整性和发布校验均未修改。不暂停隐藏页告警提醒，不增加缓存、写重放、数据库/协议或部署改动。

## 测试与测量边界

所有浏览器计数来自真实本机 Chromium、真实前端与隔离 API/WS fixture，不是生产 Network/延迟，也不是纯源码推算。墙钟与虚拟时钟分开标记。后端覆盖测试执行实际 delivery/store/runtime 实现，显式内存存储，无 app.main lifespan 或数据库连接；既有证据存储测试只使用临时目录/内存对象。

| 场景 | 已验证结果 |
|---|---|
| 正常 WS，真实静置 60.5 秒 | alerts 增量 12；auth/me、auth/projects 各 4；WS 连接 1；业务写入 0。加上初始化及握手，alerts 总计 14。没有宣称稳态降频收益 |
| 真实断线/重连 | 立即恢复漏报且重连重放不重复通知；首轮本地 fixture 52ms，最终整套 41ms，不代表生产 SLA，也没有旧版同场景实测对照 |
| 旧 REST 在途时重连（虚拟时钟） | 旧请求期间仍仅 1 次读取；释放后追加 1 次新读取并显示旧快照没有的事件 |
| WS 健康但漏消息、REST 临时 503 | 5 秒补偿恢复事件，错误恢复后通知一次 |
| 成员权限变化 | 浏览器观测 net::ERR_ABORTED；晚到旧响应不显示，待补偿不复活 |
| WS 4403、项目 A/B 切换 | 停止旧同步；错项目 WS 与旧列表不泄露 |

首轮新增浏览器场景 7 项通过（evidence/M32-T24-browser-initial.log）。最终整套浏览器 26 项通过（4.6 分钟），无失败、无 flaky、无跳过；包括前两批 19 项回归与本次新增 7 项。证据：evidence/M32-T24-browser-final.log、evidence/M32-T24-browser-results.json。此前转换 idle jobs=2/60.5s、models=0、push status=2/60.5s、policy=0 的改善仍保持。

### 其他已执行测试

- Typecheck：通过，evidence/M32-T24-typecheck-final.log。
- 新增浏览器脚本/配置单独严格类型检查通过，evidence/M32-T24-e2e-typecheck-final.log。首次独立检查发现 fixture 的字面量类型过宽及命令缺少 vite/client 声明，修正 fixture 来源类型并显式加载声明；初次失败保留在 M32-T24-e2e-typecheck.log，不是产品运行失败。
- Vitest：31 文件、272 项通过（较 T23 增加 12 项），evidence/M32-T24-unit-final.log。包含原有权限、项目、账号、模型、轮询保护；其中断线发生在第 4.9 秒的测试确认第 5 秒不会再被旧定时重复触发。
- 后端：25 项通过，其中新增覆盖缺口测试 5 项，evidence/M32-T24-backend.log；独立覆盖测试 evidence/M32-T24-coverage.log。
- Cookie/子路径：7 通过、3 适用范围跳过，evidence/M32-T24-subpath.log。跳过分别为 direct 不适用的代理重定向断言 1 项及子路径代理未暴露预览入口 2 项。使用本地真实认证 handler 与内存存储，未连接环境数据库。
- 本地 production/preview 前端构建通过，evidence/M32-T24-build-production.log 和 M32-T24-build-preview.log；仅输出 .tmp/m32-t24/dist、dist-preview，不覆盖其他任务产物，不是 Docker 构建。
- Harness 单元测试 34 通过，evidence/M32-T24-harness-tests.log。
- 完成后 Harness 单元测试再次 34 通过，validate/render 通过；见 M32-T24-harness-complete-tests.log、M32-T24-harness-final.log、M32-T24-harness-render.log。fixture 类型修正后撤权/跨项目两项再跑通过，M32-T24-fixture-final.log；未改变产品实现。

原有代理单元测试输出两条 ECONNRESET，但全套断言和退出码通过；npm 用户配置 home/sass_binary_site、颜色与换行警告未调整。未下载依赖或浏览器。

## 本次改动文件

- admin-web/src/features/alerts/sync.ts：唯一产品实现修改。
- admin-web/tests/alert-sync.test.ts：同步与恢复单元回归；保留原 8 项。
- tests/test_alert_sync_coverage.py：5 项真实后端行为缺口测试。
- admin-web/tests-e2e/alert-sync-optimization.spec.ts：7 项真实浏览器场景和请求计数。
- admin-web/playwright.alert-sync.config.ts：独立 Vite 5194，合并第一批/轮询/告警回归，不覆盖 T22/T23 配置。
- admin-web/playwright.alert-sync-subpath.config.ts：独立 Cookie/子路径验收 4199/4200。
- 本报告、evidence/M32-T24-* 证据，以及 Harness CLI 维护的任务状态、任务板和记录。

原有脏工作区保留；本次不修改 app/ 后端产品代码、权限、模型或部署文件。

完成记录：harness/records/M32/M32-T24.md。本任务完成含义是完成覆盖核验与允许范围内安全恢复，不表示 WS 覆盖通过或 30 秒降频交付；后续降频需要新的已批准范围。HEAD 保持 889b60fb3cfad0414c1994dcbad2388192d300ec，索引为空。

## 复现

服务端工程目录 E:/aiyolo/server-video-service：

    $env:DATABASE_URL=''
    $env:PYTHONPATH='tests'
    .venv/Scripts/python.exe -m unittest test_alert_sync_coverage test_alert_delivery test_alert_disposition test_server_alert_runtime -v
    python -m unittest discover -s harness/tests -p 'test_*.py'

前端目录 E:/aiyolo/server-video-service/admin-web：

    npm run typecheck
    npm run test
    $env:PLAYWRIGHT_CHROMIUM_EXECUTABLE='C:/Users/45393/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'
    npx playwright test --config playwright.alert-sync.config.ts --output test-results-m32-t24-final
    npx vite build --mode production --outDir ../.tmp/m32-t24/dist
    npx vite build --mode preview --outDir ../.tmp/m32-t24/dist-preview
    npx playwright test --config playwright.alert-sync-subpath.config.ts

## 未解决与边界

- 30 秒降频不交付：需单独定义完整变更流、丢失可检测/补偿及跨 worker 一致性方案，再验证后决定；不能只看 socket=open。
- 未进行生产压测、真实告警端到端性能/长稳、多 worker 部署测试；本地 fixture 延迟不能推导生产改善。
- 浏览器取消不代表服务端处理必然终止。同步器 stop 保留原 API scope 取消职责，不取消其他页面共享读取。
- 未构建/导出 Docker，未改开发服务器、生产、数据库、Nginx、K8s，未暂存、commit、push、reset 或 clean。
- M32-T25/T26 保持 pending；本次不提前实现共享查询、图片/预览优化。
