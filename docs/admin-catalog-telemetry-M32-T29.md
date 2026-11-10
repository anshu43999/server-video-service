# M32-T29：模型目录校验耗时与安全观测

日期：2026-11-09（Asia/Shanghai）；工程与命令目录：`E:\aiyolo\server-video-service`。

## 1. 授权、范围与现状

- 用户批准定义后，Harness CLI `add → show → start` 绑定 M32-T29，依赖 M32-T28。没有改写 task-state 绕过门禁；任务启动时间见 CLI 完成记录。
- 已读工作区规则、服务端开发规则、Harness、测试隔离约定与原请求优化方案。检查已有 RequestTelemetry：已有服务端生成的 requestId、路由模板、状态及 HTTP 总耗时，因此本次复用它，不重做访问日志。
- 开始时 HEAD `889b60fb3cfad0414c1994dcbad2388192d300ec`，索引为空；保留大量原有前后端、模型、测试、Harness 脏改。在 T27/T28 的未提交实现上增量修改，不将整仓 diff 计作本任务成果。
- 仅三个模型列表入口的观测：全局/兼容项目 `/aiyoloapi/models`、项目 `/models`、项目 `/models/available`。未新增轻量目录、HTTP 响应字段、日志采集服务或配置，不连接数据库/NFS。

## 2. 事件与判读口径

复用 `aiyolo.requests` 日志器及原中间件生成的 UUID；新增事件只记录路由模板，不含实际 projectId/modelId、查询字符串、文件路径或模型摘要。

| 事件 | 发生点 | 字段与含义 |
| --- | --- | --- |
| `catalog.worker.finished` | 工作线程完成目录检查和摘要作用域清理后，在 callable 返回前 | requestId、route、outcome、durationMs，以及完整哈希计数/耗时；不等同 HTTP 成功 |
| `catalog.read.finished` | 目录等待结束，含正常返回前的权威权限复核 | requestId、route、outcome、durationMs；不等同 HTTP 响应已发送 |
| `request.finished`（既有） | ASGI 中间件 finally | HTTP status、completed、durationMs 等原字段不变，按相同 requestId 关联 |

新增 outcome 白名单为 `ok`、`busy`、`timeout`、`cancelled`、`changed`、`denied`、`error`。禁止将异常 message 或任意外部字符串用作 outcome。

哈希统计：

- `hashAttempts`：进入完整 SHA-256 函数的次数，含失败尝试。
- `hashCompleted`：完整哈希函数正常返回次数，**不代表文件与预期哈希一致**，也不代表模型可发布。
- `hashReuses`：同次读取内通过文件变化检查后复用摘要的次数，不是跨请求缓存命中。
- `hashDurationMs`：全部完整哈希调用的墙钟耗时总和，含失败尝试及未知元数据回退重算；不是纯 CPU、磁盘或 NFS 时间。
- worker 的 `durationMs` 包括线程内权限复核、registry/assignment 和文件检查、投影及清理；不含线程提交前等待，也不含该事件自身输出日志的时间。
- read 的 `durationMs` 从进入目录读取封装开始计时，含等待和返回前权限复核；不含此前路由依赖鉴权、响应序列化/发送，以及自身日志输出时间。不得拿这些字段直接相减认定数据库/NFS 耗时。

时序约定：

- 正常：worker 检查结束 → read 结束 → HTTP request 结束。
- 超时：read=timeout，HTTP 返回 503 后，工作线程可能仍在读文件；稍后单独记录 worker 结果，不改写之前的超时为成功。
- 取消：read=cancelled，既有 HTTP 日志可能为 `completed=false`、默认 status=500；这不是已发送 HTTP 500 的证明。线程稍后完成不表示客户端拿到结果。
- 超额：read=busy、HTTP 503，没有伪造 worker 事件或零哈希的“完成”事件。
- worker 检查后撤权：可以出现 worker=ok、read=denied、HTTP 401/403/404，这是正常的返回前安全复核，不是矛盾。
- 入场鉴权在封装前拒绝：仅保留既有 request.finished，不生成未发生的目录检查事件。
- worker 长期卡住或进程被终止时，可能永远没有 worker.finished；没有事件不能解释为零耗时或成功。

## 3. 实现与隐私

- 每次请求创建独立 telemetry 对象，仅传递已规范化 UUID 和路由模板；不在对象中保留 Request、Cookie、Token、响应体或异常。
- 哈希计数位于 T28 单次工作线程的摘要容器中，不全局累计、不跨线程共享；HTTP 侧不读取正在变化的部分计数。清理路径/摘要后保留数字供该次 worker 汇总，随后随请求释放。
- 每个已执行的目录请求最多新增两条汇总事件，不逐文件输出，不为日志建无限队列或额外线程。busy 通常只新增一条；调用前拒绝零条。
- 日志白名单不包含 Cookie/Authorization、密码、签名、模型内容/哈希、本地路径、查询字符串或异常原文；非法 UUID/路由/outcome 被归一化，不原样输出。
- 新增日志输出抛异常时不改变业务结果、撤权逻辑或槽位释放，也不记录带秘密的日志端异常。失败事件可能丢失；这不是可靠审计或持久化投递保证。
- 仍使用已有同步日志器。日志输出端长期阻塞可能延迟事件循环/工作线程和槽位释放；本次未改为异步日志队列，也不承诺日志永不阻塞。
- T27/T28 的两路额度、12秒等待、取消不提前释放、文件变化409、跨项目/账户隔离及完整性门禁保持不变；不自动重试写操作。

## 4. 改动文件

| 文件 | 本次增量 |
| --- | --- |
| `app/catalog_telemetry.py` | 新增允许字段/事件/状态及请求关联日志输出 |
| `app/catalog_hashes.py` | 增加完整哈希尝试、完成、复用及耗时数字统计 |
| `app/model_catalog.py` | 列表作用域 yield 当前计数容器；原清理不变 |
| `app/main.py` | 区分目录等待/工作线程结果，关联原 requestId，异常只分类不输出原文 |
| `tests/test_catalog_telemetry.py` | 新增15项计数、关联、时序、失败及隐私测试 |
| `tools/measure_catalog_telemetry.py` | 临时文件同步日志两事件成本测量，不导入app.main或连接DB |
| `docs/admin-catalog-telemetry-M32-T29.md` | 本说明与验收报告 |

另有 `evidence/M32-T29-*`、CLI维护的 Harness 状态/任务板及 `harness/records/M32/M32-T29.md`。`app/observability.py` 原实现未改；既有请求日志字段不变。

## 5. 真实测试与结果

- 最终目录、完整性、安全及市场回归 **109/109 通过，35.260秒**，其中本次新增15项、T28既有94项。证据 `evidence/M32-T29-tests-final.log`。
- 既有请求日志身份/脱敏及传输日志安全测试 **2/2 通过，0.873秒**。仅选内存API类的两项，不运行同文件的数据库测试。证据 `evidence/M32-T29-request-log-regression.log`。
- 首轮聚焦34项通过、首轮综合106项通过；日志 `M32-T29-focused-initial.log`、`M32-T29-regression-initial.log` 保留。没有失败被改成通过或隐藏。

统一测试进程隔离：

```powershell
$env:DATABASE_URL=''
$env:RUN_POSTGRES_TESTS='0'
$env:APP_APK_WORKER_ENABLED='false'
$env:APP_APK_EXTERNAL_ENABLED='false'
$env:PYTHONPATH='tests'
.venv/Scripts/python.exe -m unittest test_catalog_telemetry test_catalog_hashes test_catalog_reads test_catalog_read_api test_model_catalog_source test_model_catalog test_model_marketplace_api test_model_version_lifecycle test_model_download test_model_marketplace_automation test_model_marketplace_contract test_project_model_inventory.ProjectModelInventoryApiTests -v
.venv/Scripts/python.exe -m unittest test_project_reporting.ReportingApiTests.test_request_logs_use_server_identity_and_never_raw_input test_project_reporting.ReportingApiTests.test_recent_alert_limit_and_transport_logs_are_safe -v
```

新增断言包括：

- 服务端生成的 requestId 与响应头和三个事件一致；客户端伪造 ID、Cookie、查询秘密、Token、临时路径、模型哈希不出现在日志。字段集合严格符合白名单。
- 并发平台/项目请求的真实哈希数分别6/2，不串请求；available 使用模板路由且汇总事件不重复。
- 超时/取消时暂时无 worker 事件；释放测试屏障后才记录后台实际结果，之前 HTTP/read 结果不被覆盖。busy 不生成 worker 事件。
- 撤权在 worker 返回之后仍为 denied；文件变动为 changed；意外异常为 error且不输出异常文本；失败哈希尝试=1、完成=0。
- 未知元数据回退的3次完整读取均计入，不误算为复用；摘要不一致但完整读取成功仍计 completed，响应 hashValid=false，避免将性能统计当安全结论。
- 新增日志端抛异常时连续3次请求仍正常返回并释放额度；这只测试抛异常，不证明阻塞日志端无影响。

## 6. 实测观测开销

真实本地临时64 MiB文件、真实FastAPI ASGI路由、5轮、无数据库/NFS/摄像机。修改前后分别运行既有 `tools/measure_catalog_api.py`，不与本任务回归并行。OS缓存未清空，系统其他负载不受控。

| 指标 | 修改前 | 修改后 | 解释 |
| --- | ---: | ---: | --- |
| 目录请求中位数 | 59.385 ms | 59.313 ms | 差值-0.072ms属于小样本波动，不宣称提速或零成本 |
| 同轮无关请求完成中位数 | 20.278 ms | 20.914 ms | 增加0.636ms，不作因果推断 |
| 每轮完整SHA-256 | 1 | 1 | 未增加完整文件读取 |
| 新增目录日志/已执行请求 | 0 | 2 | 一条worker、一条read汇总 |

前后原始证据：`evidence/M32-T29-api-before.log`、`evidence/M32-T29-api-after.log`。修改后5轮worker均为 hashAttempts=1、hashCompleted=1、hashReuses=1；日志输出的哈希耗时与目录总时长可用同一requestId关联。

独立日志微基准：`.venv/Scripts/python.exe tools/measure_catalog_telemetry.py`。本地临时文件，10对预热、1000对计时，使用同步StreamHandler逐条flush。每对两条新增事件（UUID校验、对象构造、JSON、logging及两次flush）的成本：

- 中位数 **0.0305 ms**；本地微基准p95 **0.0440 ms**；最大 **0.2538 ms**。
- 含预热共2020条事件，373681字节；每对约370字节，仅当前短路由样本。
- 不含UUID生成、完整哈希或真实生产采集器；不是请求p95，更不是NFS/远端日志端性能。临时日志退出清理，未写用户正式日志。证据 `evidence/M32-T29-telemetry-cost.json`。

## 7. 尚未解决与交付边界

- 只补充校验观测，未定位生产502/内存问题；没有生产/HAR、数据库连接等待或NFS指标，不能把hashDurationMs等同这些指标。
- 同步日志端可能阻塞；异常被隔离可能丢日志。未新增日志队列、采集器、轮转/保留策略、报警或远程服务。
- 超时/取消不能终止底层I/O，线程卡住仍占额度；没有worker结束日志不能当作测试通过。额度仍每进程，不是集群全局限额。
- 未测试Linux/NFS、多worker、真实TCP断连、真实大模型或长稳；ASGI协程取消仅代表本地测试场景。
- 原T28文件指纹不是原子快照，未知元数据回退完整校验；发布、下载和运行门禁继续独立执行。前端未改，告警WS缺口仍保留5秒REST补偿。
- 保留既有Starlette/httpx弃用提示、脏改及任务板生成格式；本次不顺手修改依赖、用户环境或不相关任务。

## 8. 完成门禁

- M32-T29于`2026-11-09T22:27:15+08:00`启动，CLI于`2026-11-09T22:39:08+08:00`记录completed。记录：`harness/records/M32/M32-T29.md`；执行证据：`evidence/M32-T29-complete.log`。
- Harness单测 **34/34通过，0.078秒**；validate/render通过。证据：`M32-T29-harness-tests.log`、`M32-T29-harness-validate.log`、`M32-T29-harness-render.log`，均在evidence/下。M00 start/add输出属于单测临时夹具，不是部署或新增实际任务。
- 产品diff和新增文件尾部空白检查通过。既有Harness任务板`harness/TASK_BOARD.md:367`的Markdown双空格仍触发广域diff空白提示，保留CLI生成结果，不手改状态/任务板。
- 风险补充后再次validate，最终核验见`evidence/M32-T29-harness-final.log`。HEAD仍为`889b60fb3cfad0414c1994dcbad2388192d300ec`，索引为空；已有改动保留。
- 仅本地修改测试，不Docker、不部署、不改数据库/Nginx/K8s、不stage/commit/push/reset/clean，未创建或启动下一任务。
