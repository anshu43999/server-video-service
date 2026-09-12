# 统一观测信封（M11-T03）

`app.alerts.observation` 是告警引擎唯一的观测接入边界。推理适配器可提交检测框、整帧分类、分割掩膜和标量读数，统一携带 `sourceId`、允许跳号的 `frameSeq`、微秒 `capturedAtUs` 与显式 `provides` 能力声明。

`ObservationIngestor` 按来源保存最后接收时间：时间戳倒退会抛出 `NonMonotonicTimestampError`，不会排序或静默丢弃；latest-only 造成的帧序号跳跃允许通过。空信封同样有效，用于后续算子推进 absence/窗口状态。

分类载荷没有 `BOX` 能力，因此不能进入需要框、ROI 或几何的算子。调用 `validate_operator_compatibility` 会返回结构化 `Rejection`（`CAPABILITY_UNSATISFIED` 或 `SUBJECT_KIND_UNSUPPORTED`），而不是静默不触发。声明能力与实际载荷不符通过 `capability_mismatches` 与 `capability_mismatch_count` 暴露。

该模块只做边界校验和能力拒绝；规则求值和事件生命周期继续由 M11-T05/M11-T06 实现。
