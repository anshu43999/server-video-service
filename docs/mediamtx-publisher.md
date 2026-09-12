# MediaMTX 推流实现（M08-T03）

每个 `StreamSession` 持有一个 `MediaMTXPublisher`。首帧到达时按帧尺寸惰性创建 H.264 编码器，并将编码后的 Annex-B 数据写入长驻 FFmpeg 子进程，由 FFmpeg 通过 RTSP 推送到固定路径：

`{MEDIAMTX_RTSP_URL}/{stream_id}`

发布器遇到 BrokenPipe 或进程异常会关闭旧进程，进入 `reconnecting`，按 `MEDIAMTX_RECONNECT_DELAY` 重试 `MEDIAMTX_MAX_RECONNECT_ATTEMPTS` 次；最终失败时状态为 `failed`。发布器关闭或未启用时状态为 `idle`。

MediaMTX 控制 API 是可选的。设置 `MEDIAMTX_API_URL=http://127.0.0.1:9997` 后，服务会周期性查询 `/v3/paths/list`，将对应路径的读取者数量暴露为 `viewers`。控制 API 未启用时观看者数安全回落为 0。

默认 `MEDIAMTX_ENABLED=false`，避免开发环境在未启动媒体服务器时阻塞 JPEG/MJPEG 诊断链路。部署 MediaMTX 后设置 `MEDIAMTX_ENABLED=true`，并按需设置 `MEDIAMTX_FFMPEG_PATH`、RTSP/API 地址。

`GET /api/streams` 与 `/api/metrics` 的每路条目新增：`publish_state`、`viewers`、`publish_path`、`publish_url`、`frames_published`、`publish_error`。

播放端通过 `GET /api/streams/{stream_id}/playback` 获取动态入口，不应硬编码媒体地址。响应包含：

- `whep.url`：`http(s)://<media-host>:8889/{stream_id}/whep`，生产播放首选；
- `llhls.url`：`http(s)://<media-host>:8888/{stream_id}/index.m3u8`，WHEP 失败时回退；
- `rtsp.url`：`rtsp://<media-host>:8554/{stream_id}`，始终带 `diagnostics_only: true`，仅供 VLC/ffprobe；
- 各协议的 `available`：仅当 `MEDIAMTX_ENABLED=true` 且发布状态为 `connected` 时为 `true`。未发布或重连中仍返回地址，客户端应按 `available` 和协议顺序处理。

默认地址从 `MEDIAMTX_RTSP_URL` 的主机派生。跨域或 TLS 部署可设置 `MEDIAMTX_WHEP_URL`、`MEDIAMTX_LLHLS_URL` 覆盖 HTTP 基地址，并用 `MEDIAMTX_HTTP_SCHEME=https` 选择默认 HTTPS 方案。

本地单元测试覆盖命令构造、禁用安全空操作和 BrokenPipe 重连；真实 MediaMTX 端到端首帧/观看者数验证留待 M08-T06 编排完成后执行。
