---
major_task_id: M27
result: passed
owner: codex
accepted_at: 2026-09-08T18:52:00+08:00
---

# M27 远程模型转换服务适配测试验收报告

## 验收结论

**通过**

远程模型转换服务适配完成：安全配置、幂等流式 HTTP 执行、轮询取消、产物完整性校验、本地 LiteRT 复验和后台配置均已接通，local/WSL 既有流程保持回归通过。

## 验收标准

- [x] 转换配置支持 remote 模式且与 local、WSL 模式互斥，远程地址和令牌经过校验并不会出现在日志或任务快照中
- [x] 服务端可幂等提交 PT、轮询远程任务并下载 Android TFLite 与转换元数据，超时、取消、重试和进程重启行为明确
- [x] 远端产物回到本机后重新执行大小、SHA-256 与 TFLite 张量契约校验，校验失败不登记 Android 产物
- [x] 管理后台可配置和检测远程转换服务，原有 WSL/local 转换保持可用

## 小任务完成记录

| ID | 小任务 | 状态 | 记录 |
|---|---|---|---|
| M27-T01 | 冻结远程转换 HTTP 协议与安全配置 | completed | [M27-T01.md](../records/M27/M27-T01.md) |
| M27-T02 | 实现远程转换执行器与本地复验 | completed | [M27-T02.md](../records/M27/M27-T02.md) |
| M27-T03 | 接通后台远程配置与回归测试 | completed | [M27-T03.md](../records/M27/M27-T03.md) |

## 测试结果

- 远程 HTTP 集成 4/4 通过；转换回归 17/17 通过
- 后台配置测试 2/2 与 node 语法检查通过
- Harness 单元测试 30/30、validate/render 通过

## 验收证据

- docs/remote-model-conversion.md
- app/conversion.py
- tools/conversion_worker.py
- tests/test_remote_conversion.py

## 遗留风险

- 无；若存在遗留风险，必须在正式通过前改写本节并给出责任人和截止日期。
