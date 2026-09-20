# 生产安全与流量保护

## TLS / HTTPS / WSS

推荐由 Nginx、Caddy 或云负载均衡终止 TLS，再将内网 HTTP/WebSocket 转发到 Uvicorn：

```text
App -- HTTPS/WSS --> TLS reverse proxy -- HTTP/WS --> video-service:8080
```

反向代理必须转发 `Upgrade`、`Connection` 和鉴权请求头；公网不应直接暴露 Uvicorn 端口。管理页面使用 HTTPS 打开时，MJPEG 和 WebSocket 地址也必须使用 HTTPS/WSS，避免浏览器 mixed content。

## 应用层保护

- `MAX_INPUT_FPS` 默认 30，超过后丢弃当前帧并记录错误；
- 单帧消息最大 5 MiB，最大有效尺寸 1920×1080；
- `MAX_OUTPUT_SUBSCRIBERS` 默认 4，超过后 HTTP 返回 429 或 WebSocket 关闭码 4429；
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

```nginx
location /api/streams/ {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 3600s;
}
```

上线前仍需使用真实证书、访问控制和压测结果替换示例值。

## 媒体服务器端口与暴露面

[ADR-002](adr-002-production-transport.md) 之后，部署拓扑增加 MediaMTX 进程，暴露面随之扩大：

| 端口 | 协议 | 暴露策略 |
|---|---|---|
| `:8889` | WebRTC / WHEP（HTTP 信令） | 生产播放入口，对外时经网关鉴权并使用 HTTPS |
| `:8189/udp` | WebRTC 媒体（`webrtcLocalUDPAddress`） | 必须放通，否则只能走 LL-HLS 回退 |
| `:8888` | LL-HLS | 回退入口，同样经网关鉴权并使用 HTTPS |
| `:8554` | RTSP | **只对诊断网络开放，不得暴露到公网** |
| `:8890` | SRT | 默认不对外；仅在启用服务端之间专用链路时开放 |
| `:1935` | RTMP | 默认不对外 |

- 控制面（`:8080`）与媒体面（`:8888`/`:8889`）分属不同暴露策略，不要用同一条规则放通；
- 管理页面使用 HTTPS 打开时，WHEP 与 LL-HLS 地址必须同为 HTTPS，避免 mixed content；
- 公网部署需要 STUN，可能需要 TURN；TURN 会把媒体带宽成本转回服务端，必须先核算再启用（ADR-002 未验证项 2）；
- 媒体服务器的配置文件、证书（`auto.crt`/`auto.key`）和推流凭据不得提交仓库。
