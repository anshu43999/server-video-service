# 生产环境部署与排障上下文

更新时间：2026-11-25（Asia/Shanghai）
用途：为后续生产发布、数据库迁移和故障排查提供可续接上下文。此文档是操作背景，不代表所有待办已完成。

新对话查资源：保密字典、配置字典、YAML、入口、模型 PVC → PV → NFS 的对应关系及发布核对方法，见本文第 8 节。

## 1. 项目与环境

- 本地工作区：`E:\aiyolo`；服务端项目根目录：`E:\aiyolo\server-video-service`。
- 服务端发布必须遵守工作区根目录 `docs/deployment/GIT_FIRST_RELEASE_WORKFLOW.md`：从经确认的 Git 提交构建；不得在开发服务器直接改源码或使用未提交文件补镜像；生产变更需单独确认。
- 生产 Kubernetes namespace：`saas-prod`。主要工作负载为 StatefulSet `aiyolo-video-service` 和 `aiyolo-model-converter`。
- 视频服务 Pod：`aiyolo-video-service-0`，容器 `container-mc3lj2`，HTTP 端口 `8080`；Service `aiyolo-video-service-5orf`。
- 转换器 Pod：`aiyolo-model-converter-0`，容器 `container-mqe2zn`，HTTP 端口 `8090`；Service `aiyolo-model-converter-vs2e`。
- Nginx 对外按 `/video` 子路径提供该项目；不要把项目改成根路径 `/admin`，避免与同域名下其他项目冲突。
- 用户倾向通过 KubeSphere、Navicat 等可视化界面操作。服务器上的 `kubectl` 曾返回 `Unauthorized`；不要假设其 CLI 凭据可用。确需给终端命令时，优先提供简短单行命令。
- 未经明确要求不要添加额外卷。转换器已有资源设置：内存 request/limit 均为 `4Gi`，nodeSelector 指向 `node2`；启动健康检查曾通过。

## 2. 数据库事实

- 生产数据库是 **Kubernetes 集群外的 PostgreSQL**，数据库名 `aiyolo_prod`，不是 `saas-prod` 中的 StatefulSet。
- 历史连接记录中，Pod 配置曾使用 `192.168.0.146:5432`；公网连接端点为 `116.204.109.243:5432`。曾通过同一实时 `pg_stat_activity` 会话及数据库 system identifier 证明两个路由到达同一数据库。生产配置和路由今后仍应以当前 Secret/运行配置为准。
- 不记录或索取生产数据库密码、完整连接串、Secret 内容。本次 11-25 对比只连接本地开发库，使用生产结构导出和用户在 Navicat 的回执；此前用户贴出的 Pod 连通性测试是只读查询。另有 [11-07 历史迁移回执](../../docs/deployment/2026-11-07-app-upgrade-preflight/reset-completion-20261107.md)，不据此推断今天持有生产凭证，也不把旧回执当作本次迁移验收。
- 本地开发数据库由助手只读检查：`server-video-service/.env` 指向 `127.0.0.1:5432/aiyolo_dev`，不是已知生产端点。`public` schema 有 63 张表，`alembic_version=20261117_35`。数据库另有一个 28 张表的测试临时 schema；不要将其当成正式开发 schema。

## 3. 生产库结构对比与迁移

用户提供的 `C:\Users\45393\Desktop\ios\public.sql` 是生产库 `public` schema 的结构导出；Navicat 截图确认生产 `alembic_version=20261105_34`。

生产导出与本地开发库 `public` schema 表名均为 63 张、集合一致。已确认的关键结构差异：

| 对象 | 本地开发库（revision 35） | 生产导出（revision 34） |
|---|---|---|
| `project_scene_members.project_model_id` | nullable | `NOT NULL` |
| `project_scene_members.archived_project_model_id` | 存在、nullable | 不存在 |
| `ck_scene_member_inventory_identity` | 存在 | 不存在 |
| `mobile_alert_clips` | 不存在（开发库还未升到 36） | 不存在 |

这与视频服务启动日志相符：`scene history reference schema is not initialized; run 'python -m alembic upgrade head'`。

当前代码迁移链为：

- `20261105_34 → 20261117_35`：在 `project_scene_members` 增加 nullable `archived_project_model_id`，将 `project_model_id` 改为 nullable，并添加 `ck_scene_member_inventory_identity`。迁移源码说明不会删除业务记录。
- `20261117_35 → 20261121_36`：新增 `mobile_alert_clips`，含项目/事件/账号/哈希主键、视频二进制内容及到 `alert_events(project_id,event_id)` 的 `ON DELETE CASCADE` 外键。

生产 `public.sql` 是结构导出，不含 `alembic_version` 的数据行；生产版本来自 Navicat 截图。不要为这次启动错误清空或重建数据库：更新到代码需要的结构应按 35、36 顺序迁移，清库是无关且更具破坏性的操作。

### 最近的迁移操作状态

- 助手按上述 revision 35、36 内容生成了一份含前置检查、事务、结构更新和版本标记更新的 Navicat SQL。
- 用户随后提供 Navicat 执行摘要：14 条已处理、14 条成功、0 错误，约 0.843 秒。该数字与脚本语句数相符，说明脚本报告执行成功。
- **尚未收到迁移后的独立核验结果**。下次继续先通过 Navicat 确认：
  1. `alembic_version` 为 `20261121_36`；
  2. `project_scene_members` 有 `archived_project_model_id`，`project_model_id` 可空，并存在 `ck_scene_member_inventory_identity`；
  3. `mobile_alert_clips` 表存在。
- 不要重复运行迁移脚本、手工删除表或单独改版本号。若校验不符或出现 SQL 错误，先保留现场并分析，不要盲目重试。

## 4. 2026-11-25 发布产物

发布源代码提交：`33d6a112e48d994ac429851ed9d56906b0910a66`。

| 服务 | 镜像标签 | Registry digest | 导入镜像 ID | tar SHA256 |
|---|---|---|---|---|
| Video | `aiyolo-video-service:1.0.3-adminopt.20261125-33d6a11-r1` | `sha256:c7d7dc22af63253f93c714d2231b9720bb8d19e3bc7600e55ff91833ec33fe00` | `sha256:e09f92ec66c2d68f08d302c9212aea6d6466e0cded379b8b85a238725880e3b8` | `8e2bff8344fbaceec00b644d13dc3c540ba149372846b91fcb44cbf8e72c2ccc` |
| Converter | `aiyolo-model-converter:1.0.2-ultra84123.20261125-33d6a11-r1` | `sha256:2ff1f41536df86899eef6dc7758babc0869b042a9298f717d645719a36c2ce83` | `sha256:428792b46b1bc27e6097e608c889ab611e02cd214ba64c355b91452bc4899bd4` | `782530ff52e74b986a8ee27d362bc763b8dd96f9352c94c3e8b552fb9a481433` |

归档在生产机 `/opt/server-video/`。SHA256 校验和 `docker load` 已由用户提供输出确认；Registry push 已成功并返回上述 digest。镜像导入、推送不等于 K8s 工作负载更新成功。

此前已知可运行的视频镜像：`aiyolo-video-service:1.0.3-appupdates.20261109-0a061fb-r5@sha256:8927cbf2fb2f3da5977eece47a8ac6687bd0953b07aea0d75a3708ad3f215c93`。只在需要恢复服务且核对修订历史后，将其作为回退参考。

## 5. 当前生产故障与下一步

### 已观察事实

- KubeSphere 截图显示 `aiyolo-video-service-0` 在 `node4` 上 `CrashLoopBackOff`。
- 用户附的容器日志明确显示应用在 `database.verify_schema` 阶段退出，原因是缺 revision 35 的场景历史引用结构。
- 用户在随后执行数据库迁移脚本后，Navicat 报告 14/14 成功、0 错误。
- **尚未确认视频 Pod 已恢复，也未确认转换器工作负载是否更新为 r1。**

### 恢复与验收顺序

1. 在 Navicat 只读核实上节列出的 revision 36 和 schema 项。
2. 在 KubeSphere 检查 `aiyolo-video-service` 当前 Pod 和 StatefulSet 镜像；若仍 CrashLoop，在迁移确认成功后通过 UI 重启 Pod/工作负载，等待 `Running 1/1`。迁移没有成功核实前不要反复重启或回滚数据库。
3. 确认 `aiyolo-video-service-5orf` 有 `:8080` Endpoint；检查 Pod 日志中不再有 schema initialization 错误。
4. 经项目 `/video` 路径验证登录、管理页面和健康接口；验证页面刷新仍留在 `/video/...`，不跳到同域名其他项目的 `/admin`。
5. 单独核对 Converter 是否需要部署 r1；若更新，保留 `4Gi` request/limit、node2 节点选择和既有配置，不新加卷。转换器有任务运行时避免重启。
6. 记录最终 Pod imageID、Ready 状态、Endpoint、数据库迁移版本和业务验证结果；未实际验证的项目标为未验证。

## 6. 相关历史结论

- 管理页面 `/video/admin` 跳转到根路径 `/admin` 曾造成刷新进入同域名其他项目；用户已反馈 r5 后 F5 不再跳走。本次发布包含 admin 优化，但发布后仍应复测子路径。
- Converter 内部健康接口 `GET /v1/health` 曾返回 `HTTP 200`、`status=ok`、`protocolVersion=1`；视频服务到 Converter 的集群内访问曾成功。
- 发生过转换器资源占用导致集群服务中断；转换器保留 4Gi 限额和 node2 约束。Metrics API 当时不可用，节点内存曾通过 `free -h` 查看。
- 单纯把容器 health probe 改成 HTTP `/healthz` 并不能解决数据库/schema 故障或 Nginx 502；排障应先确认 Pod Ready、Service Endpoint、应用日志及实际路由。

## 7. 操作偏好与安全边界

- 默认用中文沟通，优先提供可视化步骤（KubeSphere、Navicat），不要未经请求就给多段终端命令。
- 生产数据库结构变更通过受控迁移；不要求用户发送凭证。数据库连接验证与 schema 比对不得写入业务数据。
- 保留用户已有工作区改动；禁止因本任务执行 `git reset --hard`、`git clean` 或清理用户数据。
- 未经明确要求不提交或推送 Git 变更；构建与生产切换是不同授权。
- 不把镜像、镜像摘要或本地 `docker load` 结果误报为已完成生产部署；不把迁移脚本成功误报为应用已恢复。

## 8. Kubernetes 资源对照（`saas-prod`）

本节是**历史生产配置索引，不是可直接 apply 的清单**。工作负载与入口来自 [11-06 脱敏资源清单](../../docs/deployment/2026-11-06-production-resource-inventory.md)，模型卷来自 [11-07/08 生产核对回执](../../docs/deployment/2026-11-07-app-upgrade-preflight/live-resource-check-20261107.md)，挂载和探针变更来自 11-08/09 用户的 StatefulSet 补丁和 Pod 回显。11-06 清单中“已绑定、未挂载”是当时状态；之后 r4 的视频 StatefulSet 已列出该 PVC 和挂载路径。11-25 未重新读取集群 YAML，下次切换前以 KubeSphere 的实际 `spec` 和运行 Pod 为准。

### 保密字典、配置字典：谁在用，通过什么字段

| 资源 | 消费者及注入方式 | 发布时要保留的关系 |
|---|---|---|
| Secret `video-service-secret` | 视频容器 `container-mc3lj2`：`envFrom.secretRef`；历史转换器模板也从此 Secret 按键引用 | `DATABASE_URL` 指向外部 PostgreSQL；另有 MinIO 和转换鉴权配置。核对视频端与转换端 token **引用**是否配对，不显示值。不因仓库示例叫 `aiyolo-runtime-secret` 就重命名或重建生产 Secret。 |
| Secret `aiyolo-model-signing` | 视频容器 `model-signing-key` 卷，只读挂至 `/app/model-signing` | 文件键 `aiyolo-model-ed25519.pem` 用于模型签名；不是 App 更新签名。 |
| Secret `aiyolo-app-update-signing` | 视频容器 `app-update-signing` 卷，只读挂至 `/app/app-update-signing` | 对应文件键 `app-update-ed25519.pem`。这两个签名目录都是 Secret 文件映射，**不是业务 PVC**。 |
| ConfigMap `aiyolo-app-update-runtime` | 视频容器 `envFrom.configMapRef` | 历史开关：`APP_UPDATES_ENABLED=true`、`APP_APK_EXTERNAL_ENABLED=true`、`APP_APK_WORKER_ENABLED=false`。外链核验开启，不等于直接上传 worker 开启。 |
| ConfigMap `aiyolo-app-update-files` | 视频容器 `app-update-config` 卷，只读挂至 `/app/app-update-config` | 发布范围 `scopes.json`、兼容声明 `compatibility.json` 等文件；来源证据对应具体构建，文件存在不是所有 APK 的兼容证明。 |
| ConfigMap `video-nginx-config` | Deployment `video-nginx-v1`，键 `default.conf` 以 `subPath` 只读挂至 `/etc/nginx/conf.d/default.conf` | 只保存 ConfigMap 不会更新旧 Pod 的 `subPath` 文件；如果确实变更代理配置，须在获准发布时验证新 Pod 加载的版本。单纯换业务镜像不需改代理。 |

### 持久卷：从容器目录追到实际存储

| 层级 | 历史实测对应值 |
|---|---|
| 容器目录 → Pod 内卷名 | 视频容器 `/app/models` → `model-data`，读写挂载，用于模型清单及模型文件 |
| 卷声明 PVC（命名空间内） | `model-data` → `saas-prod/aiyolo-model-data`；`Bound`，StorageClass `nfs-client`，`ReadWriteOnce`，声明容量 `20Gi` |
| 持久卷 PV（集群级） | PVC `spec.volumeName` → `pvc-29ddbc78-8744-4598-b2f7-dad7a6ec8da5`；历史 `persistentVolumeReclaimPolicy: Delete` |
| 底层 NFS | `192.168.0.206:/data/sharenfs/saas-prod-aiyolo-model-data-pvc-29ddbc78-8744-4598-b2f7-dad7a6ec8da5`；11-08 用 UID/GID 10001 实测写入、读取、重命名成功，当时已初始化 `registry.json`。不是今天的余量、备份或恢复验证。 |

**普通升级只换镜像，保留原 PVC。不要删 PVC/PV 再建同名卷**：`Delete` 策略存在丢失后端数据的风险，重建同名 PVC 也不等于找回原数据。不要重复初始化已有模型目录。历史转换器检查未见业务 PVC；未证实 `/data` 的任务文件、校准目录、APK 核验证据能跨 Pod 保留。外链 APK、外部 MinIO、外部 PostgreSQL 都不是这个模型卷。不能把仓库 `storage.yaml` 里的示例卷数当作生产事实或扩卷授权。

### YAML 怎么查，哪份不能直接用

- **工作负载**：KubeSphere → `saas-prod` → 工作负载 → 有状态副本集 → 对应服务 → 查看 YAML。看 `spec.serviceName`、`spec.updateStrategy`、`spec.template.spec` 下的 `containers`、`volumes`、`nodeSelector`。用 `volumeMounts[].name` 对上 `volumes[].name`，再看它是 `secret`、`configMap` 还是 `persistentVolumeClaim`。发布基线为两个单副本 StatefulSet、`RollingUpdate`、`partition=0`；不要套用仓库示例 Deployment 的 `Recreate` 策略。转换器保留 `4Gi/4Gi`、`node2` 和 8090；视频启动/就绪探针曾改为 HTTP `/healthz:8080`，不是外部 `/video/healthz`。
- **入口**：共享 Ingress `route-config` 的 `/video` 和 `/aiyoloapi` → Service `video-nginx:80` → Deployment `video-nginx-v1` → Headless Service `aiyolo-video-service-5orf:8080` → 视频 Pod。Nginx 去掉 `/video`，保留 `/aiyoloapi`；视频 Service 同时声明 `8080→8080`、`18080→8080`。转换请求由视频服务走集群内 Headless Service `aiyolo-model-converter-vs2e:8090`，不是一个新的公网入口。遇到 502，先对照 Pod Ready、Service 端点和日志，不凭历史 Pod IP 改共享 Ingress。
- **存储**：在项目存储卷声明中打开 `aiyolo-model-data`，沿绑定的 PV 查看 `claimRef`、回收策略、NFS 来源，再看业务 Pod 是否实际挂载。只有 `Bound` 不代表业务容器已使用；若无 PV 查看权限，把未核对字段记为未知。
- **追溯用文件**：生产 node2 曾保存 `/opt/server-video/aiyolo-r4-backup-5Bj0kr/` 下的 `statefulsets.yaml`、`services.yaml`、`app-update-configmaps.yaml`（r4 **变更前**）；不含完整集群、PV 或 Secret 备份，当前是否还在未查。仓库 [生产 YAML 模板](../deploy/k8s/production/README.md) 和 [App 升级挂载片段](../deploy/k8s/app-updates/pod-template.fragment.yaml) 用于比对字段，不能覆盖已有 StatefulSet、Secret、Service 或共享 Ingress。
- **下次如何更新本节**：记录日期、资源名、容器名、引用键名、挂载路径、PVC/PV 绑定和观察来源；将“模板声明”和“Pod 实际生效”分开。不要复制完整 Secret YAML、`data`/`stringData`、带值环境变量、历史注解里的凭据或私钥；不需要解码。镜像回退不能还原 Secret/ConfigMap、模型卷文件或外部数据库。
