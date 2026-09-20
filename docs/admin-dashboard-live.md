# 管理后台真实统计

管理后台的总览、数据看板和系统诊断读取真实业务数据，不再使用固定统计数字。统计接口为：

```http
GET /api/dashboard/stats?range=today
Authorization: Bearer <dynamic-access-token>
```

`range` 支持 `today`、`7d` 和 `30d`。管理页面同源访问时使用登录后的 HttpOnly Session Cookie，运维工具也可通过 Bearer 携带动态访问令牌；接口不会把令牌写入 URL 或响应。开发环境仍可使用 `X-Admin-Token` 携带静态测试令牌。

## 统计口径

- `today` 从服务器本地时区当天 00:00 统计到当前时间。
- `7d` 和 `30d` 包含当前自然日，分别从第 7 天或第 30 天的 00:00 统计到当前时间。
- 告警总量、严重告警、处置数量、处置率、平均响应、类别排行和时间趋势来自 PostgreSQL 的 `alert_events`。
- 复核调用、结论、失败原因和额度配置来自 PostgreSQL 的复核记录与配置。
- 视频流数量和状态来自当前服务进程，CPU、内存、磁盘及可用的 GPU 数据来自实时系统指标。
- `ACKNOWLEDGED`、`FALSE_POSITIVE` 和 `CLOSED` 计入已处置；平均响应只统计存在有效处置时间且时间不早于告警发生时间的样本。
- 严重告警包括 `CRITICAL` 和 `MAJOR`。类别优先使用告警展示名，其次使用标签、规则 ID，均缺失时归为“未分类”。

当前系统没有独立持久化逐帧检测事件历史，因此看板展示的是“持久化告警事件”，不会把实时检测帧数量伪装成历史检测统计。若后续需要检测吞吐、命中率或漏报分析，应单独设计检测遥测表和数据保留策略。

## 空值与故障

PostgreSQL 在所选范围内没有告警时，计数与处置率显示 `0`，图表显示“暂无数据”；没有已处置样本时，平均响应显示“暂无已处置样本”；运行环境未提供 GPU 指标时显示“不可用”。统计查询失败时接口返回 `503` 和错误码 `dashboard_stats_unavailable`，管理页显示“统计不可用”，不会回退到 Mock 数字。

示例响应：

```json
{
  "range": "today",
  "dataSource": "postgresql",
  "summary": {
    "totalEvents": 0,
    "severeAlerts": 0,
    "handledEvents": 0,
    "resolutionRate": 0,
    "averageResponseMinutes": null
  },
  "streams": {"total": 0, "online": 0, "waiting": 0, "errors": 0},
  "categories": [],
  "trend": [],
  "verification": {"used": 0, "limit": 0, "conclusions": {}, "failures": {}}
}
```
