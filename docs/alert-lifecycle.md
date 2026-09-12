# 告警事件生命周期（M11-T06）

`app.alerts.lifecycle.EventStateMachine` 为运行时消费者提供候选、确认、结束和冷却四态协调。`run_vector` 继续作为纯函数入口；两者共享同一事件快照字段和冷却语义。

## 规则

- 首次满足条件创建 `CANDIDATE`；达到连续帧/时长阈值后转为 `CONFIRMED`。候选中断会丢弃并在下一次命中重新计时。
- 条件消失或主体丢失写入 `endedAtUs`。配置了 `cooldownMs` 时快照进入 `COOLDOWN`，重复命中只累加同级 `suppressedCount`。
- 去重键为 `(ruleId, sourceId, subjectKey, severity)`。更高事实级别绕过冷却并产生新实例；事实级别不会被后续观测改写。
- `severity` 是确认瞬间的事实级别；未处置超时只修改 `notifySeverity` 和 `escalatedAtUs`，且只提级一次。`acknowledge()` 将处置状态写入快照并停止提级计时。
- 快照包含 `ruleVersion`、`subjectKey`、`effectiveThresholds`、`measuredValue` 与稳定 `eventId`。所有时间戳来自观测/调用方，按来源单调递增校验。

示例：

```python
machine = EventStateMachine()
machine.on_hit(rule, {"sourceId": "cam-1", "subjectKey": "track:7",
                      "capturedAtUs": 1_000_000, "severity": "MINOR"}, confirmed=True)
machine.escalate_unattended(301_000_000)
```

