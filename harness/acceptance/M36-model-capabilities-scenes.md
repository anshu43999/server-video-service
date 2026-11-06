---
major_task_id: M36
result: passed
owner: codex
accepted_at: 2026-10-21T21:21:57+08:00
---

# M36 模型端能力与项目场景配置第一阶段测试验收报告

## 验收结论

**通过**

第一阶段模型端能力与项目场景配置验收通过；19/19子任务完成，真实本机服务单成员运行授权的开始、续期、心跳、令牌轮换、停止撤权、旧令牌重放与跨账号拒绝均通过。多成员推理调度仍不在本阶段验收范围。

## 验收标准

- [x] 模型发布按PC、移动端或双端能力独立标记；目标端产物分别校验，缺少非目标端产物不阻止发布或使用，Android转换不再是模型发布前置条件
- [x] 场景作为项目可管理的业务配置独立于模型分类；有权限的用户可创建和编辑场景及其模型成员关系，服务端强制校验项目和场景能力
- [x] 场景可配置一个或多个已发布模型并声明图片/视频输入适用性；本阶段只交付配置、授权、目录展示与兼容消费，不宣称已支持多模型运行编排
- [x] 既有modelId/version、产物签名/哈希、参数快照、项目隔离和图片/相机既有运行行为保持兼容；服务端、PC管理后台、Android契约测试及Harness门禁通过

## 小任务完成记录

| ID | 小任务 | 状态 | 记录 |
|---|---|---|---|
| M36-T01 | 冻结模型目标端能力与场景配置跨端契约 | completed | [M36-T01.md](../records/M36/M36-T01.md) |
| M36-T02 | 实现按目标端独立校验的模型就绪与发布规则 | completed | [M36-T02.md](../records/M36/M36-T02.md) |
| M36-T03 | 建立项目场景及多模型成员关系 API 与存储 | completed | [M36-T03.md](../records/M36/M36-T03.md) |
| M36-T04 | 实现项目场景授权和目标端可用目录 | completed | [M36-T04.md](../records/M36/M36-T04.md) |
| M36-T05 | 建设PC模型资产与项目场景管理界面 | completed | [M36-T05.md](../records/M36/M36-T05.md) |
| M36-T06 | 完成模型能力与场景配置跨项目自动化验收 | completed | [M36-T06.md](../records/M36/M36-T06.md) |
| M36-T07 | 为已登记 PC 模型补充运行验证与发布入口 | completed | [M36-T07.md](../records/M36/M36-T07.md) |
| M36-T08 | 支持项目模型双端独立分配与按端场景执行判定 | completed | [M36-T08.md](../records/M36/M36-T08.md) |
| M36-T09 | 更新本机8080开发服务并验证双端分配接口 | completed | [M36-T09.md](../records/M36/M36-T09.md) |
| M36-T10 | 补齐项目场景审批参数快照与修订绑定执行契约 | completed | [M36-T10.md](../records/M36/M36-T10.md) |
| M36-T11 | 更新本地场景服务并发布获授权的双测试版本 | completed | [M36-T11.md](../records/M36/M36-T11.md) |
| M36-T12 | 冻结场景套件成员与运行方案v2跨端契约 | completed | [M36-T12.md](../records/M36/M36-T12.md) |
| M36-T13 | 实现套件混合输入成员及运行方案持久化迁移 | completed | [M36-T13.md](../records/M36/M36-T13.md) |
| M36-T14 | 提供套件安装授权与单成员方案修订绑定运行接口 | completed | [M36-T14.md](../records/M36/M36-T14.md) |
| M36-T15 | 扩展管理后台套件成员输入与方案编辑审批 | completed | [M36-T15.md](../records/M36/M36-T15.md) |
| M36-T16 | 完成套件混合输入与单成员方案真实服务联合验收 | completed | [M36-T16.md](../records/M36/M36-T16.md) |
| M36-T17 | 支持多模型方案冻结参数与客户端能力协商授权 | completed | [M36-T17.md](../records/M36/M36-T17.md) |
| M36-T18 | 补齐联合识别方案后台配置与真实授权回归 | completed | [M36-T18.md](../records/M36/M36-T18.md) |
| M36-T19 | 颁发可续期且可撤权的单成员套件运行授权 | completed | [M36-T19.md](../records/M36/M36-T19.md) |

## 测试结果

- Harness单元测试：34项通过
- Harness validate：通过
- Harness render：通过
- M36-T19隔离PostgreSQL回归：记录为90个HTTP请求通过、PostgreSQL回归exit code 0
- 本机127.0.0.1:8080服务链接：14个API请求；单成员运行授权及撤权用例通过

## 验收证据

- harness/records/M36/M36-T19.md
- harness/records/M36/M36-T18.md
- harness/evidence/M36/M36-T16-acceptance.md
- harness/evidence/M36/M36-T18-live-postgres-http.json
- harness/evidence/M36/M36-T19-postgres-regression.json
- harness/evidence/M36/M36-T19-service-links-final-20261021-211259/result.json
- harness/evidence/M36/M36-T19-service-links-final-20261021-211259/api-trace.json

## 遗留风险

- 无；若存在遗留风险，必须在正式通过前改写本节并给出责任人和截止日期。
