---
major_task_id: M07
result: passed
owner: claude
accepted_at: 2026-09-03T09:43:23+08:00
---

# M07 生产传输协议重构与架构重定位测试验收报告

## 验收结论

**通过**

生产传输协议的重构决策已完整落盘并在任务板上生效。Harness 增加 superseded 终止状态与 supersede 命令；ADR-002 冻结 WebRTC/WHEP 为唯一生产播放路径、LL-HLS 为过渡与回退、RTSP 仅供诊断、MJPEG 与 WebSocket JPEG 降级为测试与诊断通道，并把 ADR-001 明确标记为 superseded；产品需求升到 V2.0（新增 FR-08 检测结果元数据通道、FR-09 H.264 编码与分发约束），接口契约升到 v2（H.264 参数冻结表、播放地址接口、检测结果旁路、播放与回退顺序、三个新错误码）；README、传输方案对比、播放器兼容性、冻结项和生产安全文档同步一致；服务端任务板完成重构，M04-T02 终止、M04/M05 受影响任务改写、新增 M08 共 9 个实现任务。本次验收只覆盖决策与文档契约，不代表 H.264 编码、MediaMTX 推流和 WHEP 播放已经实现或实测。

## 验收标准

- [x] Harness 支持 superseded 终止状态，可作废因传输协议变更而无效的任务定义
- [x] ADR-002 冻结 WebRTC/WHEP 为主、LL-HLS 为过渡与回退、RTSP 为诊断的输出协议，并声明 ADR-001 作废
- [x] 产品需求与接口契约按新协议更新，MJPEG 降级为测试与诊断通道
- [x] 服务端任务板按新协议重构，受影响的旧任务全部有终止记录或改写后的定义

## 小任务完成记录

| ID | 小任务 | 状态 | 记录 |
|---|---|---|---|
| M07-T01 | 为 Harness 增加 superseded 终止状态与 supersede 命令 | completed | [M07-T01.md](../records/M07/M07-T01.md) |
| M07-T02 | 冻结 ADR-002 输出传输协议决策并作废 ADR-001 | completed | [M07-T02.md](../records/M07/M07-T02.md) |
| M07-T03 | 按新传输协议更新产品需求与接口契约 | completed | [M07-T03.md](../records/M07/M07-T03.md) |
| M07-T04 | 按新协议重构服务端任务板 | completed | [M07-T04.md](../records/M07/M07-T04.md) |

## 测试结果

- python harness/harness.py validate 通过
- python harness/harness.py render 重新生成 harness/TASK_BOARD.md
- harness 单元测试 28 项通过
- 服务端产品测试 32 项通过，其中 tests/test_transport_docs.py 由 1 项扩展为 6 项文档契约断言

## 验收证据

- docs/adr-002-production-transport.md
- docs/adr-001-output-protocol.md（superseded 标记与作废说明）
- PRODUCT_REQUIREMENTS.md V2.0；docs/video-protocol.md v2
- docs/transport-comparison.md、docs/player-compatibility.md、docs/frozen-validation-risks.md、docs/production-security.md、README.md
- harness/records/M07/M07-T01.md ~ M07-T04.md；harness/records/M04/M04-T02.superseded-20260903-093835.md
- harness/task-state.json 与 harness/TASK_BOARD.md（新增 M08）

## 遗留风险

本次验收通过的是**决策与文档契约**，实现与实测均未开始。以下四项在 ADR-002 中已登记为未验证假设，不得当作已验证结论引用：

| 风险 | 内容 | 承接任务 | 解除条件 |
|---|---|---|---|
| R-1 | libwebrtc 在 Android API 27 的可用性与 APK 体积增量（预估 arm64 约 10 MB）无实测 | `M08-T08`（冻结风险 FR-M08-ANDROID-WHEP）、App 侧 M11 之后的播放任务 | 提供 Android 真机或可用模拟器并确定 WebRTC 依赖 |
| R-2 | 公网 NAT 穿透、STUN/TURN 拓扑与 TURN 带宽成本未定 | `M08-T06`、`M08-T08`（冻结风险 FR-M08-PUBLIC-NAT） | 确定部署网络拓扑并核算是否启用 TURN |
| R-3 | 加入 H.264 编码后的单机并发容量未知，`M02-T03` 的无编码容量数字已作废 | 改写后的 `M04-T03` | 在含编码与推流的完整链路上完成压测，编码开销单独计量 |
| R-4 | WHEP 链路的首帧与 P50/P95 端到端延迟未实测，500 ms 目标尚未验证 | `M08-T08`、改写后的 `M04-T04` | 产出真实延迟数据，验证或推翻该目标 |

另有两项范围性遗留：

- `docs/frozen-validation-risks.md` 冻结的四项（Android 播放器兼容性、Android 断线重连、弱网与长时间运行、VLC 播放对照）仍然冻结，验证对象已改为 WHEP/LL-HLS；
- 场景化模型市场已于 2026-09-03 立项：新增 `M09 场景化模型市场（MVP）`（7 个小任务，冻结风险 FR-M09-SCENARIO-WEIGHTS）承接目录契约、单一数据源、目录查询、产物下载与完整性校验、首个场景模型上架和管理页视图；`M10 模型签名与发布服务（后移，待拆解）` 只保留大任务标题与一个拆解小任务 `M10-T01`，签名、灰度与密钥保管在 MVP 之后再拆解，不在 `M09` 范围内。App 侧展示由 `mobile-app` 的 `M14` 承接，其 `M14-T02`/`M14-T03` 以 `M09-T01` 契约为准。

责任人：项目所有者（Harness owner 记为 `claude` 的执行结果需由项目所有者复核）。截止日期待 Android 设备与部署拓扑确定后随 `M08` 排期确定，不在本验收内承诺日期。
