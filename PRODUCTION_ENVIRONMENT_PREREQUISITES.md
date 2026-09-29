# AI YOLO 服务端生产环境前置条件与环境基线

> 文档状态：初稿
> 基线日期：2026-09-29
> 适用项目：AI YOLO 服务端、后台管理系统、移动端接口
> 工程目录：`server-video-service/`

## 1. 文档目的

本文档用于统一生产部署前的基础设施、数据库、Kubernetes、网络、存储、配置和验收要求。文档中的密码、Token、私钥、数据库地址均使用占位符，不应把真实凭据提交到 Git。

当前生产环境采用以下总体方案：

- 服务端运行在 Kubernetes 集群中，当前生产命名空间为 `saas-prod`。
- 服务端和模型转换器当前均使用单副本 StatefulSet，而不是 Deployment。
- PostgreSQL 使用云厂商提供的外部数据库，不依赖 Pod 内或 Docker Compose 内的 PostgreSQL 容器。
- App 和后台管理系统统一通过 `/aiyoloapi` 前缀访问服务端接口。
- 后台静态页面、REST API、WebSocket、媒体播放和模型转换按各自端口及路由对外提供。
- 移动端保留现有业务配置，仅需要把服务地址指向生产环境对外地址。

根据 2026-09-29 提供的生产 YAML，当前已核实的工作负载如下：

| 工作负载 | 类型 | 副本 | 容器端口 | 镜像 |
| --- | --- | --- | --- | --- |
| `aiyolo-video-service` | StatefulSet | 1 | `8080/TCP` | `192.168.0.171:30002/saas-prod/aiyolo-video-service:1.0.1` |
| `aiyolo-model-converter` | StatefulSet | 1 | `8191/TCP` | `192.168.0.171:30002/saas-prod/aiyolo-model-converter:1.0.1` |

说明：YAML 中声明 `containerPort: 8080` 只用于描述容器端口，不会自动改变应用实际监听端口。必须确认镜像内服务实际监听 8080，且 Kubernetes Service 的 `targetPort` 与之完全一致。

## 2. 生产架构基线

建议生产链路如下：

`Android App / 浏览器 -> 公网 DNS 或 IP -> 负载均衡 / Ingress / Nginx -> video-service Pod -> 云 PostgreSQL + 私有 MinIO`

相关服务组件：

| 组件 | 作用 | 生产要求 |
| --- | --- | --- |
| video-service | 后台管理、鉴权、告警、模型和控制 API | 必须部署 |
| MediaMTX | WHEP、LL-HLS、RTSP 等媒体协议 | 使用远程视频功能时必须部署 |
| model-converter | 模型转换任务 | 使用在线转换功能时部署 |
| 云 PostgreSQL | 账号、会话、告警、参数、任务等持久化数据 | 必须准备 |
| 公司 MinIO | 告警证据图片对象存储 | 必须准备私有 Bucket |
| Ingress / Nginx | 统一域名、路径路由和 TLS | 推荐部署 |
| 持久卷 PVC | 模型、证据图片、校准集和转换产物 | 按功能准备 |

使用外部 PostgreSQL 后，Kubernetes 中不需要再启动项目自带的 PostgreSQL 工作负载。必须避免本地 PostgreSQL 和云 PostgreSQL 同时被配置为生产数据源。

## 3. Kubernetes 前置条件

### 3.1 集群与命名空间

- Kubernetes 集群节点状态正常，能够拉取业务镜像。
- 创建独立命名空间，例如 `aiyolo-production`。
- 明确生产集群、测试集群和本地环境，禁止共用同一组数据库凭据。
- 节点时间同步正常，建议容器内部统一使用 UTC 记录时间，展示层再转换为本地时区。

待确认：

| 项目 | 生产值 |
| --- | --- |
| 集群名称 | `<K8S_CLUSTER_NAME>`，尚未提供 |
| 命名空间 | `saas-prod` |
| Ingress Controller | `<INGRESS_CONTROLLER>` |
| StorageClass | `<STORAGE_CLASS>` |
| 镜像仓库 | `192.168.0.171:30002/saas-prod` |

### 3.2 镜像

- 生产环境必须使用已推送到镜像仓库的不可变版本标签，不建议长期使用 `latest`。
- 当前服务端镜像：`192.168.0.171:30002/saas-prod/aiyolo-video-service:1.0.1`。
- 当前转换器镜像：`192.168.0.171:30002/saas-prod/aiyolo-model-converter:1.0.1`。
- 若镜像仓库为私有仓库，需要创建 Kubernetes `imagePullSecret`。
- 每次部署前记录镜像 Tag、镜像 Digest、Git Commit 和部署时间。
- 当前两个工作负载均使用 `imagePullPolicy: Always`。即使 Tag 不变，也可能拉取新的镜像内容；生产环境建议使用不可变 Tag 并记录 Digest。

### 3.3 Secret 与 ConfigMap

以下内容必须放入 Kubernetes Secret：

- 数据库用户名和密码。
- 完整 `DATABASE_URL`。
- MinIO Access Key、Secret Key 和 Endpoint。
- `CONVERTER_TOKEN`。
- 模型签名私钥或私钥挂载信息。
- 镜像仓库拉取凭据。
- TLS 私钥。

以下内容可放入 ConfigMap：

- 公开域名和 API 路径。
- 服务端口。
- 模型路径和运行参数。
- 媒体服务配置。
- 非敏感的超时、限额和功能开关。

禁止将 Secret 明文写入 Deployment YAML、镜像、Git 仓库或本文档。

当前已核实的 Secret：

| Secret | 用途 | 当前引用方式 |
| --- | --- | --- |
| `video-service-secret` | 数据库连接与模型转换 Token | video-service 使用 `envFrom`；converter 使用独立 `secretKeyRef` |
| `aiyolo-model-signing` | Ed25519 模型签名私钥 | 只读挂载到 `/app/model-signing` |

模型签名 Secret 的文件权限当前为十进制 `292`，对应八进制 `0444`。文件为只读，但同一 Pod 内具备读取权限的进程仍可读取该私钥。

重要安全说明：Kubernetes Secret 的 `data` 只是 Base64 编码，并不是加密。此次提供的 YAML 已包含完整数据库连接信息、Token 和模型签名私钥材料，应视为已暴露凭据。生产环境应尽快轮换数据库密码、转换 Token 和 Ed25519 私钥，并更新对应 Secret。

## 4. 云 PostgreSQL 前置条件

### 4.1 数据库基线

| 项目 | 当前约定/要求 |
| --- | --- |
| 数据库类型 | PostgreSQL |
| 云数据库版本 | PostgreSQL 16.2 |
| 数据库名 | 当前生产连接串指向 `aiyolo_prod` |
| Schema | `public` |
| 字符集 | UTF-8 |
| 数据库用户 | 当前使用高权限账号，文档不记录明文；建议改为项目专用最小权限账号 |
| 数据库地址 | 已配置外部云数据库公网地址，文档中脱敏；建议优先改为云内网地址 |
| 数据库端口 | 通常为 `5432`，以云平台实际值为准 |

### 4.2 网络要求

- 云数据库安全组或白名单必须允许 Kubernetes 节点或 NAT 出口地址访问 5432 端口。
- 优先使用云内网地址连接数据库，避免数据库暴露在公网。
- 若云数据库强制 TLS，需要在连接串中配置对应的 SSL 参数。
- 后端 Pod 内应能够完成 DNS 解析并连接数据库地址。
- 当前生产连接串明确关闭了 PostgreSQL SSL。若云数据库支持 TLS，应改为 `sslmode=require` 或云厂商要求的验证模式。

### 4.3 连接串

生产连接串格式：

`postgresql+psycopg://<DB_USER>:<URL_ENCODED_PASSWORD>@<DB_HOST>:5432/aiyolo_prod?<SSL_OPTIONS>`

注意事项：

- 密码中的 `@`、`:`、`/`、`#`、`%` 等保留字符必须进行 URL 编码。
- `DATABASE_URL` 应从 Kubernetes Secret 注入。
- 不应继续使用 Docker Compose 服务名 `postgres` 作为生产数据库 Host。

### 4.4 数据导入与迁移

- 本地 PostgreSQL 导出的 custom dump 应使用 `pg_restore` 导入，不需要先转换为 SQL。
- 导出工具版本应尽量不高于目标 PostgreSQL 主版本，避免出现目标数据库不识别的参数。
- 导入完成后必须检查业务表、种子数据、默认模型数据和账号数据。
- 必须检查 `public.alembic_version` 是否存在有效版本号；空表不代表迁移已完成。
- `RUN_DATABASE_MIGRATIONS=true` 仅用于执行数据库结构迁移，不应被理解为每次启动重新导入业务数据。
- 正式导入前后都应创建数据库备份或云数据库快照。

基础检查 SQL：

`SELECT * FROM public.alembic_version;`

`SELECT COUNT(*) FROM public.accounts;`

`SELECT COUNT(*) FROM public.alert_events;`

`SELECT COUNT(*) FROM public.model_parameter_profiles;`

## 5. MinIO 告警证据存储

告警图片不得继续以 `data:image/...;base64,...` 形式保存在 `alert_events.payload`。Base64 会放大数据库体积和接口响应体，并导致 `/aiyoloapi/alerts` 在数据量增长后严重超时。

生产约定：

- 当前本地真实联调已验证私有 Bucket `yolo-system`、前缀 `alerts` 可以正常上传和读取。若该 Bucket 为 AI YOLO 专用，生产可保持一致；若它还承载其他系统，应创建独立 `aiyolo-alerts` Bucket。任何情况下都不要复用公开静态资源 Bucket。
- video-service 只在数据库保存对象引用、内容类型、字节数和 SHA-256，不保存图片 Base64。
- App 和后台仍通过受鉴权的 `/aiyoloapi/alerts/{event_id}/evidence` 读取图片，不直接暴露 MinIO 公网 URL。
- MinIO 账号至少需要 Bucket 检查、PutObject 和 GetObject 权限；迁移与运行链路不要求删除权限。
- K8s Pod 必须能访问 MinIO 的内网 Endpoint 和端口；启用 TLS 时应使用可信证书。
- 为 Bucket 配置容量监控、备份和生命周期策略，保留期限必须符合告警审计要求。

环境变量：

| 变量 | 说明 |
| --- | --- |
| `MINIO_ENDPOINT` | MinIO 的 `host:port`，例如 `minio.internal:9000` |
| `MINIO_ACCESS_KEY` | 放入 Kubernetes Secret |
| `MINIO_SECRET_KEY` | 放入 Kubernetes Secret |
| `MINIO_BUCKET` | 固定建议为 `aiyolo-alerts` |
| `MINIO_SECURE` | HTTPS 为 `true`；仅可信内网 HTTP 才使用 `false` |
| `MINIO_REGION` | 公司 MinIO 未配置 Region 时留空 |
| `MINIO_ALERT_PREFIX` | 默认 `alerts` |
| `MINIO_AUTO_CREATE_BUCKET` | 生产建议 `false`，由管理员预先创建 Bucket |

上述敏感变量只需要注入 `aiyolo-video-service`，不需要注入模型转换器。当前 YAML 使用 `envFrom: video-service-secret`，可将 MinIO 键加入同一个 Secret，或创建独立 Secret 后增加第二个 `envFrom`。

历史数据迁移步骤：

1. 在迁移前创建云 PostgreSQL 快照，并确认 MinIO Bucket 可访问。
2. 先执行预演，只统计含 Base64 的记录，不上传、不更新数据库：`python tools/migrate_alert_evidence_to_minio.py --dry-run --batch-size 100`
3. 执行正式迁移：`python tools/migrate_alert_evidence_to_minio.py --batch-size 100`
4. 验证数据库已无内联图片：`SELECT COUNT(*) FROM public.alert_events WHERE payload::text LIKE '%data:image/%';`
5. 抽查后台告警图片和证据接口，并再次测量 `/aiyoloapi/alerts` 的响应体积及耗时。

迁移工具支持幂等重跑，也可使用 `--limit <N>` 先迁移少量记录。该迁移不会在容器启动时自动执行，避免大量对象上传阻塞 Pod 启动。若必须回滚到不支持 MinIO 的旧镜像，需要同时恢复迁移前数据库快照；只回滚镜像会使已迁移的移动端证据无法读取。

## 6. 核心环境变量

### 6.1 必填项

| 变量 | 示例/说明 |
| --- | --- |
| `DEPLOYMENT_ENV` | `production` |
| `DATABASE_URL` | 指向云 PostgreSQL 的完整连接串 |
| `RUN_DATABASE_MIGRATIONS` | 建议为 `true`，但上线前必须确认迁移版本正确 |
| `DATABASE_CONNECT_TIMEOUT_SECONDS` | 数据库建立连接的超时，例如 `10` |
| `AUTH_SESSION_DAYS` | 登录会话有效期，例如 `30` |
| `MINIO_ENDPOINT` / `MINIO_BUCKET` | 公司 MinIO 内网地址和私有告警 Bucket |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | 放入 Secret，不得提交 Git |
| `MEDIA_PUBLIC_HOST` | App 能访问的公网域名或 IP |
| `MEDIA_PUBLIC_SCHEME` | 生产建议为 `https` |
| `MEDIA_ALLOW_ORIGINS` | 生产环境应配置明确来源，避免长期使用 `*` |
| `CONTROL_BIND_ADDRESS` | `0.0.0.0` |
| `CONTROL_PORT` | 当前 YAML 声明容器端口为 `8080`；必须显式设置并与应用监听端口、Service targetPort 保持一致，历史 Compose 默认值为 `18080` |
| `MODEL_MOUNT_PATH` | 模型持久卷在容器外的挂载来源 |
| `YOLO_MODEL_PATH` | 容器内模型路径 |
| `CONVERTER_TOKEN` | 放入 Secret，不得提交 Git |

当前 YAML 中的实际注入关系：

- video-service 通过 `envFrom: video-service-secret` 注入该 Secret 的全部键。
- video-service 另外设置 `MODEL_SIGNING_KEY_ID=internal-dev-2026-01` 和私钥路径。
- model-converter 从 `video-service-secret` 单独读取 `CONVERTER_TOKEN`、`POSTGRES_PASSWORD` 和 `DATABASE_URL`。
- Secret 同时包含 `AIYOLO_REMOTE_CONVERSION_TOKEN` 和 `CONVERTER_TOKEN`。如二者当前使用同一值，应确认是否确实需要两个变量，避免长期重复维护同一敏感值。
- 如果 converter 实际不直接读写数据库，应移除它的数据库凭据，遵循最小权限原则。

### 6.2 可选签名配置

| 变量 | 说明 |
| --- | --- |
| `MODEL_SIGNING_KEY_ID` | 模型签名密钥标识 |
| `MODEL_SIGNING_PRIVATE_KEY_PATH` | 私钥在容器内的只读挂载路径 |

私钥文件必须存放在 Secret 或外部密钥管理系统中，并使用只读挂载。

## 7. 网络、端口与路由

| 功能 | 默认端口/路径 | 对外要求 |
| --- | --- | --- |
| 后台与控制 API | 当前 StatefulSet 声明 `8080/TCP` | 必须确认应用监听端口和 Service targetPort |
| REST API 前缀 | `/aiyoloapi` | Nginx、Ingress、后台和 App 必须一致 |
| 模型转换服务 | `8191/TCP` | 建议仅集群内访问 |
| LL-HLS | `8888` | 按媒体需求暴露 |
| WHEP | `8889` | 按媒体需求暴露 |
| WebRTC UDP | `8189/UDP` | 安全组、Service 和 NAT 都需放行 |
| RTSP 诊断 | `8554` | 建议仅内网开放 |
| SRT | `8890` | 未使用时不要对公网开放 |

生产环境建议：

- 后台和 API 使用 HTTPS。
- WebSocket 路由必须支持 Upgrade 头。
- Ingress/Nginx 不应将其他项目的 `/api` 路由转发到本项目。
- 本项目所有 API、WebSocket 和相关请求统一使用 `/aiyoloapi`。
- App 的生产服务地址应使用稳定域名，不建议长期写死公网 IP。

## 8. 持久化存储

以下目录不应只存放在 Pod 临时文件系统中：

- 已安装和已转换模型。
- 告警证据图片（本次改造后使用 MinIO，不再依赖 Pod 本地目录）。
- 校准数据集及上传文件。
- 转换任务产物。
- 需要跨 Pod 重启保留的运行资产。

要求：

- 使用 PVC 或对象存储实现持久化。
- 明确访问模式、容量、扩容方式和备份策略。
- Deployment 滚动更新或 Pod 重建后，模型与证据文件必须仍然存在。
- 数据库备份与文件资产备份必须分别设计。

当前提供的两个 StatefulSet YAML 均没有声明 PVC 或业务数据卷。video-service 只挂载了模型签名 Secret，model-converter 没有任何持久卷。因此当前 YAML 无法保证模型文件、告警证据、校准数据和转换产物在 Pod 重建后仍然存在。虽然工作负载类型是 StatefulSet，但没有 `volumeClaimTemplates` 或 PVC 时，并不会自动获得数据持久化能力。

待确认：

| 存储项 | 挂载路径 | 容量 | 备份策略 |
| --- | --- | --- | --- |
| 模型目录 | `<MODEL_VOLUME_PATH>` | `<SIZE>` | `<POLICY>` |
| 告警证据 | `<EVIDENCE_VOLUME_PATH>` | `<SIZE>` | `<POLICY>` |
| 校准数据 | `<CALIBRATION_VOLUME_PATH>` | `<SIZE>` | `<POLICY>` |

## 9. 健康检查与资源配置

- 为后端配置 Startup、Readiness 和 Liveness Probe。
- Readiness 检查失败时，Service 不应继续向该 Pod 转发流量。
- 数据库短暂不可用时，应有明确日志，不应导致无限重启。
- 根据推理、视频和转换负载分别配置 CPU、内存和临时磁盘。
- 模型转换容器应独立设置更高内存、共享内存和临时空间限额。
- 如需 GPU，必须确认节点驱动、RuntimeClass、资源声明和调度标签。

当前 YAML 存在以下运行治理缺口：

- 两个容器的 `resources` 均为空，未设置 CPU/内存 requests 和 limits。
- 两个工作负载均未配置 startupProbe、readinessProbe 或 livenessProbe。
- 使用 `default` ServiceAccount，尚未体现最小权限 RBAC。
- Pod 和容器 `securityContext` 为空，尚未限制 root 用户、Linux capabilities 或只读根文件系统。
- 两个工作负载均只有 1 个副本，Pod 更新或节点故障期间可能造成服务中断。
- StatefulSet 使用 `OrderedReady`，但当前单副本情况下不会带来高可用能力。
- 当前容器名称是平台生成名称，排查和脚本维护不直观，建议改成稳定的 `video-service` 和 `model-converter`。

## 10. 推荐部署顺序

仓库现已提供 `deploy/k8s/production/` Kustomize 模板。模板使用 Deployment、外部 PostgreSQL、外部 MinIO、8080 控制端口、8090 转换端口、健康探针、资源限制、安全上下文和 PVC；运行时真实值通过 `aiyolo-runtime-config` 与 `aiyolo-runtime-secret` 注入。旧 YAML 中模型转换器的 8191 端口不再使用。

1. 创建云 PostgreSQL 数据库、用户、网络白名单和备份策略。
2. 导入生产数据并检查 `alembic_version`、账号、种子数据和默认模型数据。
3. 创建私有 `aiyolo-alerts` Bucket、最小权限 MinIO 账号及网络白名单。
4. 在 K8s 创建命名空间、Secret、ConfigMap、PVC 和镜像拉取凭据。
5. 部署或确认 MediaMTX 和模型转换服务。
6. 部署 `aiyolo-video-service` StatefulSet，并确认其连接的是 `aiyolo_prod` 云 PostgreSQL 和公司 MinIO。
7. 先预演再执行历史告警证据迁移。
8. 配置 Service、Ingress/Nginx、域名、TLS 和 WebSocket 转发。
9. 检查 Pod 状态、探针、日志和资源使用情况。
10. 执行登录、告警、模型、参数、视频播放和后台管理验收。
11. 验收通过后记录镜像版本、数据库快照和回滚版本。

## 11. 上线验收清单

### 11.1 Kubernetes

- [ ] 所有必要 Pod 为 `Running` 且 Readiness 正常。
- [ ] Deployment 使用正确的生产镜像 Tag/Digest。
- [ ] Pod 重启后模型和文件资产不会丢失。
- [ ] Secret 未出现在日志、Git 或页面响应中。

### 11.2 数据库

- [ ] Pod 可以通过内网连接云 PostgreSQL。
- [ ] `alembic_version` 有正确版本记录。
- [ ] 账号能够登录，密码哈希算法与当前服务端一致。
- [ ] 种子数据、默认模型和业务数据数量符合预期。
- [ ] 已创建上线前数据库快照。
- [ ] `alert_events.payload` 中不再存在 `data:image/` 内联图片。

### 11.3 API 与 App

- [ ] `/aiyoloapi/auth/login` 正常返回。
- [ ] `/aiyoloapi/models` 正常返回模型列表。
- [ ] `/aiyoloapi/alerts` 在 App 超时阈值内返回。
- [ ] 新告警数据库记录只包含 MinIO 对象引用，证据接口可返回正确图片。
- [ ] 模型参数接口能够返回当前启用模型的 Android 参数。
- [ ] App 不再请求旧的 `/api` 前缀。
- [ ] WebSocket 能够建立并保持连接。

### 11.4 MinIO 与媒体

- [ ] MinIO Bucket 为私有，未开启匿名读取。
- [ ] Pod 可通过内网访问 MinIO，上传和读取测试均成功。
- [ ] Bucket 容量、备份、保留期限和告警已配置。

- [ ] WHEP、LL-HLS 或选定播放协议可以从外部网络访问。
- [ ] WebRTC UDP 端口已在安全组和 K8s Service 中放行。
- [ ] 不存在无效的 MJPEG 预览地址或无对应运行时的视频流。

## 12. 诊断命令

查看工作负载和 Pod：

`kubectl get deployment,pod -n <K8S_NAMESPACE> -o wide`

查看后端日志：

`kubectl logs -n <K8S_NAMESPACE> deployment/<VIDEO_SERVICE_DEPLOYMENT> --tail=500 --timestamps`

进入后端容器：

`kubectl exec -it -n <K8S_NAMESPACE> <VIDEO_SERVICE_POD> -c <VIDEO_SERVICE_CONTAINER> -- /bin/sh`

Pod 内直接测试接口总耗时：

`curl -sS -o /dev/null -w 'HTTP=%{http_code} connect=%{time_connect}s start=%{time_starttransfer}s total=%{time_total}s size=%{size_download}B\n' -H 'Authorization: Bearer <ACCESS_TOKEN>' http://127.0.0.1:<ACTUAL_CONTROL_PORT>/aiyoloapi/alerts`

数据库活动连接和锁等待：

`SELECT pid,state,wait_event_type,wait_event,query_start,LEFT(query,200) FROM pg_stat_activity WHERE datname=current_database() ORDER BY query_start;`

统计仍含 Base64 的告警：

`SELECT COUNT(*) FROM public.alert_events WHERE payload::text LIKE '%data:image/%';`

## 13. 当前已知风险与待处理事项

1. App 控制接口当前连接和读取默认超时均为 15 秒。
2. `/aiyoloapi/alerts` 的主要已知瓶颈是历史告警在 JSON 中内联 Base64 图片；上线 MinIO 代码后仍必须执行历史迁移。
3. 告警列表当前缺少明确分页上限，生产环境建议默认只返回最近一页数据。
4. 部分上传模型可能没有对应的 Android 参数配置，参数接口会返回 404。
5. 部分视频流的 MJPEG 地址返回 404，需要确认运行时实际支持的播放协议。
6. 已提供的 Secret 内容包含真实凭据及私钥，必须执行凭据轮换。
7. 数据库连接当前关闭 SSL，且使用外部公网地址，应评估切换内网和启用 TLS。
8. 两个 StatefulSet 均无健康探针、资源限制、持久卷和安全上下文。
9. video-service 声明的容器端口为 8080，但必须继续核对实际监听端口和 Service targetPort。
10. `MODEL_SIGNING_KEY_ID` 当前带有 `internal-dev` 标识，生产环境建议生成独立生产密钥并使用明确的生产 Key ID。
11. 需要补齐生产集群名称、域名、Service、Ingress、PVC、资源限额和备份保留周期。

## 14. 生产信息登记表

以下内容应由生产负责人填写，并将敏感值存放到密码管理或 Secret 管理系统中：

| 项目 | 生产值 |
| --- | --- |
| 公网域名 | `<PUBLIC_DOMAIN>` |
| 公网入口 IP | `<PUBLIC_IP>` |
| API Base URL | `https://<PUBLIC_DOMAIN>/aiyoloapi` |
| K8s 集群 | `<K8S_CLUSTER_NAME>` |
| Namespace | `saas-prod` |
| 后端工作负载 | StatefulSet `aiyolo-video-service` |
| 后端容器 | 当前为平台生成名称，建议改为 `video-service` |
| 后端镜像 | `192.168.0.171:30002/saas-prod/aiyolo-video-service:1.0.1` |
| 转换器工作负载 | StatefulSet `aiyolo-model-converter` |
| 转换器镜像 | `192.168.0.171:30002/saas-prod/aiyolo-model-converter:1.0.1` |
| PostgreSQL Host | 已配置外部地址，文档脱敏；建议改为内网地址 |
| PostgreSQL Database | `aiyolo_prod` |
| PostgreSQL User | 建议使用 `<AIYOLO_DB_USER>` 项目专用账号 |
| MinIO Endpoint | `<MINIO_ENDPOINT>` |
| MinIO Bucket | `aiyolo-alerts` |
| TLS Secret | `<TLS_SECRET>` |
| StorageClass | `<STORAGE_CLASS>` |
| 数据库备份保留周期 | `<RETENTION_DAYS>` |
| 文件资产备份策略 | `<BACKUP_POLICY>` |

## 15. 当前 YAML 整改优先级

### P0：立即处理

1. 轮换此次已暴露的数据库密码、转换 Token 和 Ed25519 签名私钥。
2. 更新 `video-service-secret` 和 `aiyolo-model-signing` 后滚动重启两个 StatefulSet。
3. 确认 video-service 实际监听端口与 Service `targetPort` 一致，重点核对 8080 与历史配置 18080 的差异。
4. 确认云数据库白名单、连接账号和 `aiyolo_prod` 数据库均为正式生产配置。
5. 创建私有 MinIO Bucket，将访问凭据加入 Secret，并执行历史告警证据迁移。

### P1：上线稳定性

1. 为 video-service 增加 startup、readiness 和 liveness 探针。
2. 为两个容器设置 CPU/内存 requests 和 limits。
3. 为模型、校准数据和转换产物增加 PVC；告警证据统一使用 MinIO。
4. 为 PostgreSQL 启用 TLS 或使用云内网链路。
5. 为 `/aiyoloapi/alerts` 增加分页并排查服务端阻塞。

### P2：安全与治理

1. 创建项目专用 ServiceAccount 和最小权限 RBAC。
2. 增加 Pod/容器安全上下文，限制 root 和多余 capabilities。
3. 使用生产专用签名 Key ID，停止使用 `internal-dev-2026-01`。
4. 将平台自动生成的容器名称改为稳定业务名称。
5. 评估 video-service 是否确实需要 StatefulSet；如果状态全部外置到 PostgreSQL、PVC 或对象存储，可考虑改用 Deployment 以便扩缩容和滚动发布。
