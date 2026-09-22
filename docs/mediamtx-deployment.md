# MediaMTX 编排与端口策略（M08-T06）

根目录唯一的 `compose.yml` 会同时启动 `video-service`、`model-converter`、PostgreSQL 与 MediaMTX 1.20.1。服务均使用 `restart: unless-stopped`；MediaMTX 通过健康检查后，视频服务才开始推流。媒体进程或容器异常退出时由 Compose 自动拉起，发布器（M08-T03）会在首帧到达后重新建立 RTSP 发布。

## 控制面与媒体面

Compose 的控制面容器端口固定为 `8080`。未覆盖时宿主机安全回退为
`127.0.0.1:8080`；当前 `.env.example` 的直接 HTTP 示例映射为
`0.0.0.0:18080`。使用直接 HTTP 模式时必须通过安全组或防火墙限制来源；使用
Nginx/Caddy/云网关时可将控制面改回本机绑定。媒体面独立暴露，可使用不同规则：

| 入口 | 默认绑定 | 用途 |
|---|---|---|
| `CONTROL_PORT`（宿主机默认 8080，示例 18080） | `CONTROL_BIND_ADDRESS=127.0.0.1`（示例 0.0.0.0） | FastAPI 控制面、管理页和 WebSocket |
| `MEDIA_WHEP_PORT`（8889） | `MEDIA_BIND_ADDRESS=0.0.0.0` | WebRTC/WHEP 播放 |
| `MEDIA_LLHLS_PORT`（8888） | `MEDIA_BIND_ADDRESS=0.0.0.0` | LL-HLS 回退 |
| `MEDIA_WEBRTC_UDP_PORT/udp`（8189） | `MEDIA_BIND_ADDRESS=0.0.0.0` | WebRTC 媒体包 |
| `DIAGNOSTIC_RTSP_PORT`（8554） | `DIAGNOSTIC_BIND_ADDRESS=127.0.0.1` | VLC/ffprobe 诊断，不应公网开放 |
| `SRT_PORT/udp`（8890） | `SRT_BIND_ADDRESS=127.0.0.1` | 默认关闭，仅专用链路 |

MediaMTX 控制 API `:9997` 仅通过 Compose 的 `control` 内部网络提供给 `video-service`，没有 `ports` 映射，不应由网关转发。

## 配置与证书

仓库只包含无密钥模板 [mediamtx.yml.example](../deploy/mediamtx/mediamtx.yml.example)。生产部署应复制为被 `.gitignore` 忽略的 `deploy/mediamtx/mediamtx.yml`，或设置 `MEDIAMTX_CONFIG` 指向外部挂载文件，然后在该文件中配置媒体鉴权、TLS 证书和公网主机名。证书文件（`*.crt`、`*.key`）同样被忽略，禁止提交令牌、密码或私钥。

```bash
cp deploy/mediamtx/mediamtx.yml.example deploy/mediamtx/mediamtx.yml
# 在 .env 中设置 MEDIAMTX_CONFIG=./deploy/mediamtx/mediamtx.yml
bash deploy/deploy.sh config
bash deploy/deploy.sh up
bash deploy/deploy.sh logs mediamtx
```

如需对外使用 WHEP/LL-HLS，应将 TLS 终止放在网关，并把 `MEDIAMTX_WHEP_URL`、`MEDIAMTX_LLHLS_URL` 设置为网关的 HTTPS 基地址；不要直接把 Uvicorn 或 MediaMTX 控制 API 暴露到公网。

## 运维检查

```bash
bash deploy/deploy.sh config
bash deploy/deploy.sh status
bash deploy/deploy.sh logs mediamtx
```

`docker compose config` 应显示 `bluenviron/mediamtx:1.20.1`、`restart: unless-stopped`、独立的控制/媒体网络和上述端口。真实公网部署仍需补充网关鉴权、证书、STUN/TURN 和压测结果；这些不在本任务中伪造。
