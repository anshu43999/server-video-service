# 模型市场目录与下载 API 契约

版本：`v1`（M09-T01，MVP）  
状态：冻结，供 `server-video-service` 与 Android App `M14-T02/M14-T03` 共用。

2026-09-08 增补（M26）：新增独立 `/api/conversion/*` 管理接口负责上传、后台处理与环境配置，目录/下载路径保持兼容。成对产物条目以 PT 为主产物，App 必须从 `artifacts` 中选择 Android TFLite；新增 `serverReady`、`androidReady`、`androidContract`、`placeholder` 字段。`androidReady` 只代表转换与电脑端预热通过，不代表 App 安装已接通。详见 `local-model-conversion.md`。下文原 M09 范围保留为历史基线，签名仍未实现。

## 1. 范围与边界

模型市场是服务端提供、App 消费的场景化目录。MVP 只负责目录元数据和模型产物下载；不负责训练、格式转换、端侧推理或签名发布。

**MVP 不含数字签名。** 客户端必须在下载完成后使用目录给出的 SHA-256 校验产物；签名、密钥、证书、灰度发布和签名错误码属于后续 M10，不得在本契约中假设已提供。

控制面基础地址为 `http(s)://<server-host>:8080`。所有接口均使用 UTF-8 JSON（下载接口除外）。

## 2. 鉴权与安全约束

- 移动端请求使用 `X-Video-Service-Token: <device-token>`。
- 管理后台或运维工具可使用 `Authorization: Bearer <admin-token>`；服务端部署可以按权限策略限制管理操作。
- 令牌只能出现在请求头，**不得放入 query、path、下载 URL 或日志**。
- 未配置令牌的开发环境可保持兼容模式；生产环境必须启用鉴权。
- `modelId` 和 `artifactId` 只允许作为 URL path segment 使用，客户端应进行 percent-encoding。
- 响应中的路径必须是 API URL 或相对下载地址，不得泄露服务器本机绝对路径。

## 3. 目录模型字段

目录列表和详情返回的模型对象使用下列字段。除标注“可选”外均为必填。

| 字段 | 类型 | 说明 |
|---|---|---|
| `modelId` | string | 稳定唯一标识，`[A-Za-z0-9][A-Za-z0-9._-]{0,127}` |
| `name` | string | 面向用户显示的名称 |
| `version` | string | 发布版本，不用于替代 `modelId` |
| `scenario` | string | 场景标识，如 `intrusion`、`smoke` |
| `purpose` | string | `development`、`business` 或其他服务端定义用途 |
| `runtime` | string | `server-onnx`、`server-pt`、`android-tflite` 等 |
| `labels` | string[] | 权重原始类别名，顺序即输出类别顺序 |
| `compatibleDevices` | string[] | 设备/API/ABI 适配声明，可为空 |
| `license` | object | `spdx`（可选）、`status`、`sourceUrl`（可选） |
| `artifacts` | object[] | 可下载产物，见下表 |
| `releaseEligible` | boolean | 是否允许当前部署用于发布 |

产物对象字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `artifactId` | string | 在该模型内唯一 |
| `format` | string | `pt`、`onnx`、`tflite` 等 |
| `platform` | string | `server` 或 `android` |
| `url` | string | 产物下载 API URL；不得含令牌 |
| `sizeBytes` | integer | 非负字节数 |
| `sha256` | string | 64 位十六进制 SHA-256，大写/小写均可，客户端比较时忽略大小写 |
| `contentType` | string | 可选 MIME 类型 |

为兼容 App `M14-T02` 已实现的解析器，目录模型**同时提供主产物别名**：`format`、`downloadUrl`、`sizeBytes`、`sha256`。这些字段等价于 `artifacts` 中 `platform` 与当前客户端匹配的首个产物；新客户端应优先使用 `artifacts`。

## 4. 接口

### 4.1 查询目录列表

`GET /api/models`

可选查询参数：`scenario=<scenario>`，按场景精确过滤。没有过滤时返回全部可见模型。

成功 `200`：

```json
{
  "models": [
    {
      "modelId": "site-intrusion-v1",
      "name": "异物入侵五类",
      "version": "1.0.0",
      "scenario": "intrusion",
      "purpose": "business",
      "runtime": "android-tflite",
      "labels": ["bottle", "bag", "box", "tool", "person"],
      "compatibleDevices": ["API 27+", "arm64-v8a", "armeabi-v7a"],
      "license": {"spdx": "LicenseRef-Enterprise", "status": "approved"},
      "artifacts": [{
        "artifactId": "android-arm64-int8",
        "format": "tflite",
        "platform": "android",
        "url": "/api/models/site-intrusion-v1/artifacts/android-arm64-int8/download",
        "sizeBytes": 12345678,
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "contentType": "application/octet-stream"
      }],
      "format": "tflite",
      "downloadUrl": "/api/models/site-intrusion-v1/artifacts/android-arm64-int8/download",
      "sizeBytes": 12345678,
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "releaseEligible": true
    }
  ]
}
```

空目录仍返回 `200` 和 `{"models":[]}`，客户端显示“暂无可用模型”，不得把它当成网络错误。

### 4.2 查询模型详情

`GET /api/models/{modelId}`

成功 `200` 返回单个模型对象（字段同 §3，必须包含完整 `artifacts`）。详情用于安装前展示和选择具体产物。

### 4.3 下载模型产物

`GET /api/models/{modelId}/artifacts/{artifactId}/download`

成功 `200` 返回二进制流，并设置：

- `Content-Type`：产物 `contentType` 或 `application/octet-stream`
- `Content-Length`：应等于 `sizeBytes`
- `Content-Disposition`：服务端建议提供安全文件名
- `X-Model-SHA256`：与目录 `sha256` 一致（辅助信息，客户端仍以目录值校验）

客户端应下载到临时文件，校验大小和 SHA-256 均通过后再原子移动到模型安装目录；校验失败的临时文件必须删除，不得标记为可激活模型。支持 HTTP `Range` 时可断点续传；MVP 不要求服务端必须支持 Range。

## 5. 错误响应与重试

JSON 错误统一为：

```json
{"error":{"code":"model_not_found","message":"model not found","request_id":"optional-id","retryable":false}}
```

兼容当前 FastAPI MVP 的 `{"detail":"..."}`，客户端应将其归一化为下表错误。

| HTTP | `error.code` | 含义 | 客户端建议 |
|---:|---|---|---|
| 401/403 | `authentication_required` / `authentication_failed` | 缺少或无效令牌 | 提示重新配置服务地址或令牌，不自动重试 |
| 404 | `model_not_found` | 模型或产物不存在 | 刷新目录；不重试同一 URL |
| 409 | `model_not_available` | 模型未发布或当前不可下载 | 提示稍后再试，按 `retryable` 决定 |
| 416 | `range_not_satisfiable` | 断点范围无效 | 删除临时文件后从头下载 |
| 429 | `rate_limited` | 下载/查询限流 | 指数退避并限制重试次数 |
| 500/502/503/504 | `internal_error` / `service_unavailable` | 服务端或上游暂时故障 | 有界指数退避；不得把 token 写入日志 |
| 413 | `artifact_too_large` | 请求或产物超过部署限制 | 不重试，提示联系管理员 |
| 422 | `invalid_model_request` | 参数或 manifest 不合法 | 修正请求，不重试 |

## 6. 与 Android M14 对接约定

- `M14-T02` 使用 `GET /api/models`，读取 `modelId`、`name`、`scenario`、`version`、`sizeBytes`、`license`、`compatibleDevices`、`format`、`downloadUrl`、`sha256`；服务端必须保留这些别名字段。
- `M14-T03` 使用详情中的 `artifacts` 选择适配 Android/API/ABI 的产物，下载后校验 `sizeBytes` 与 `sha256`。本契约不要求或假设签名字段。
- App 的下载器不得把 `X-Video-Service-Token` 拼接到 `downloadUrl`；每个请求都通过 header 注入。
- 服务端新增字段必须向后兼容；未知字段 App 应忽略。

## 7. 当前服务端实现说明（M09-T03）

- `GET /api/models` 支持可选的 `scenario` 精确匹配过滤；未知场景返回空数组而不是错误。
- `GET /api/models/{modelId}` 返回与列表项相同的公开字段，并保留完整 `artifacts` 数组。
- 目录查询在配置 `ADMIN_TOKEN` 或 `MOBILE_TOKEN` 后必须携带匹配令牌；管理工具可使用 `X-Admin-Token` 或 `Authorization: Bearer`，移动端使用 `X-Video-Service-Token`。
- 服务端从注册表读取文件并执行存在性/哈希检查，但查询响应只返回下载 API URL、大小和 SHA-256，不返回 `models/` 下的本机路径、Manifest 路径或其他本地文件定位信息。

## 8. 下载实现与运行时保护（M09-T04）

- `GET /api/models/{modelId}/artifacts/{artifactId}/download` 只解析注册表中已登记的产物；路径必须位于服务端 `models/` 目录内，禁止通过 `..`、绝对路径或符号链接逃逸。
- 开始传输前再次读取文件大小并计算 SHA-256；文件缺失、大小变化或摘要不一致返回 `409 model_not_available`，不会发送不符合目录契约的字节。
- 成功响应设置 `Content-Length`、安全的 `Content-Disposition` 文件名和 `X-Model-SHA256`。客户端仍应自行计算下载文件的大小与 SHA-256。
- 每个服务进程默认最多并发下载 2 个、每个客户端 60 秒最多 10 次。超限返回 `429 rate_limited` 和 `Retry-After`；可通过 `MODEL_DOWNLOAD_MAX_CONCURRENT`、`MODEL_DOWNLOAD_RATE_LIMIT`、`MODEL_DOWNLOAD_RATE_WINDOW_SECONDS`、`MODEL_DOWNLOAD_CHUNK_SIZE` 调整。
- 令牌只从 `X-Video-Service-Token`、`X-Admin-Token` 或 Bearer 请求头读取，下载 URL 与服务日志不包含令牌。多 worker 部署仍应在反向代理层配置全局带宽/并发限额。
