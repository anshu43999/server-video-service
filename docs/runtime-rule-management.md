# 运行时规则管理与能力绑定（M11-T07）

服务端通过 `/api/rules` 提供规则的新增、修改、删除和查询。修改不会重启进程，
`ruleVersion` 从 1 开始递增；每次 create/update/delete/bind 都写入内存审计链，
可由 `/api/rules/audit` 查询。部署重启后的持久化由后续运维任务负责。

规则的 `requires` 使用统一能力枚举：`BOX`、`MASK`、`TRACK`、`SCALAR`、
`POLYGON_ROI`、`LINE_ROI`。绑定前调用 `POST /api/rules/{ruleId}/validate` 做
无副作用检查；实际绑定使用 `/bindings`。能力不足返回 HTTP 409 和结构化
`CAPABILITY_UNSATISFIED`（含 `missing`），未实现算子返回
`OPERATOR_NOT_IMPLEMENTED`，不会被显示成已启用规则。

管理页规则面板在 Live API 模式读取规则和审计记录，并将拒绝原因直接展示给管理员。
