# M27-T04 远程转换检测与轮询修复（本地，未发布）

日期：2026-11-09。代码基线：889b60fb3cfad0414c1994dcbad2388192d300ec。

## 用户证据与结论边界

用户提供 `/aiyoloapi/conversion/jobs` 的 JSON：helmet PT 验证成功，mobile 任务在最后记录的 `remote_stage=exporting` 阶段失败，开始到结束约 140.29 秒；错误为“无法连接远程转换服务或响应无效”。这段响应不是请求列表接口自身出错的证据，也不能单凭该概括错误区分连接中断、响应超时、无效 JSON 或容器退出。没有查询生产 API、数据库或 K8s，也没有复用用户 Cookie/Token。

环境检查显示远程服务可用，但本地 `verifier.mobile_available=false`，消息为缺少 litert-torch。仓库 Dockerfile 明确只为视频服务安装 requirements-verifier.txt 中的 ai-edge-litert；完整导出栈应在转换服务。旧检查把本地导出能力错误地用作远程流程可用性的依据。此误报与线上导出中断是两个独立问题，修复误报不等于修复资源不足。

## 本地变更

- `tools/conversion_worker.py`：独立检测 NumPy/LiteRT Interpreter 和发行包元数据，返回 verifier_available/verifier_message；保留 mobile_available 表示本地导出能力。不安装额外导出依赖，不修改镜像或依赖清单。
- `app/conversion.py`：remote 检测组合远端协议能力与本地复验能力，不要求视频服务具备完整导出栈。
- 仅对同一个已受理远端任务的状态 GET 增加最多 2 次重试，针对瞬断/超时/408/429/5xx；进度明确标注重试，不重复 POST、不自动重启导出。保留停止取消、截止时间检查。
- 鉴权、TLS、响应协议异常不重试；检查远端 jobId/status。网络错误分类，不输出原始异常消息。远端终态失败仍失败。哈希/大小检查及实际本地复验流程不放宽。
- 增加隔离 HTTP 回归与依赖能力模拟测试；未修改前端、Nginx、Ingress、探针、卷、内存限制、生产配置、数据库或旧任务记录。

## 测试与证据

- 修复前新回归：14 个方法未通过，包含 4 个断言失败和 15 个错误（含 subTest）；缺少新方法/字段、错误分类及能力误报复现。日志 evidence/M27-T04-before-fix.log。
- 最终远程适配器与新增回归：24 通过，见 evidence/M27-T04-remote-final-r2.log；覆盖真实本机 HTTP 中断→503→恢复，同 jobId 无重复提交、完整上传/查询/下载/复验流程、重试耗尽、取消、截止时间、鉴权错误体中断不重试、TLS/格式错误、缺失复验依赖与完整导出依赖。
- 既有转换/HTTP API/进度测试：35 通过，1 项 PostgreSQL 集成按门禁跳过。日志 evidence/M27-T04-conversion.log。
- 转换服务协议与校准/幂等/取消回归：8 通过。日志 evidence/M27-T04-converter.log。模型来源清单：1 通过，evidence/M27-T04-model-metadata.log。
- Harness 单测 34 通过，evidence/M27-T04-harness.log；完成后再次 validate/render。
- 测试使用临时目录、回环 HTTP、合成小产物、模拟复验器；不执行真实 PT→INT8 重计算、不连接外部 PostgreSQL、不证明生产 4Gi 可以完成该模型导出。

## 未解决与发布状态

线上这次导出失败的底层原因尚未确诊，需要转换器 Pod 的重启次数、lastState.terminated、事件及必要时上次容器日志，与任务时间对齐。不能根据通用连接错误断言 OOM，也不能宣称本地轮询重试能修复持续内存不足或丢失的远端任务。不要直接提高/移除内存限制或反复提交重任务。

COCO8 标为 development-only：本次不将其作为 helmet 业务精度验收依据，不调整 input_size 或自动选用其他校准集。

本次未提交或推送 Git、未连接开发服务器、未构建/导出镜像、未修改生产。用户要求先集中修复 bug，后续另行批准 Git 交付和统一构建。共享 conversion_worker 改动将影响未来基于新提交构建的两个镜像，但未声称现有线上转换器镜像已包含修复。原工作区其他修改保留。

## 后续只读诊断：用户提供的生产输出

- 历史 mobile 任务开始于 2026-11-09 09:51:59、结束于 09:54:19（北京时间），最后记录阶段 exporting。
- 当前同名转换器 Pod UID 为 02e2ca4b-1dfb-4dec-850a-aa9bad8d00b2，创建于 2026-11-09T02:32:01Z（北京时间 10:32:01），启动于下一秒；比该任务失败晚 37 分 42 秒。
- 当前输出 ready=true、restartCount=0、lastState.terminated 无记录、memory limit=4Gi、node=node2。这些是当前实例的信息，不能用于排除旧实例当时的故障，亦不能证明该历史失败发生在当前 4Gi 配置下。
- 用户在当前容器按 CONVERTER_ROOT（缺省 /data）查询 jobs/*/job.json，结果为 []。只能确认该次查询没有找到任务文件；没有据此断言所有存储中的历史任务已删除。
- 用户按 saas-prod / Pod / aiyolo-model-converter-0 筛选 events，仅返回表头，没有事件行。不能推断事件为空的具体原因，也不能由此确认或排除 OOM。
- 结论：旧故障根因仍未确诊，M27-T05 保留 pending；不将当前 Pod 的零重启视为旧任务成功证据，不修改历史失败记录。后续先做当前视频服务到转换器的轻量健康查询；未经确认不重跑耗内存转换、不放宽 4Gi、不加卷、不构建部署。
- 本节仅记录用户回传证据，不声称已直接访问生产或验证当前完整转换链路。
