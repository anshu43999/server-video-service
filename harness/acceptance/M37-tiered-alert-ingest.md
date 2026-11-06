---
major_task_id: M37
result: passed
owner: codex
accepted_at: 2026-10-20T14:43:49+08:00
---

# M37 移动端告警分级上传接收与证据治理测试验收报告

## 验收结论

**通过**

完成本轮分级上传接收与证据治理：真实HTTP、远程PostgreSQL/MinIO及API27联合验收通过；按保留原件的显式金样映射验收，智能复核不在本轮范围，未部署生产

## 验收标准

- [x] 与Android M105-T01共同冻结并引用同一版本API契约与金样，事实、处置、缩略图、原图分别具备明确路由、项目授权、幂等身份、乱序处理、错误分类和兼容策略；两端完成记录互相引用契约版本/哈希及评审证据
- [x] 无处置事实以OPEN保存并纳入统计，来源分组及各自分母可验证；处置增量和事实重放不丢字段、不重置既有处置
- [x] 证据独立受鉴权上传和读取，缩略图/原图可同时存在；对象身份至少区分项目、事件、证据类型及内容版本/摘要，重复与并发上传安全，不产生覆盖、孤儿对象或base64持久化
- [x] 证据留存策略覆盖对象和数据库引用，明确待同步保护上限、误报/样本保留期限及可配置例外；干跑、审计、失败重试和引用/并发保护可验证
- [x] 修复路径证据引用规范化和base64进入反馈/训练导出的问题，保留受鉴权引用、缺失原因与审计语义
- [x] 服务端测试、数据库迁移、前端类型检查/构建及与Android M105-T08共用金样的跨端联调通过；真实PostgreSQL、MinIO等本轮所需环境证据如实记录，不以模拟结果替代
- [x] 按2026-10-20用户确认，仅调整本轮联合验收范围：智能复核、真实供应商联调、复核重试及复核触发原图上传不纳入本轮专项验收，供应商endpoint/key不是关闭M37/M105的门禁；现有功能代码、数据、历史完成记录与既有自动化测试保持不变。范围变更记录：../harness/decisions/20261020-m37-m105-acceptance-scope.md

## 小任务完成记录

| ID | 小任务 | 状态 | 记录 |
|---|---|---|---|
| M37-T01 | 冻结分级上传服务端接收契约 | completed | [M37-T01.md](../records/M37/M37-T01.md) |
| M37-T02 | 支持无处置事件入库并按来源分组统计 | completed | [M37-T02.md](../records/M37/M37-T02.md) |
| M37-T03 | 新增受鉴权的证据图片独立上传接口 | completed | [M37-T03.md](../records/M37/M37-T03.md) |
| M37-T04 | 建立证据对象留存与清理策略 | completed | [M37-T04.md](../records/M37/M37-T04.md) |
| M37-T05 | 修复证据引用转义与base64图像入库 | completed | [M37-T05.md](../records/M37/M37-T05.md) |
| M37-T06 | 复核失败结果可重试 | completed | [M37-T06.md](../records/M37/M37-T06.md) |
| M37-T07 | 完成分级上传接收与证据治理回归验收 | completed | [M37-T07.md](../records/M37/M37-T07.md) |

## 测试结果

- 35个真实HTTP步骤及五阶段API27通过；Room/DB/MinIO三对象摘要一致，处置重放无重复，测试前缀最终余数0
- 服务端53项、后台119项和类型检查/构建、Harness34项通过；Android JVM877项、设备媒体36项、Debug/Lint/Harness38项通过

## 验收证据

- docs/m37-t07-tiered-acceptance.md
- evidence/M37/M37-M105-joint-final/result.json
- evidence/M37/M37-M105-final-regression.txt
- evidence/M37/M37-T07-admin-tests.txt
- evidence/M37/M37-T07-admin-build.txt

## 遗留风险

- 无；若存在遗留风险，必须在正式通过前改写本节并给出责任人和截止日期。
