# 告警处置闭环与误报回流（M11-T09）

服务端提供只读告警查询与管理员处置接口。告警快照由运行时调用
`app.alerts.disposition.alert_disposition_store.register(event)` 登记；生产环境可用
数据库适配器替换当前进程内存储而不改变接口。

## 权限

- `GET /api/alerts`、`GET /api/alerts/{eventId}` 和误报导出允许 `X-Admin-Token` 或
  `X-Video-Service-Token`，用于后台和移动端只读查看。
- `POST` 处置接口只允许 `X-Admin-Token`。操作人从 `X-Operator-Id`（兼容
  `X-Actor`）读取，不接受请求体中的 actor，避免伪造审计身份。

## 处置接口

```text
POST /api/alerts/{eventId}/acknowledge
POST /api/alerts/{eventId}/false-positive
POST /api/alerts/{eventId}/close
```

请求体可带 `actedAtUs`（测试/回放用；缺省取服务端 UTC 微秒）、`screenshot`、
`evidence`、`effectiveThresholds`、`detectionResults` 和 `note`。响应事件的
`disposition` 含当前状态、操作人与时间戳，以及追加的 `history`。

## 误报数据集导出

`GET /api/alerts/false-positives/export` 返回
`aiyolo-false-positive-v1` JSON。每条 entry 包含截图引用、生效阈值、原始检测
结果、来源/主体和规则版本，可直接交给标注或再训练流水线。导出前递归移除
token/secret/password/authorization 等字段，并将 Windows、Unix 和 `file:` 绝对
路径转换为 `evidence/<basename>`；不会泄漏服务端工作目录。

误报动作会将事件置为 `ENDED`，但保留原始事实字段和完整操作历史，便于审计。
