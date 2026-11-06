---
major_task_id: M28
result: passed
owner: codex
accepted_at: 2026-10-19T16:04:40+08:00
---

# M28 管理后台模型资产去 Mock 化测试验收报告

## 验收结论

**通过**

M28 全部 13 个子任务完成；原验收覆盖模型资产真实目录及上传、转换等能力，补充核验 M28-T13 模型可用性与安全绑定门禁。遗留风险：旧 test_model_catalog 有 3 项因转换目录锁启动失败，按记录未解锁，未宣称通过。

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
| M28-T10 | 显示模型上传与后台转换实时进度 | completed | [M28-T10.md](../records/M28/M28-T10.md) |
| M28-T11 | 内置离线测试校准集保障生产转换 | completed | [M28-T11.md](../records/M28/M28-T11.md) |
| M28-T12 | 接入真实 COCO8 校准集 | completed | [M28-T12.md](../records/M28/M28-T12.md) |
| M28-T13 | 统一模型资产可用性与安全绑定门禁 | completed | [M28-T13.md](../records/M28/M28-T13.md) |

## 测试结果

- M28-T13 记录的 46 项相关 Python 回归、Node 前端行为/语法检查及 Harness 30 项检查；T13 记录中明确保留 3 项锁占用启动失败。此前 M28 验收报告中的模型资产 API、管理后台及转换测试。

## 验收证据

- harness/acceptance/M28-real-model-assets.md; harness/records/M28/M28-T13.md; app/model_catalog.py; tests/test_model_version_lifecycle.py; tests/model_asset_availability.test.cjs

## 遗留风险

- 无；若存在遗留风险，必须在正式通过前改写本节并给出责任人和截止日期。
