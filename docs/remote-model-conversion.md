# 远程模型转换 HTTP 协议

对应任务：`M27-T01`，服务端实现由 `M00-T07` 补齐。调用方是视频服务，提供方可以部署在本机、局域网 GPU/CPU 主机或独立转换服务器。统一生产编排使用同一 `compose.yml` 项目中的 `model-converter` 容器，远程 URL 是 HTTP API endpoint，不冒充 Python 路径。

## 配置与秘密

`ConversionConfig.mode=remote` 时使用：

- `remote_endpoint`: 服务根地址，默认只允许 HTTPS；开发环境显式设置 `remote_allow_insecure_http=true` 才允许 HTTP。
- `remote_token_env`: Bearer 令牌所在的服务进程环境变量名，默认 `AIYOLO_REMOTE_CONVERSION_TOKEN`。
- `remote_poll_interval_seconds`: 查询间隔，范围 0.5 至 30 秒。
- `remote_verifier_mode`: 下载后的复验方式，`wsl` 或 `local`。
- `python_path`、`distribution`: 复验虚拟环境；即使转换发生在远端也必须配置，避免信任远端自报的 tensor 元数据。
- `timeout_seconds`: 整个提交、排队、转换和下载流程的总截止时间。
- `input_size`、`calibration_data`: 与本机转换含义一致。

配置文件、任务快照、日志与 API 只保存环境变量名，不保存或回显令牌值。endpoint 禁止 URL 内凭据、query 和 fragment。跨主机生产环境不得开启明文 HTTP。同一 `compose.yml` 中的调用使用不发布宿主机端口的内部网络和独立 Bearer Token，允许显式开启内部 HTTP；一旦转换服务跨主机或端口被发布，必须改为 HTTPS。

仓库内的提供方实现位于 `converter_service/`，镜像定义为 `Dockerfile.converter`。服务持久化任务、源 PT 与产物到 `converter-data` 卷，校准集通过只读目录挂载；默认单 Worker 串行执行，避免多个导出进程争用内存。API 不返回本机路径、日志或堆栈。

## API

所有请求使用 `Authorization: Bearer <token>`，响应为 UTF-8 JSON，错误体为 `{"code":"...","message":"...","retryable":true|false}`。服务不得返回堆栈、绝对路径或令牌。

### 健康检查

`GET /v1/health`

返回 `200`：`{"status":"ok","protocolVersion":1,"capabilities":["yolo-detect-to-tflite-int8"]}`。

### 幂等提交

`POST /v1/conversions?inputSize=640&calibrationData=coco8.yaml`

- `Content-Type: application/octet-stream`
- `Content-Length`: PT 字节数
- `Idempotency-Key`: 调用方本地任务 ID 与源 PT SHA-256 组合后的稳定 SHA-256
- `X-Source-SHA256`: 源 PT SHA-256
- body: 原始 `.pt` 字节流

返回 `202` 或命中幂等记录时返回 `200`：`{"jobId":"...","status":"queued|running|succeeded|failed|cancelled"}`。相同 Idempotency-Key 与不同源哈希组合必须返回 `409 idempotency_conflict`。

### 状态与取消

- `GET /v1/conversions/{jobId}`
- `DELETE /v1/conversions/{jobId}`

成功状态必须包含 `result`：标签顺序、输入/输出 tensor 名称、shape、dataType、quantization、TFLite 大小和 SHA-256，以及相对产物 URL。失败包含稳定错误码与 `retryable`。取消为幂等操作。

### 产物下载

`GET /v1/conversions/{jobId}/artifact`

只接受任务响应中的同源相对 URL，不跟随重定向。视频服务流式写入当前任务尝试目录，限制接收字节数，并再次校验声明大小和 SHA-256。随后必须用配置的本地/WSL LiteRT 验证环境重新检查单输入、单输出、NCHW float32、`[1, 4+类别数, N]`、预热非有限值和标签顺序；远端自报的验证结果不能替代本地复验。

## 错误与重试

- `401/403`: 鉴权错误，不自动重试。
- `408/429/5xx`、连接中断：在总截止时间内有限重试，遵守 `Retry-After` 上限。
- `409 idempotency_conflict`、`422 unsupported_model|invalid_request`: 不重试。
- 本地服务停止：请求远端取消；本地任务记为 interrupted，可由管理员重试且复用同一幂等键语义。
- 大小、SHA-256 或本地张量复验失败：删除隔离产物，不登记 Android artifact，不影响已通过验证的服务端 PT。
