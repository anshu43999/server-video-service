# 移动端告警上报

Android 本地告警在用户确认或标记误报后，通过 `POST /api/alerts/mobile-ingest` 上报。请求必须携带操作员账号登录后获得的动态 Session，可通过 `X-Video-Service-Token` 兼容头传递；操作员 Session 不能调用管理员处置接口。

请求体包含 `eventId`、来源和主体、告警级别、时间戳、`effectiveThresholds`、`detectionResults`、`evidence`，以及可选的 `disposition`。`eventId` 支持 App 的 `local:...` 格式，重复提交按 eventId 幂等；最新检测和证据会更新，但已有处置历史不会被重置。

`evidence.snapshotDataUrl` 仅接受 PNG、JPEG 或 WebP 的 Base64 data URL，最大 8 MB，服务端将其放入 `evidence.snapshotUri` 供管理后台显示，不保存 App 私有绝对路径。服务端接收成功后返回 `202`，表示事件已经进入告警列表；管理页 WebSocket 的实时投递失败不影响事件接收。
