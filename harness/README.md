# Server Video Service Harness

这套 Harness 专门管理 `server-video-service` 的开发任务和验收记录，不依赖也不修改 `mobile-app/harness`。

## 工作流

```text
需求阶段 → 任务拆分 → start → 开发与测试 → complete 记录 → 大任务验收
```

状态源是 `task-state.json`，任务板 `TASK_BOARD.md` 由 CLI 生成，不手工修改。

## 常用命令

在 `E:\aiyolo\server-video-service` 执行：

```powershell
python harness/harness.py validate
python harness/harness.py status
python harness/harness.py next
python harness/harness.py show M01-T01
python harness/harness.py start M01-T01 --owner codex
python harness/harness.py complete M01-T01 `
  --summary "完成协议定义" `
  --test "单元测试通过" `
  --evidence "docs/protocol.md" `
  --owner codex
```

完成一个大任务前，所有子任务必须完成或已按 `supersede` 流程作废：

```powershell
python harness/harness.py accept-major M01 `
  --result passed `
  --summary "联调验收通过" `
  --test "端到端测试通过" `
  --evidence "evidence/e2e-report.md" `
  --owner codex
```

任务定义因架构或范围变更而作废时，用 `supersede` 终止，不要用 `block` 顶替，也不要删除任务：

```powershell
python harness/harness.py supersede M04-T02 `
  --reason "输出协议改为 WebRTC/WHEP 后原 MJPEG 适配器任务定义作废" `
  --owner codex `
  --superseded-by M07-T04
```

命令会在 `records/<major>/` 下生成 `<task>.superseded-<时间戳>.md` 终止记录，保留原完成标准与终止理由。`--superseded-by` 可选，用于指向接管该范围的新任务。

## 状态

| 状态 | 含义 |
|---|---|
| `pending` | 尚未开始 |
| `in_progress` | 正在开发 |
| `blocked` | 存在明确阻塞，记录中必须说明原因和解除条件 |
| `completed` | 小任务有记录；大任务有通过的验收文档 |
| `superseded` | 任务定义因架构或范围变更而作废：不再执行、不计入完成、不满足依赖 |

`completed` 和 `superseded` 都是终态。`completed` 表示工作已交付并留有证据；`superseded` 表示这份工作永远不会交付，只保留任务定义和终止决策。已经 `completed` 的任务不能再被终止，历史记录一律保留。

## 规则

- 同一时间只启动一个小任务；
- 未完成依赖不能启动；
- `completed` 小任务必须有 `records/<major>/<task>.md`；
- `completed` 大任务的所有小任务必须处于终态，且不能全部是 `superseded`；
- `superseded` 小任务必须有 `supersededReason` 和 `supersededAt`，`supersededBy` 必须指向已存在的任务；
- `superseded` 不满足依赖，下游任务的 `dependsOn` 必须显式改写；
- `superseded` 任务不能被 `start` 或 `block`，`completed` 任务不能被 `supersede`；
- `completed` 大任务必须有 `result: passed` 的验收文档；
- 测试、配置、模型和部署证据应写入任务完成记录；
- 未经用户要求，不自动提交或推送 Git。

## 自动检查

```powershell
python -m unittest discover -s harness/tests -p "test_*.py"
python harness/harness.py validate
python harness/harness.py render
```

## 当前执行顺序

当前主线是 `M07 生产传输协议重构与架构重定位`：先完成 `M07-T01` 的治理工具升级，再冻结 ADR-002 输出协议决策，然后更新产品需求与接口契约，最后重构任务板并终止 `M04` 中因协议变更而作废的任务。`M00`–`M03`、`M06` 是已完成基线，不能替代真实服务器部署和目标模型压测。
