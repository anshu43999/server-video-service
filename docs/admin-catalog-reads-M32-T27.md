# M32-T27：模型目录耗时测量与受控校验

日期：2026-11-09。实际工程：`E:\aiyolo\server-video-service`。

## 1. 授权、绑定与范围

- 用户批准新增并实施 M32-T27，依赖已完成的 M32-T26；通过 Harness CLI 新增、核对、启动，owner 为 `codex`，startedAt 为 `2026-11-09T20:34:00+08:00`。
- 先读取工作区规则、服务端 README、Harness README/PostgreSQL 测试隔离规则、ADR-004、Git-first 发布流程及管理后台请求分析方案；检查已有修复后再实施。
- 开始时仓库已有大量前端、服务端、模型、测试和 Harness 改动，索引为空；HEAD 为 `889b60fb3cfad0414c1994dcbad2388192d300ec`。这些既有成果不清理、不覆盖，不将整仓 diff 算作本任务成果。
- 仅本地源码、测试、契约、测量脚本和证据；不构建/导出 Docker 镜像，不操作开发服务器、生产、数据库、Nginx、K8s，不 stage/commit/push/reset/clean。
- 本任务不修改前端；告警 WS 事件覆盖缺口仍保留 **5 秒 REST 补偿**，不自动进入下一任务。

## 2. 问题与实施

本地实测确认：异步列表路由同步调用完整目录检查时，模型 SHA-256 文件读取会长时间占用事件循环。将原完整检查移入独立、有界线程通道，使其他请求可以继续调度；没有把完整性结果缓存为安全结论。

覆盖端点：

1. `GET /aiyoloapi/models`，包括原有项目上下文兼容入口。
2. `GET /aiyoloapi/projects/{project_id}/models`。
3. `GET /aiyoloapi/projects/{project_id}/models/available`。

执行约定：

- 每进程最多 **2 个已提交/运行的目录读取**；超过额度立即 `503 catalog_busy`，没有待处理请求队列。
- 等待工作线程结果最多 **12 秒**；超过返回 `503 catalog_timeout`。busy/timeout 均携带 `Retry-After: 1`；这不是整个 HTTP 请求或底层 I/O 的强制总时限。
- HTTP 协程取消/超时不强杀文件读取、不提前释放槽位。仅底层 concurrent future 实际完成时释放额度，避免取消风暴把线程池队列无限堆积。
- 执行前、线程内与返回结果前验证会话及权威项目上下文；会话失效、角色降权、成员撤销、项目/成员修订变化不返回旧模型结果。
- 完整检查前后比较 registry stat 指纹及项目分配元数据；发现变化返回 `409 catalog_changed`，要求重新读取。指纹只是失效检测，不是基于 mtime 的完整性缓存，也不是跨资源事务快照。
- 项目分配快照使用 `include_display=False`，避免安全检查的显示字段再触发模型哈希；默认公开分配列表仍返回原 `modelName`。
- 不缓存、不跨账户合并结果；保留成功响应字段、项目隔离及原 SHA-256、缺文件和元数据检查。客户端可以按既有有界策略重试读取，但本次未新增自动重试，不自动重放写操作。
- 未改 `app/model_catalog.py`；详情、版本详情、下载、发布、激活、启动及运行门禁不接入本次通道，也不简化校验。

## 3. 改动文件

| 文件 | 本次变更 |
| --- | --- |
| `app/catalog_reads.py` | 新增每进程有界执行器、超时/取消和关闭行为 |
| `app/main.py` | 三个列表读取端点接入；权限复核及目录/分配失效检测 |
| `app/project_model_assignments.py` | 新增仅内部使用的无模型显示字段元数据读取选项；默认行为不变 |
| `tests/test_catalog_reads.py` | 6 项执行器并发、超限、取消、超时、异常和关闭测试 |
| `tests/test_catalog_read_api.py` | 13 项真实 ASGI 路由契约、隔离、撤权、完整性和竞态测试 |
| `tools/measure_catalog_reads.py` | 临时 64 MiB 文件、哈希次数和事件循环 heartbeat 测量 |
| `tools/measure_catalog_api.py` | 真实 ASGI 目录请求与同时发生的 auth/status 请求测量 |
| `docs/model-marketplace-api.md` | 补充限额、错误与重试边界 |
| `docs/admin-catalog-reads-M32-T27.md` | 本报告 |

另有本任务 `evidence/M32-T27-*` 原始证据、Harness CLI 维护的 `harness/task-state.json` / `harness/TASK_BOARD.md`，以及完成记录 `harness/records/M32/M32-T27.md`。上述 Harness 文件包含先前任务信息，不能整体归为本任务新增内容。

## 4. 真实测试结果

最终本地回归 **74 项全部通过，25.285 秒**：新增 19 项 + 既有模型相关回归 55 项。证据：`evidence/M32-T27-tests-final.log`。

```powershell
# 在 E:\aiyolo\server-video-service 执行；仅进程级环境覆盖。
$env:DATABASE_URL=''
$env:RUN_POSTGRES_TESTS='0'
$env:APP_APK_WORKER_ENABLED='false'
$env:APP_APK_EXTERNAL_ENABLED='false'
$env:PYTHONPATH='tests'
.venv/Scripts/python.exe -m unittest test_catalog_reads test_catalog_read_api test_model_catalog_source test_model_catalog test_model_marketplace_api test_model_version_lifecycle test_model_download test_model_marketplace_automation test_model_marketplace_contract test_project_model_inventory.ProjectModelInventoryApiTests -v
```

覆盖包括：真实临时文件同大小篡改/缺失、列表响应契约、跨项目隔离、登出/平台降权/成员撤销/owner 降权/项目 revision 变更、HTTP 协程取消、超时、2 路并发与第 3 路拒绝、20 次超额请求不执行、registry/assignment 变化拒绝旧投影，以及发布/版本/下载等既有模型回归。assignment 元数据 guard 的测试确认它不额外调用模型检查且默认显示字段保留。

测试使用临时文件、内存账户和真实 FastAPI ASGI 路由；没有以数据库/生产测试冒充本地回归。未运行 PostgreSQL 或 SQLite 集成验收。

## 5. 实测改善与不变部分

临时合成文件为 **64 MiB**；每组 **5 轮**，没有清理操作系统文件缓存。下面是本机小样本，不是生产 p95、Network/HAR 或容量承诺。

| 指标 | 实施前 | 实施后 | 解释 |
| --- | ---: | ---: | --- |
| 完整目录检查耗时中位数 | 111.677 ms | 115.806 ms | 检查自身没有加速 |
| 5 ms heartbeat 的最大间隔 | 169.841 ms | 19.525 ms | 事件循环长时间阻塞明显减少；不是硬实时保证 |
| 每轮 SHA-256 调用次数 | 2 | 2 | 主文件与 artifact 引用同一文件，仍完整检查两次 |
| ASGI 目录请求完成中位数 | 115.368 ms | 122.650 ms | 增加调度/复核开销，没有宣称模型列表更快 |
| 同轮无关 auth/status 请求完成中位数 | 123.264 ms | 16.982 ms | 从一轮开始计时，包含 5 ms 延迟与调度等待，改善约 86% |

证据及口径：

- 函数级基线：`evidence/M32-T27-baseline.json`；实施后：`evidence/M32-T27-bounded.json`。用 `tools/measure_catalog_reads.py --mode baseline` / `--mode bounded` 可比较原同步调用与有界执行方式。
- 真实 ASGI 基线在路由改造前采集：`evidence/M32-T27-api-baseline-isolated.log`；最终结果：`evidence/M32-T27-api-final.log`。运行 `tools/measure_catalog_api.py` 测量当前路由，不会自动恢复历史实现。
- 最终 ASGI 无关请求 5 个样本为 61.783 / 16.982 / 18.927 / 9.135 / 11.690 ms。最终测量与回归测试在独立进程并行执行，存在本机负载影响；不要解读为稳定延迟上界。
- 本次不是请求次数优化；不宣称降低单次哈希次数、总 CPU/磁盘 I/O、目录总耗时，或解决历史 502/内存问题。原方案的源码请求数推算也没有转述为 Network 实测。

## 6. 过程异常与证据保留

- 初次新增测试中的两项失败来自测试夹具：Python tuple 与 JSON list 比较，以及内存账户以 username 而非 accountId 为 key。修正测试后通过；保留 `evidence/M32-T27-new-tests-initial.log`，不抹去失败。
- 首次 API 基线漏关测试生命周期中的 APK 后台 worker，出现 `apk_worker_iteration_failed`；该次已清空 DATABASE_URL，未连接真实数据库。测量脚本随后在 import 应用前显式关闭 APK worker/external，并重跑隔离基线；以 `api-baseline-isolated.log` 为主证据，保留初次 `api-baseline.log`。
- Starlette/httpx 弃用提示保留，未为清理警告修改依赖或用户环境。中间测试/测量日志保留，最终通过情况以 74 项综合日志及最终 API 日志为准。

## 7. 未解决问题与验收边界

- SHA-256 重复读取未减少。详情、版本及其他未接入列表通道的同步读取仍可能阻塞事件循环，需要另行测量、定义任务与授权。
- 2 路限额仅每进程，不是跨 worker/跨集群全局限制；多 worker 可放大总 I/O。线程执行不是异步存储，不改善底层文件系统持续卡顿。
- 取消/12 秒等待超时不能终止 Python 线程内文件 I/O；永久卡住最多占满 2 个槽，随后目录请求持续 503。Python 进程退出也可能等待在途线程；本次未新增 lifespan 强停逻辑，未验收服务重启或退出耗时。
- 权限权威复核仍有同步存储访问；registry/assignment 前后比较不是跨数据库与文件的原子快照。它增加失效拒绝，不取代下载、发布或运行时完整性门禁。
- 取消测试覆盖 ASGI 请求协程取消，不等同于真实 TCP 断连验收。未测生产 Network/HAR、NFS、大模型、多模型容量、多 worker、真实摄像机、数据库负载或长稳。
- 此次没有改变前端既有旧请求取消/项目隔离逻辑；WS 覆盖缺口及 5 秒 REST 补偿保持原状。后续生产验收或进一步降低完整校验成本需单独授权。

## 8. Harness 与交付门禁

- Harness CLI 已于 `2026-11-09T20:53:00+08:00` 将 M32-T27 记为 completed，完成记录为 `harness/records/M32/M32-T27.md`，执行输出为 `evidence/M32-T27-complete.log`。
- Harness 单元测试 **34 项全部通过，0.060 秒**：`evidence/M32-T27-harness-tests.log`。其中 M00 测试任务的 start/add 输出来自测试夹具，不是新增生产任务或执行部署。
- `validate`、`render` 均通过，证据为 `evidence/M32-T27-harness-validate.log`、`evidence/M32-T27-harness-render.log`；完成记录补充风险后再次验证。
- 本任务产品 diff 空白检查与新增文件尾部空白检查通过。Harness 生成的 `TASK_BOARD.md:367` 保留既有 Markdown 双空格换行，广域 `git diff --check` 仍会报告 trailing whitespace；不手改任务板绕过 CLI。
- 最终 HEAD 仍为 `889b60fb3cfad0414c1994dcbad2388192d300ec`，索引为空，`app/model_catalog.py` 无 diff；既有脏改保留。最终核验输出见 `evidence/M32-T27-harness-final.log`。没有启动下一任务。
