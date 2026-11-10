# 模型市场目录与下载 API 契约

类型：当前领域接口说明，对应 App 需求基线 PR-03/04/06/07。M112-T02 增量见末节；不单独定义产品需求。

版本：`v2`（M98-T01，模型版本生命周期扩展；M36 的目标端能力增量见 v3 契约）
状态：冻结，供 `server-video-service` 与 Android App `M14-T02/M14-T03/M98-T03/M98-T04` 共用。

v2 在保留 v1 顶层目录字段和旧下载路径的同时，将发布对象唯一键提升为
`modelId + version`。完整生命周期、端云对账状态和升级回滚语义见
`E:/aiyolo/mobile-app/docs/模型版本生命周期与端云对账契约.md`。

当前版本：独立 `/aiyoloapi/conversion/*` 管理接口负责 PT 上传、后台处理、校准集和环境配置；目录/下载
路径保持兼容。成对产物条目以 PT 为服务端主产物，App 必须从 `artifacts` 中选择 Android
TFLite；`serverReady`、`androidReady`、`androidContract` 和 `calibrationDataset` 用于描述
服务端验证、移动端签名状态和校准集快照。校准集快照记录所选档案的 ID、版本、图片数、大小、
内容 SHA-256、受控 YAML 相对路径与内置标记，不代表客户端可以直接访问服务器文件路径。详见
`local-model-conversion.md` 和 `docker-deployment.md` 附录 C。

M36-T01 冻结的模型端能力、PC/移动端分别就绪、项目场景及多模型成员配置语义见
[`model-capabilities-and-scenes-v1.md`](model-capabilities-and-scenes-v1.md)。该契约是 v2 的增量扩展；
实际 API/存储行为须由后续 M36 实现任务交付，当前文档不表示同步/异步多模型推理已支持。

## 1. 范围与边界

模型市场是服务端提供、App 消费的场景化目录。MVP 只负责目录元数据和模型产物下载；不负责训练、格式转换、端侧推理或签名发布。

Android 动态安装要求客户端校验目录中的 SHA-256，并在 `androidReady=true` 且
`signatureStatus=signed` 时使用与 App 内置公钥匹配的 Ed25519 Manifest。未配置签名时，
服务端仍可提供 PT 和未签名 TFLite 供管理员诊断下载，但客户端不得安装。

容器内控制面端口为 `8080`；直接 HTTP 部署示例通常通过宿主机 `18080` 对外发布，实际地址
以部署 `.env` 的 `CONTROL_PORT` 为准。所有接口均使用 UTF-8 JSON（下载接口除外）。

## 2. 鉴权与安全约束

- 移动端请求使用账号登录后签发的动态 Session，可通过 `X-Video-Service-Token: <access-token>` 兼容头传递。
- 管理后台使用同源 HttpOnly Cookie，运维工具可使用 `Authorization: Bearer <access-token>`。
- 令牌只能出现在请求头，**不得放入 query、path、下载 URL 或日志**。
- 开发环境可配置静态 `ADMIN_TOKEN`、`MOBILE_TOKEN` 简化测试；生产环境强制禁用静态客户端令牌并使用动态账号 Session。
- `modelId` 和 `artifactId` 只允许作为 URL path segment 使用，客户端应进行 percent-encoding。
- 响应中的路径必须是 API URL 或相对下载地址，不得泄露服务器本机绝对路径。

### 2.1 项目授权投影（M33）

平台目录仍由平台超级管理员全局治理；项目成员访问项目路径时，只能看到该项目按场景批准的
`modelId + version`。项目负责人通过项目模型分配接口选择已发布版本、参数平台和参数修订，
服务端保存不可变批准参数快照；项目用户只能读取批准快照和下载启用版本，不能读取负责人尚未
批准的工作配置，也不能上传、发布、撤回、卸载或迁移全局模型资产。

项目目录、版本详情、产物下载和流绑定均重新检查项目生命周期及分配状态。未分配、已停用、
项目外或生命周期不可用的对象按项目范围返回 404/403，不得通过平台目录的同族其他版本绕过
授权。项目流持久化精确模型版本；撤权、撤回或暂停后，运行时在推理前后重新授权，失效结果
丢弃并回退原图。

## 3. 目录模型字段

目录列表和详情返回的模型对象使用下列字段。除标注“可选”外均为必填。

| 字段 | 类型 | 说明 |
|---|---|---|
| `modelId` | string | 稳定唯一标识，`[A-Za-z0-9][A-Za-z0-9._-]{0,127}` |
| `name` | string | 面向用户显示的名称 |
| `version` | string | 发布版本，不用于替代 `modelId` |
| `scenario` | string | 场景标识，如 `intrusion`、`smoke` |
| `runtime` | string | `server-onnx`、`server-pt`、`android-tflite` 等 |
| `labels` | string[] | 权重原始类别名，顺序即输出类别顺序 |
| `compatibleDevices` | string[] | 设备/API/ABI 适配声明，可为空 |
| `license` | object | `spdx`（可选）、`status`、`sourceUrl`（可选） |
| `artifacts` | object[] | 可下载产物，见下表 |
| `releaseEligible` | boolean | 是否允许当前部署用于发布 |
| `calibrationDataset` | object/null | 可选；INT8 转换使用的不可变校准集版本与内容哈希快照 |

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

`GET /aiyoloapi/models`

可选查询参数：`scenario=<scenario>`，按场景精确过滤。没有过滤时返回全部可见模型。

成功 `200`：

```json
{
  "models": [
    {
      "modelId": "authorized-scene-v1",
      "name": "已授权场景检测模型",
      "version": "1.0.0",
      "scenario": "intrusion",
      "runtime": "android-tflite",
      "labels": ["bottle", "bag", "box", "tool", "person"],
      "compatibleDevices": ["API 27+", "arm64-v8a", "armeabi-v7a"],
      "license": {"spdx": "LicenseRef-Enterprise", "status": "approved"},
      "artifacts": [{
        "artifactId": "android-arm64-int8",
        "format": "tflite",
        "platform": "android",
        "url": "/aiyoloapi/models/authorized-scene-v1/artifacts/android-arm64-int8/download",
        "sizeBytes": 12345678,
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "contentType": "application/octet-stream"
      }],
      "format": "tflite",
      "downloadUrl": "/aiyoloapi/models/authorized-scene-v1/artifacts/android-arm64-int8/download",
      "sizeBytes": 12345678,
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "releaseEligible": true
    }
  ]
}
```

空目录仍返回 `200` 和 `{"models":[]}`，客户端显示“暂无可用模型”，不得把它当成网络错误。

### 4.2 查询模型详情

`GET /aiyoloapi/models/{modelId}`

成功 `200` 返回单个模型对象（字段同 §3，必须包含完整 `artifacts`）。详情用于安装前展示和选择具体产物。

### 4.3 下载模型产物

`GET /aiyoloapi/models/{modelId}/artifacts/{artifactId}/download`

成功 `200` 返回二进制流，并设置：

- `Content-Type`：产物 `contentType` 或 `application/octet-stream`
- `Content-Length`：应等于 `sizeBytes`
- `Content-Disposition`：服务端建议提供安全文件名
- `X-Model-SHA256`：与目录 `sha256` 一致（辅助信息，客户端仍以目录值校验）

客户端应下载到临时文件，校验大小和 SHA-256 均通过后再原子移动到模型安装目录；校验失败的临时文件必须删除，不得标记为可激活模型。支持 HTTP `Range` 时可断点续传；MVP 不要求服务端必须支持 Range。

### 4.4 卸载模型

`DELETE /aiyoloapi/models/{modelId}`

仅管理员可调用。成功后从目录移除模型，并删除未被其他目录条目共享的本地产物；模型参数及审计历史保留。当前激活模型或仍被任一视频流绑定的模型返回 `409 model_in_use`，管理员必须先切换默认模型或流绑定后重试。

成功 `200` 返回卸载和文件清理摘要：

```json
{
  "modelId": "authorized-scene-v1",
  "uninstalled": true,
  "deletedFiles": 2,
  "missingFiles": 0,
  "retainedSharedFiles": 1,
  "cleanupFailures": []
}
```

目录条目移除后若个别文件因操作系统占用无法删除，`cleanupFailures` 返回安全文件名，响应不暴露绝对路径。

### 4.5 多版本目录、下载和生命周期

v2 新增以下接口：

```text
GET    /aiyoloapi/models/{modelId}/versions
GET    /aiyoloapi/models/{modelId}/versions/{version}
GET    /aiyoloapi/models/{modelId}/versions/{version}/artifacts/{artifactId}/download
DELETE /aiyoloapi/models/{modelId}/versions/{version}
POST   /aiyoloapi/models/{modelId}/versions/{version}/deprecate
POST   /aiyoloapi/models/{modelId}/versions/{version}/revoke
```

同一 `modelId` 可以保留多个不可变 `version`。`GET /aiyoloapi/models` 默认返回模型族的
最新可安装版本；版本列表接口返回完整历史。目录对象新增 `status`、`latestVersion`、
`availableVersions`、`isLatest`、`manifestSha256`、`revokeReason` 和 `versionedUrl`，
未知字段由旧 App 忽略。

版本级卸载只允许删除未被服务端 active 模型、视频流绑定或进行中下载使用的版本，
并写入 `UNINSTALLED` 历史墓碑。旧 `DELETE /aiyoloapi/models/{modelId}` 在只有一个版本时
兼容映射；同一模型族存在多个版本时返回 `409 version_required`，禁止隐式删除整个模型族。

`DEPRECATED` 版本停止新安装但不强制中断已激活的端侧模型；`REVOKED` 版本禁止新安装、
升级和服务端新绑定，移动端显示撤回原因且不会因目录刷新静默删除本地文件。

## 5. 错误响应与重试

2026-11-09 M32-T27 补充：`GET /aiyoloapi/models`、
`GET /aiyoloapi/projects/{project_id}/models` 和项目 `models/available`
共享每进程 2 路完整目录检查额度，不排队、不缓存完整性结果。超出额度返回
`503 {"detail":{"code":"catalog_busy","message":"catalog read capacity reached"}}`；
等待检查超过 12 秒返回 `503` / `catalog_timeout`；两者均携带 `Retry-After: 1`。
客户端可按现有有界策略重试读取，但不得自动重放发布、转换、分配等写操作。
取消/超时不会强杀文件读取线程；额度保持到实际检查结束，防止线程无界增长。
检查期间注册表或项目分配变化返回 `409` / `catalog_changed`，需重新读取；
会话失效、降权或项目权限修订变化仍拒绝结果，沿用 401/403/404 的安全边界。
成功响应字段和完整 SHA-256、文件/元数据检查保持不变；这些限制不代表
下载、发布、启动或运行门禁被简化，也不代表跨进程/集群全局限流。

2026-11-09 M32-T28 补充：仅上述三个列表读取在一次工作线程检查内复用
同路径文件的完整 SHA-256 摘要，各引用仍独立比对预期哈希与大小。读取前后、
复用时及离开检查作用域前复核文件身份、大小、修改时间和元数据变更时间；
检测到替换、删除或变更返回 `409 catalog_changed`。无法取得可靠文件身份/
变更时间时回退完整重读，不把未知元数据当成命中。该摘要不跨请求、账户或
线程共享，不落盘，结束或异常即清理。下载、发布、激活、启动等路径不启用
此复用；这也不是对不可靠文件系统或并发恶意写入的原子快照保证。

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
| 409 | `model_in_use` | 模型当前激活或仍被视频流绑定 | 先切换默认模型或相关流绑定，再重新卸载 |
| 416 | `range_not_satisfiable` | 断点范围无效 | 删除临时文件后从头下载 |
| 429 | `rate_limited` | 下载/查询限流 | 指数退避并限制重试次数 |
| 500/502/503/504 | `internal_error` / `service_unavailable` | 服务端或上游暂时故障 | 有界指数退避；不得把 token 写入日志 |
| 413 | `artifact_too_large` | 请求或产物超过部署限制 | 不重试，提示联系管理员 |
| 422 | `invalid_model_request` | 参数或 manifest 不合法 | 修正请求，不重试 |

## 6. 与 Android M14 对接约定

- `M14-T02` 使用 `GET /aiyoloapi/models`，读取 `modelId`、`name`、`scenario`、`version`、`sizeBytes`、`license`、`compatibleDevices`、`format`、`downloadUrl`、`sha256`；服务端必须保留这些别名字段。
- `M14-T03` 使用详情中的 `artifacts` 选择适配 Android/API/ABI 的产物，下载后校验 `sizeBytes` 与 `sha256`。本契约不要求或假设签名字段。
- App 的下载器不得把 `X-Video-Service-Token` 拼接到 `downloadUrl`；每个请求都通过 header 注入。
- 服务端新增字段必须向后兼容；未知字段 App 应忽略。

## 7. 当前服务端实现说明（M09-T03）

- `GET /aiyoloapi/models` 支持可选的 `scenario` 精确匹配过滤；未知场景返回空数组而不是错误。
- `GET /aiyoloapi/models/{modelId}` 返回与列表项相同的公开字段，并保留完整 `artifacts` 数组。
- 目录查询必须携带有效账号 Session；管理工具使用 Cookie 或 `Authorization: Bearer`，移动端可使用 `X-Video-Service-Token` 兼容头传递动态 Session。静态令牌只在开发环境可用。
- 服务端从注册表读取文件并执行存在性/哈希检查，但查询响应只返回下载 API URL、大小和 SHA-256，不返回 `models/` 下的本机路径、Manifest 路径或其他本地文件定位信息。

## 8. 下载实现与运行时保护（M09-T04）

- `GET /aiyoloapi/models/{modelId}/artifacts/{artifactId}/download` 只解析注册表中已登记的产物；路径必须位于服务端 `models/` 目录内，禁止通过 `..`、绝对路径或符号链接逃逸。
- 开始传输前再次读取文件大小并计算 SHA-256；文件缺失、大小变化或摘要不一致返回 `409 model_not_available`，不会发送不符合目录契约的字节。
- 成功响应设置 `Content-Length`、安全的 `Content-Disposition` 文件名和 `X-Model-SHA256`。客户端仍应自行计算下载文件的大小与 SHA-256。
- 每个服务进程默认最多并发下载 2 个、每个客户端 60 秒最多 10 次。超限返回 `429 rate_limited` 和 `Retry-After`；可通过 `MODEL_DOWNLOAD_MAX_CONCURRENT`、`MODEL_DOWNLOAD_RATE_LIMIT`、`MODEL_DOWNLOAD_RATE_WINDOW_SECONDS`、`MODEL_DOWNLOAD_CHUNK_SIZE` 调整。
- Session 可从 Cookie、`X-Video-Service-Token`、`X-Admin-Token` 或 Bearer 请求头读取；生产环境只接受动态 Session。下载 URL 与服务日志不包含令牌。多 worker 部署仍应在反向代理层配置全局带宽/并发限额。

## 9. 资源移除增量（M112-T02，2026-10-25）

本节仅交付云端管理操作、领域事实和恢复机制；设备库存、更新通道、App 生命周期展示和用户确认清理分别属于 M111/M112-T03～T06，尚未交付。

| 路径（均带 `/aiyoloapi`） | 语义及权限 |
|---|---|
| `GET /projects/{projectId}/scenes/{sceneId}/removal-impact` | 当前项目场景管理权限；返回 `expectedRevision`、影响计数及 `safeToRemove` |
| `DELETE /projects/{projectId}/scenes/{sceneId}` | 相同权限；软删除，返回操作 ID、终态修订及删除标记，不级联模型或文件 |
| `GET /models/{modelId}/versions/{version}/removal-impact` | 当前平台模型管理权限；精确版本作用域 |
| `GET /models/{modelId}/removal-impact` | 同上；家族作用域。多版本家族返回 `409 version_required`，要求明确版本 |
| `DELETE /models/{modelId}/versions/{version}`、`DELETE /models/{modelId}` | 云端版本退役及有限已知产物回收；家族接口只允许唯一版本，不隐式全族删除 |
| `POST /models/{modelId}/versions/{version}/deprecate`、`…/revoke` | 原有状态操作增加严格前置、持久幂等意图与审计；已 REVOKED 不得退回 DEPRECATED |

写请求必须包含 `If-Match: "<正整数修订>"` 和 `Idempotency-Key`（1～128 位 ASCII 字母、数字、点、下划线、冒号或连字符）。DELETE 不接收 body 或 cascade；状态 POST 保留原有原因载荷。缺任一前置返回 428，格式或 DELETE body 无效返回 400。修订变化、同键不同载荷、依赖未消除及删除进行中返回 409；当前权限不足 403，不可见对象 404。模型存储/投影故障返回不泄漏路径的 `503 resource_lifecycle_unavailable`，不能当作未执行。

幂等身份包含当前 actor、作用域及动作；同键同载荷返回已存结果，重放仍重验当前平台权限。冲突应重新预览；网络/503 结果不确定时保留原修订和幂等键核验重试，不能直接换新键。预览不是锁、不能作为写时授权或依赖证明。

依赖包括有效项目分配、所有未软删除场景的成员及方案（含停用/未批准场景）、视频流家族引用和活动版本。模型 DELETE 在写入时再次检查；场景/分配/方案/审批/流写入也检查持久删除意图。场景软删除保留成员、方案、安装和审计记录，禁用并撤销运行授权，`sceneId` 永不复用，PATCH 不能复活。新建同名场景必须使用新 ID。旧下载、resolve、runtime 授权路径仍由服务端拒绝失效对象，不依赖新版 UI。

场景删除标记、修订、审计、领域 outbox 和授权撤销在同一 DB 事务中提交。模型使用 `prepared → registry_committed → projected/confirmed` 的持久恢复阶段；注册表墓碑与有限文件清理意图先保存，再删不再共享的已知安全路径。注册表/文件与 PostgreSQL **不是跨存储原子事务**。`uninstalled=true` 表示版本已退役，不等于全部文件已删；检查 `cleanupFailures`、`deletedFiles`、`retainedSharedFiles`、`missingFiles`。失败时保留原意图，重放或服务启动恢复；不扫描未知目录、不另建定时云端 GC、不由 App 回执触发云端删文件。

共享本地锁顺序为 scene → assignment → parameter → catalog（进程锁和 OS 文件锁）→ stream 内存锁 → PostgreSQL default/project 行 → account 行。恢复在 catalog 锁内读取最新阶段，不使用锁外旧 pending 快照；已确认操作仅补注册表确认，不重复审计/事件。生产持久恢复要求 PostgreSQL；内存测试模式不提供同等级 DB 审计和启动恢复保证。领域 outbox 尚未接入设备推送。

上线顺序：维护窗口备份 PostgreSQL、registry 与模型产物 → 使用同一应用配置执行 `alembic upgrade head`（新增 `20261025_22`，父版 `20261022_21`）→ 部署对应代码并启动 → schema 校验和有限意图恢复 → 核对日志及影响预览。存在生命周期事实/场景墓碑时 downgrade 明确拒绝；不要为回退删表或清除历史。多进程必须共享同一注册表、OS 锁文件和数据库；分布式节点须提供兼容锁语义，本次未验证跨主机共享文件系统。

`knownDevices=0` / `unknownDeviceCount=0` 是本阶段未接设备库存时的占位，不表示设备数或离线设备数为零。管理端始终明确“离线设备数量未知”；不可承诺实时通知、远程擦除或所有正在执行的推理即刻终止。运行后续授权/续期失败边界由现有 runtime 门禁负责。
