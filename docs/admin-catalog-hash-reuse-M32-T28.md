# M32-T28：模型目录单次读取内的重复哈希去重

日期：2026-11-09（Asia/Shanghai）。工作目录：`E:\aiyolo\server-video-service`。

## 1. 授权与基线

- 用户批准 M32-T28 定义后，通过 Harness CLI `add → show → start` 绑定，依赖已完成的 M32-T27；owner `codex`，startedAt `2026-11-09T21:42:52+08:00`。没有绕过门禁手改状态。
- 已完整阅读根 AGENTS、服务端 README、Harness README/PostgreSQL 隔离说明、ADR-004、原请求分析方案及 Git-first 发布流程；先确认 T27 的完整检查通道与已有修复。
- 开始时 HEAD 为 `889b60fb3cfad0414c1994dcbad2388192d300ec`，分支 main，索引为空；工作区已有 627 条 Git 状态记录。T27 的 app/main.py、契约、API 测试及测量脚本均属已有未提交成果，在其基础上增量修改，未覆盖或重置。
- 开始时 `app/model_catalog.py` 无 diff；本次仅针对单次列表读取里的重复完整哈希，不扩展到轻量目录接口、跨请求缓存、日志平台或部署。

## 2. 实现与安全边界

仅在 T27 三个列表入口的工作线程检查中显式启用 `list_read_hashes()`：

1. `GET /aiyoloapi/models`（包括原有项目上下文入口）。
2. `GET /aiyoloapi/projects/{project_id}/models`。
3. `GET /aiyoloapi/projects/{project_id}/models/available`。

一次检查内，相同绝对路径的完整 SHA-256 摘要可复用；**复用摘要，不复用校验通过结论**。主模型及各 artifact 仍分别比较自己的预期哈希和大小；不同路径即使内容相同也分别读取。不合并不同硬链接名称，不引入跨请求、跨账号或跨线程共享缓存。

实现约束：

- 摘要状态属于一个同步工作线程作用域，正常结束或异常均在 finally 中清理；后续请求重新读取全部文件。没有新增持久化状态、配置、依赖或数据库写入。
- 全量哈希读取前后、摘要复用时、作用域结束返回投影前都检查文件身份、类型、大小、修改时间和元数据变更时间。文件删除/替换/变化时拒绝旧投影，返回现有 `409 catalog_changed`，不暴露本地路径。
- Windows 不将 Python 的创建时间误当变更时间，使用只读 FileBasicInfo 获取变更时间；缺少文件身份/变更时间时不复用摘要，并在结束时完整重算。此回退可能更慢，但不把未知状态当缓存命中。
- 同大小内容篡改后恢复 mtime，或替换为同大小/同 mtime 的另一文件，均有真实临时文件测试覆盖。
- 原 `ModelCatalog.sha256()` 算法不变。仅 inspect 的内部哈希调用可在明确列表作用域中使用摘要；未启用作用域的调用仍逐次完整哈希。详情、发布、下载、激活、启动、运行检查都不启用本次复用。
- T27 的每进程 2 路额度、12 秒等待上限、取消不提前放槽、执行前及返回前撤权检测、项目隔离、registry/assignment 变化拒绝保持不变。前端旧请求取消和告警 5 秒 REST 补偿未改。

这不是文件系统事务或加锁快照。文件指纹是一次全量读取后的失效检查，不是仅凭 mtime 判定安全；对于不可靠元数据、远程属性缓存、特权恶意改写或最终检查之后的变化，不承诺原子一致性。正式下载、发布与运行仍必须执行各自的独立校验。

## 3. 改动文件

| 文件 | 本任务增量 |
| --- | --- |
| `app/catalog_hashes.py` | 新增单次读取摘要容器、文件变化检测、未知元数据完整重读回退 |
| `app/model_catalog.py` | 新增明确列表作用域及 inspect 哈希分派；原 SHA-256 算法不变 |
| `app/main.py` | T27 工作线程内启用作用域，文件变化映射为 409 |
| `tests/test_catalog_hashes.py` | 新增 16 项真实文件、线程隔离、门禁与回退测试 |
| `tests/test_catalog_read_api.py` | 在 T27 测试上新增 4 项真实 ASGI 计数、竞态及下载/激活门禁回归 |
| `tools/measure_catalog_reads.py` | 新增可选 `--reuse-hashes`，默认仍测不复用的基线 |
| `tools/measure_catalog_api.py` | 在隔离夹具中增加每轮真实 SHA-256 调用次数记录 |
| `docs/model-marketplace-api.md` | 增补仅列表、单次读取及变化拒绝契约 |
| `docs/admin-catalog-hash-reuse-M32-T28.md` | 本交付报告 |

另外包含本任务 `evidence/M32-T28-*`、Harness CLI 维护的 `harness/task-state.json` / `harness/TASK_BOARD.md`、完成记录 `harness/records/M32/M32-T28.md`。其他脏改均不计入本任务。

## 4. 真实测试

最终综合回归 **94/94 通过，27.779 秒**：本次新增 20 项（16 个文件/作用域测试 + 4 个 API 测试），加 T27 的 74 项。证据：`evidence/M32-T28-tests-final.log`。

```powershell
# cwd: E:\aiyolo\server-video-service；只覆盖测试进程环境，不改 .env。
$env:DATABASE_URL=''
$env:RUN_POSTGRES_TESTS='0'
$env:APP_APK_WORKER_ENABLED='false'
$env:APP_APK_EXTERNAL_ENABLED='false'
$env:PYTHONPATH='tests'
.venv/Scripts/python.exe -m unittest test_catalog_hashes test_catalog_reads test_catalog_read_api test_model_catalog_source test_model_catalog test_model_marketplace_api test_model_version_lifecycle test_model_download test_model_marketplace_automation test_model_marketplace_contract test_project_model_inventory.ProjectModelInventoryApiTests -v
```

关键覆盖：

- 主文件/重复 artifact、多个条目引用同一路径只哈希一次；每个引用的预期哈希/大小错误仍独立失败；不同文件同内容不合并。
- 下个请求重新计算、并发线程互不共享、异常后不遗留命中、失败摘要不保存、未知变更时间完整重读。
- 读取中变更、检查后变更、删除、同大小并恢复 mtime 的篡改、保留大小/mtime 的替换均拒绝旧结果。
- 成功列表后篡改文件，下载/激活拒绝；启动、发布和运行模型解析仍拒绝错误完整性；既有发布/版本/下载回归保留。
- 真实 ASGI 三个列表端点及项目兼容入口连续两次请求：平台/available 的 3 版本、6 个不同文件每次各计算 6 次；项目单分配的 2 个不同文件每次各计算 2 次。项目显示名称、内部 get 和摘要构造不会重复完整读取同一路径。
- T27 会话撤销、角色降权、成员移除、项目修订、跨项目隔离、旧协程取消、超时、并发上限等全部回归通过。

首次 20 项聚焦测试通过：`M32-T28-hashes-initial.log`；首次综合 92 项通过：`M32-T28-regression-initial.log`。之后补充启动/发布测试时，夹具遗漏 runtime/labels 被原启动门禁正确拒绝；修正夹具必需字段后最终 94 项通过。失败日志 `M32-T28-hashes-final.log` 原样保留，**文件名含 final 不表示通过**；以 `M32-T28-tests-final.log` 为最终结果。未放宽产品校验来修测试。

## 5. 实测性能与口径

Windows 本地临时合成文件 **64 MiB、5 轮**，主文件与一个 artifact 指向同一路径。文件读取和 SHA-256 为真实执行；API 为真实 FastAPI ASGI 请求，不是浏览器 Network/HAR。测试不连接数据库/摄像机/NFS。OS 文件缓存未清空，不代表冷盘性能或生产分位数。

| 指标 | 去重前（已含 T27） | 去重后 | 结论 |
| --- | ---: | ---: | --- |
| 每轮完整 SHA-256 次数 | 2 | 1 | 同文件重复读取消除；不是少校验一个引用 |
| 有界目录函数耗时中位数 | 117.306 ms | 57.710 ms | 本地样本减少约 50.8% |
| 真实 ASGI 目录请求中位数 | 120.666 ms | 59.343 ms | 本地样本减少约 50.8% |
| 同轮无关 auth/status 完成中位数 | 14.260 ms | 17.476 ms | 未进一步改善；保留调度噪声事实 |
| 5 ms heartbeat 最大实际间隔 | 16.137 ms | 20.127 ms | 未改善该上界，不宣称硬实时 |

可复现命令（顺序执行，不与回归测试同时运行）：

```powershell
.venv/Scripts/python.exe tools/measure_catalog_reads.py --mode bounded
.venv/Scripts/python.exe tools/measure_catalog_reads.py --mode bounded --reuse-hashes
.venv/Scripts/python.exe tools/measure_catalog_api.py
```

证据：

- `evidence/M32-T28-bounded-before.json` / `M32-T28-bounded-after.json`：同一实现可选择不启用/启用摘要作用域进行函数级对比，每轮 hashCalls 分别 2 / 1。
- `evidence/M32-T28-api-before.log`：产品修改前对 T27 真实路由采样；`M32-T28-api-after.log`：修改后采样，5 轮均 hashCalls=1。基线脚本当时尚未记录 API hashCalls，不将函数级计数冒充基线 API 计数。
- 无关请求耗时从每轮启动计时，含 5 ms 延迟及调度等待，不是仅 auth/status 函数自身运行时间。
- 采样串行且未与本任务回归同时运行，但系统其他负载未控制。SHA-256 调用次数不等于物理磁盘读取次数或 NFS 流量；没有 CPU、NFS 或生产收益测量。

## 6. 未解决问题

- 尚未验收 Linux/NFS 元数据一致性、生产真实模型、多 worker/集群、冷缓存、多模型容量、真实 TCP 断连或长稳。两路额度仍只限每进程。
- 底层 I/O 卡住不能强杀线程；取消/超时后仍占槽直到实际完成，进程退出可能等待工作线程。此为 T27 已有边界，未在本任务改造执行器生命周期。
- 未知文件身份/变更时间会回退重复全量哈希并增加最终重算，可能比 T27 更慢；安全优先，不保证所有文件系统均有性能收益。
- 去重以路径为边界，路径别名/硬链接/符号链接不承诺合并；大目录的摘要元数据随本次访问的唯一文件数增长，作用域结束立即释放，不保留文件内容或打开句柄。
- 权限权威复核仍可能同步访问存储，未接入通道的详情/版本接口仍可能同步长读；没有新增轻量目录接口。
- 原 T24 WS 事件覆盖缺口保持 5 秒 REST 补偿；没有为降请求数牺牲撤权检测、隔离、取消或模型完整性。
- Starlette/httpx 弃用提示未改依赖清理；本次不修与范围无关的既有工作区改动。

## 7. 完成门禁

- Harness CLI 于 `2026-11-09T21:59:49+08:00` 完成 M32-T28，记录 `harness/records/M32/M32-T28.md`；日志 `evidence/M32-T28-complete.log`。
- Harness 单测 **34/34 通过，0.091 秒**；validate、render 通过。日志分别为 `M32-T28-harness-tests.log`、`M32-T28-harness-validate.log`、`M32-T28-harness-render.log`，均在 evidence/ 下。M00 start/add 是 Harness 单元测试夹具输出，不代表实际部署或新增下一任务。
- 产品 diff 与新增/增量测试脚本的尾部空白检查通过；任务板仍有既有 `harness/TASK_BOARD.md:367` Markdown 双空格换行，被广域 diff --check 报告 trailing whitespace。保留 CLI 生成结果，不手改任务板。
- 完成记录补充风险后再次 validate；最终核验日志 `evidence/M32-T28-harness-final.log`。HEAD 仍为 `889b60fb3cfad0414c1994dcbad2388192d300ec`，索引为空；既有改动保留。
- 仅本地修改与测试，不 Docker、不部署、不改数据库/Nginx/K8s、不 stage/commit/push/reset/clean。没有创建或启动下一任务。
