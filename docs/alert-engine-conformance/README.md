# 一致性金样向量

本目录存放「观测序列 → 期望事件」的金样向量，规格见 [../alert-engine-spec.md](../alert-engine-spec.md) §15，字段定义见 [../alert-engine.schema.json](../alert-engine.schema.json) 的 `ConformanceVector`。

**共 29 条向量，由 `M11-T02` 产出。** 服务端加载器是 [`tests/test_alert_engine_conformance.py`](../../tests/test_alert_engine_conformance.py)，App 侧 `M15-T05` 把这些 JSON **原样复制**到测试资源后逐条执行。

向量是双侧唯一裁判（规格 C-2）。某一侧失败时按「规格不完整」处理：回到规格与 Schema 补全定义，再同步两侧；不允许单方面改实现或改向量去对齐另一侧。向量里的每一个数字都是按规格算出来的，不是从某一侧的实现里抄出来的。

## 执行契约

引擎侧只需提供一个入口，两侧签名等价：

```python
# 服务端：app/alerts/engine.py（M11-T05 落地）
def run_vector(vector: dict) -> dict:
    """按 vector["observations"] 顺序喂给引擎，返回终态。

    return {"events": [<Event>, ...], "rejections": [<RejectionReason>, ...]}
    """
```

比对规则是冻结项（规格 §15.1），已写进服务端加载器，App 侧必须实现同样的语义：

1. 一条 `expectedEvents` 对应一个**事件实例**；被抑制的重复命中不单独成条，只体现为 `suppressedCount`。
2. **取终态**：比对整个观测序列执行完毕后的字段值，不比对中间态。
3. **未列出的字段不比对**；列出的字段必须相等，包括显式的 `null`（`escalatedAtUs: null` 表示「必须没有提级」）。
4. 时间戳、计数、帧号**精确相等**；浮点量容差 `1e-6`。
5. 两侧按 `confirmedAtUs` → `subjectKey` → `severity` 升序排序后位置对齐。
6. 只到候选的事件不出现在期望里。
7. `expectedEvents: []` 是**强断言**（必须没有任何事件）。
8. `expectedRejections` 只比对 `code`、`missing`（集合）与给出时的 `ruleId`，`message` 不比对；靠 `ruleId` 对齐，不靠顺序。
9. 未列出 `expectedRejections` 等价于空数组：所有规则都必须绑定成功。

服务端在引擎落地前，加载器只跑**语料校验**（向量合法性 + §15.4 覆盖度，25 项），执行比对整类跳过并在跳过信息里点名 `M11-T05`；`run_vector` 一出现，同一份向量立即开始判定实现。

## 向量索引

### 算子（八个已实现算子各至少一条）

| 向量 | 锁定什么 |
|---|---|
| [`op-presence-track-consecutive-frames`](op-presence-track-consecutive-frames.json) | `PRESENCE` + 连续帧确认；低置信帧不计入连续 |
| [`op-presence-frame-classification`](op-presence-frame-classification.json) | 分类型观测（无框）走 `frame:` 主体；低于 `minConfidence` 的标签不报 |
| [`op-in-region-polygon-inside`](op-in-region-polygon-inside.json) | `IN_REGION` 多边形归属；区域外的跟踪不产生事件 |
| [`op-line-cross-positive-direction`](op-line-cross-positive-direction.json) | `LINE_CROSS` 只在正方向跨越时命中，反向回穿不再命中 |
| [`op-dwell-accumulates-and-resets`](op-dwell-accumulates-and-resets.json) | `DWELL` 中断清零；重新成立取新 `startedAtUs`（§11.1 行为变更） |
| [`op-count-in-roi`](op-count-in-roi.json) | `COUNT` 按 ROI 统计；低置信与区域外目标不计数 |
| [`op-count-source-subject`](op-count-source-subject.json) | `COUNT` 的 `source:` 主体统计整帧，不套用 ROI |
| [`op-area-ratio-mask`](op-area-ratio-mask.json) | `AREA_RATIO` 有掩膜时用掩膜，`areaSource = MASK` |
| [`op-area-ratio-box-fallback`](op-area-ratio-box-fallback.json) | 无掩膜退化到框：面积取**并集**、分母是区域面积，`areaSource = BOX_FALLBACK` |
| [`op-rate-sliding-window`](op-rate-sliding-window.json) | `RATE` 滑动窗口左闭右闭；窗口过期后事件结束 |
| [`op-absence-empty-envelope`](op-absence-empty-envelope.json) | `ABSENCE` 由空信封推进计时（§11.4） |

### 生命周期、分档、提级与冷却

| 向量 | 锁定什么 |
|---|---|
| [`absence-stream-loss-silent`](absence-stream-loss-silent.json) | 断流不伪造 `ABSENCE`；`expectedEvents: []` 是强断言（§15.1 第 7 条） |
| [`severity-band-boundaries`](severity-band-boundaries.json) | 三档 `atLeast` 上下各一帧，六个边界值全覆盖 |
| [`escalation-unattended`](escalation-unattended.json) | 未处置提级：`severity` 不变、`notifySeverity` 变、`escalatedAtUs` 落值且只提一次 |
| [`cooldown-severity-escalates`](cooldown-severity-escalates.json) | 同级重复被抑制、级别升高另开实例并放行、级别降低仍抑制 |
| [`rate-window-capacity-bound`](rate-window-capacity-bound.json) | `RATE` 窗口容量上限：60 帧内只应有一个事件，窗口不过期就会误报 `CRITICAL` |
| [`track-loss-ends-event`](track-loss-ends-event.json) | 跟踪丢失结束事件（§11.2 行为变更：M07 在这里抛错） |

### 几何边界

| 向量 | 锁定什么 |
|---|---|
| [`geometry-polygon-boundary-point`](geometry-polygon-boundary-point.json) | 多边形边上点与顶点算在内 |
| [`geometry-polygon-concave-notch`](geometry-polygon-concave-notch.json) | 凹多边形射线法：凹口内的点在外（打掉外接框/凸包近似） |
| [`geometry-edge-touch-not-intersecting`](geometry-edge-touch-not-intersecting.json) | 仅边线接触算不相交；面积只算交叠部分 |
| [`geometry-center-point-inside`](geometry-center-point-inside.json) | 归属只看中心点（§17 第 11 行行为变更）；相交但中心在外不算在内 |

### 绑定期显式拒绝（§6 固定顺序）

| 向量 | 锁定什么 |
|---|---|
| [`reject-capability-and-subject-and-operator`](reject-capability-and-subject-and-operator.json) | `OPERATOR_NOT_IMPLEMENTED` > `SUBJECT_KIND_UNSUPPORTED` > `CAPABILITY_UNSATISFIED`；合法规则照常出事件 |
| [`reject-roi-required-and-labels`](reject-roi-required-and-labels.json) | `ROI_REQUIRED` 与 `TARGET_LABELS_REQUIRED`（第 4、5 步） |
| [`reject-roi-geometry-degenerate`](reject-roi-geometry-degenerate.json) | 自相交、零面积、零长度 ROI 一律 `ROI_GEOMETRY_INVALID`，引用它们的规则全不求值 |

### M07 基线（证明没有静默改变已验收语义）

| 向量 | 锁定什么 |
|---|---|
| [`baseline-m07-confirm-requires-both-thresholds`](baseline-m07-confirm-requires-both-thresholds.json) | 连续帧与停留时长是**与**关系；停留 = (最后成立 - 首次成立)/1000 |
| [`baseline-m07-same-severity-cooldown`](baseline-m07-same-severity-cooldown.json) | 同级重复仍被抑制，`suppressedCount` 累加，`endedAtUs` 不被抑制改写 |
| [`baseline-m07-cooldown-boundary`](baseline-m07-cooldown-boundary.json) | 冷却边界取 `≥`；被抑制的命中不刷新窗口起点 |
| [`baseline-m07-active-track-keeps-evaluating`](baseline-m07-active-track-keeps-evaluating.json) | 一条跟踪丢失不影响同帧其他跟踪，也不抛错 |
| [`baseline-m07-roi-inside-and-outside-unchanged`](baseline-m07-roi-inside-and-outside-unchanged.json) | 完全在内 / 完全在外的判定与 M07 一致 |
## 向量覆盖不到的一处

**「确认后停止提级计时」（规格 §14.2）不在向量里**：`ConformanceVector` 只有观测与规则两个输入通道，没有「人在第几秒点了确认」这种动作通道，硬塞进去会把处置动作变成观测的一部分，污染「观测是唯一时间来源」这条硬约束。这一条由两侧各自的单元测试覆盖 —— 服务端 `M11-T06`（状态机）与 `M11-T09`（处置闭环），App 侧 `M15-T04`。若后续要把它纳入向量，必须先在规格 §15 与 Schema 里加动作序列字段，再重新冻结（§18）。

## 改动向量的顺序

规格 §18 固定：**规格 → Schema → 向量 → 服务端实现 → App 实现**。向量文件由 `M11-T02` 的生成脚本按规格算出，人工改 JSON 里的数字属于绕过规格，评审时按不通过处理。
