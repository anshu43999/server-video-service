# 生产安全与流量保护

多项目版本的部署停写、恢复、密钥/设备凭据轮换、审计留存及值班告警门禁见
[M33-T17 发布与回滚手册](m33-t17-release-runbook.md)。隔离演练不构成线上发布授权。

## TLS / HTTPS / WSS

推荐由 Nginx、Caddy 或云负载均衡终止 TLS，再将内网 HTTP/WebSocket 转发到 Uvicorn：

```text
App -- HTTPS/WSS --> TLS reverse proxy -- HTTP/WS --> video-service:8080
```

反向代理必须转发 `Upgrade`、`Connection` 和鉴权请求头；公网不应直接暴露 Uvicorn 端口。管理页面使用 HTTPS 打开时，PC同源预览和告警 WebSocket 也必须使用 HTTPS/WSS，避免浏览器 mixed content。

## 应用层保护

- `MAX_INPUT_FPS` 默认 30，超过后丢弃当前帧并记录错误；
- 单帧消息最大 5 MiB，最大有效尺寸 1920×1080；
- PC预览最高5fps、宽1280、有界快照缓存；网关仍需限制请求速率。`MAX_OUTPUT_SUBSCRIBERS` 已移除；
- 生产环境使用账号登录签发的动态 Session；不得设置开发专用的 `ADMIN_TOKEN`、`MOBILE_TOKEN`，并通过网关限制来源 IP、请求速率和连接时长；
- 不把令牌放在 URL，日志中不得输出令牌和完整 RTSP 凭据。

## 开发环境静态令牌

本机联调可显式使用以下配置，便于脚本和 WebSocket 测试：

```dotenv
DEPLOYMENT_ENV=development
ADMIN_TOKEN=development-admin-token
MOBILE_TOKEN=development-mobile-token
```

静态值只在 `DEPLOYMENT_ENV=development` 时参与鉴权。`DEPLOYMENT_ENV=production` 时服务端会忽略静态客户端令牌，生产容器入口还会拒绝携带这两个变量启动；模型转换容器使用的 `CONVERTER_TOKEN` 不受此规则影响。

## 反向代理示例（Nginx）

本服务的 API 根路径固定为 `/aiyoloapi`。当同一个 Nginx 承载多个项目时，直接把该路径原样转发给 FastAPI，不要剥离或重写前缀。管理后台仍通过 `/admin/` 访问，但其 HTTP 和 WebSocket 请求都会直接使用 `/aiyoloapi/...`。完整示例见 `deploy/nginx/aiyolo.conf.example`。

```nginx
location /aiyoloapi/ {
    proxy_pass http://127.0.0.1:18080;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 3600s;
}
```

`proxy_pass` 的端口后不要添加 `/`，这样上游会收到完整的 `/aiyoloapi/...` 路径。本地直接访问 `http://127.0.0.1:18080/admin/` 与线上使用相同的 API 契约。

只代理单个 API 路径时也可以使用下面的精简规则：

```nginx
location /aiyoloapi/ {
    proxy_pass http://127.0.0.1:18080;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 3600s;
}
```

上线前仍需使用真实证书、访问控制和压测结果替换示例值。

## PC预览与退役分发边界

现行决策为 [ADR-003](adr-003-analysis-alerts-only.md)。PC预览仅接受同源账号 Cookie 和当前项目 `project.streams.view`，拒绝 Bearer（即使同时存在 Cookie）及跨站请求，编码后复验权限。返回 `Cache-Control: no-store, private`；网关不得缓存画面或把其他项目内容混用。合法账号在浏览器访问仍受相同权限约束，不宣称按物理设备类型隔离。

旧媒体分发端口全部移出部署；不再配置播放 CORS、媒体 Token、STUN/TURN。旧 `/internal/media/authorize` 是无条件403墓碑，不查账号/项目/存储，不存在内部发布例外。旧 HTTP 播放410，逐帧输出/检测 WS1008，不能通过旧环境变量重新开启。

输入 RTSP 解码、已授权 ingest、告警 WS、MinIO受保护证据（含已存短视频）、模型下载仍保留。日志/指标不得输出 RTSP 完整凭据、会话、模型权重或证据原图。监控输入、推理和告警持久化/投递状态；兼容发布指标的 `retired/0` 不应触发发布器故障告警。

旧容器和防火墙不会因 YAML 删除自动消失；经本地验收和维护批准后按 [升级手册](media-retirement-upgrade.md) 精确清理，不影响业务卷、数据库和输入源。
