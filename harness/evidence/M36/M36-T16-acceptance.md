# M36-T16 联合验收记录

日期：2026-10-21  
范围：隔离项目、真实 HTTP 服务和一次性 PostgreSQL；未连接 Default Project、开发库或生产容器。

## 结果

服务端联合验收脚本 `tools/accept_m36_t16_live.py` 完成 36 个检查，使用两个隔离项目和 `admin`、`gly`、`ptcy` 三种角色。覆盖场景创建/编辑/审批/目录、单成员方案解析、精确产物与参数下载、审批/修订变化、撤权、旧协议拒绝、重复/跨方案成员语义及并发修订；PostgreSQL 留存套件/方案数据和 23 条审计记录。逐请求状态码、requestId、项目/场景修订及解析快照见 `harness/evidence/M36/M36-T16-live-postgres-http.json`。

协议核验：套件契约版本 `2`，单成员方案解析客户端最低版本 `2`；解析路径为 `/aiyoloapi/projects/{project_id}/scenes/{scene_id}/plans/{plan_id}/resolve`，安装准备路径为 `/aiyoloapi/projects/{project_id}/scenes/{scene_id}/installation/prepare`。v1 客户端解析返回 HTTP 409 / `execution_mode_not_supported`。解析只提供授权快照，不颁发运行授权，也不代表服务端推理。

## 自动化验证

- 套件存储专项：5 项通过；参数并发/迁移专项：7 项通过。
- 套件安装/授权/迁移测试：37 项通过；旧协议拒绝回归：2 项通过。
- 契约、持久化、服务 API、授权、PostgreSQL 并发/迁移组合：58 项通过。
- 管理后台测试：122 项通过；`npm run build`（含类型检查）通过。
- Harness 单元测试：34 项通过。
- 真实 PostgreSQL + HTTP：36 项通过；证据 JSON 中记录 `planRows=6`、`auditRows=23`。

## 限制与风险

模型注册表中没有可独立验证的 PPE、火警等不同业务模型及现场图片/视频样本。本次仅使用内部测试授权范围内的 helmet 上传模型版本，并将模型槽映射用于套件/协议链路测试；这不构成不同业务模型的真实性、推理效果、精度或分发授权验收。没有运行图片/视频推理，也没有覆盖 API 27 设备端到端执行。后续 Android M107/T09 与 M108 仍需使用独立真实模型及许可明确的代表样本补齐；无法找到时应保留为环境/样本阻塞，不得以本记录替代。

真实服务与 PostgreSQL 一次性实例已停止；端口 `18081`、`55439` 不再监听。
