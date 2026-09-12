# M11-T05 算子求值器

`app.alerts.engine.run_vector(vector)` 是 v1 告警规格的确定性执行入口，接收
M11-T02 的观测序列并返回 `events` 与显式 `rejections`。实现了
`PRESENCE`、`IN_REGION`、`LINE_CROSS`、`DWELL`、`COUNT`、`AREA_RATIO`、`RATE`
和 `ABSENCE`。

所有时间均使用观测信封的 `capturedAtUs`。连续帧和持续时间阈值在同一观测上
共同满足后才确认；跟踪通过 `lostTrackIds` 结束。`AREA_RATIO` 优先使用掩膜，
无掩膜时使用 ROI 与检测框并集面积。`RATE` 为 `[t-window,t]` 左闭右闭窗口，
每次观测都会从 `deque` 回收过期命中，内存上限随窗口内命中数增长而有界。

金样一致性由 `tests/test_alert_engine_conformance.py` 自动加载
`docs/alert-engine-conformance/*.json` 执行；不满足能力、ROI 或预留算子的规则
返回结构化拒绝，不静默跳过。
