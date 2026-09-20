# 告警投递通道（M11-T08）

`app.alerts.delivery.AlertDeliveryService` 是告警生命周期与通知基础设施之间的
隔离层。事件生成方调用 `dispatch(event, channels)` 即可立即返回 delivery ID；
每个通道在独立后台任务中执行，失败最多重试 `max_attempts` 次（默认 3 次），
重试耗尽只产生 `failed` 回执，不抛回事件生成路径。

## 通道

| 名称 | 用途 | 实现 |
|---|---|---|
| `management` | 管理页实时告警推送 | 有界内存订阅队列，WebSocket `/api/alerts/ws` |
| `app` | App 内通知 | 独立有界内存订阅队列，WebSocket `/api/alerts/notifications` |
| `email` | 邮件 | `EmailAdapter` 本地假实现 |
| `sms` | 短信 | `SmsAdapter` 本地假实现 |
| `enterprise_im` | 企业 IM | `EnterpriseIMAdapter` 本地假实现 |

邮件、短信和企业 IM 通过 `credential_provider` 注入凭据。凭据只在发送时读取，
不保存在事件、投递回执、日志或仓库中。生产 provider 可替换本地假实现而无需
修改告警引擎。

项目明确不提供 Webhook/上游回调适配器；`webhook` 不是可用通道名。

## HTTP 接口

- `POST /api/alerts/test-delivery`（管理令牌）接受 `{event, channels}`，返回 `202`
  和 delivery IDs，仅负责排队。
- `GET /api/alerts/delivery/status`（管理令牌）返回通道订阅数、待处理数和最近
  回执；不返回凭据。
- 管理页 WebSocket 使用管理员动态 Session（同源 Cookie 或 Bearer）。
- App WebSocket 使用操作员动态 Session，可通过 `X-Video-Service-Token` 兼容头传递该动态访问令牌。
- 静态 `ADMIN_TOKEN`、`MOBILE_TOKEN` 仅用于开发环境测试，生产环境不接受。

WebSocket 事件形态为：

```json
{"type":"alert","event":{"eventId":"evt-123","severity":"MAJOR"}}
```

管理页和 App 队列彼此独立；慢客户端只丢弃自身队列中最旧的消息，不会阻塞其他
订阅者或事件生成。
