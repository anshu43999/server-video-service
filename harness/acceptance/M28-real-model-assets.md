---
major_task_id: M28
result: passed
owner: codex
accepted_at: 2026-09-21T09:24:32+08:00
---

# M28 管理后台模型资产去 Mock 化测试验收报告

## 验收结论

**通过**

管理后台模型资产已固定接入真实目录，并完成上传、转换、校准集、卸载、激活及本次 PT 选择反馈与完成态清理；上传页在桌面与窄屏均可清晰操作，失败保留重试输入，成功清空对应控件。

## 验收标准

- [x] 模型资产视图只展示服务端模型目录 API 返回的真实模型，不因页面演示模式生成或回退到静态模型卡片
- [x] 模型目录加载、刷新、空目录、鉴权失败和服务不可用均有明确状态，真实上传、转换、登记、激活和参数配置入口不回归
- [x] 模型列表和按流绑定选项不包含历史 MOCK.models 数据；脚本语法检查、模型 API 和管理后台回归测试通过

## 小任务完成记录

| ID | 小任务 | 状态 | 记录 |
|---|---|---|---|
| M28-T01 | 将模型资产视图固定接入真实目录 | completed | [M28-T01.md](../records/M28/M28-T01.md) |
| M28-T02 | 移除模型资产页旧的手机配置读取入口 | completed | [M28-T02.md](../records/M28/M28-T02.md) |
| M28-T03 | 下线异物入侵五类开发占位模型 | completed | [M28-T03.md](../records/M28/M28-T03.md) |
| M28-T04 | 实现模型资产安全卸载 | completed | [M28-T04.md](../records/M28/M28-T04.md) |
| M28-T05 | 修复模型激活标识冲突 | completed | [M28-T05.md](../records/M28/M28-T05.md) |
| M28-T06 | 修复模型卸载外部元数据路径 | completed | [M28-T06.md](../records/M28/M28-T06.md) |
| M28-T07 | 实现校准集资产管理与按任务选择 | completed | [M28-T07.md](../records/M28/M28-T07.md) |
| M28-T08 | 拆分独立校准集资产工作区 | completed | [M28-T08.md](../records/M28/M28-T08.md) |
| M28-T09 | 增强训练模型上传选择反馈与完成态清理 | completed | [M28-T09.md](../records/M28/M28-T09.md) |

## 测试结果

- 模型上传、模型市场、校准集、参数、转换 API 与转换回归测试通过；JavaScript 语法检查通过；浏览器窄屏及 1440x900 视觉验证通过；Harness 30 项单测与 validate 通过。

## 验收证据

- harness/records/M28/M28-T01.md; harness/records/M28/M28-T02.md; harness/records/M28/M28-T03.md; harness/records/M28/M28-T04.md; harness/records/M28/M28-T05.md; harness/records/M28/M28-T06.md; harness/records/M28/M28-T07.md; harness/records/M28/M28-T08.md; harness/records/M28/M28-T09.md

## 遗留风险

- 全量 `test_admin_*.py` 当前为 61/62：`test_admin_stream_live.AdminStreamLiveContractTests.test_persisted_configuration_and_runtime_states_are_distinct` 仍期待旧的 `app.js?v=20260917-stream-preview-stale-frame`，与当前工作区已有的 `20260920-calibration-workspace` 不一致。该断言不覆盖模型资产上传资源，责任范围属于视频流管理缓存版本测试；本次 M28 模型资产相关测试全部通过。
