# M111 服务端模型更新控制面

这是 `mobile-app/harness` 中 M111-T02 的跨仓实现说明，不是第二份产品需求。权威执行定义为 `../mobile-app/harness/proposals/M111-execution-plan-v1.md` 修订3；线格式为 `app/model_updates/contract-v1.schema.json`，回归核对其与移动端副本一致。真实 FCM 设备送达及容量基线最终验收归 M111-T05，本文件不宣称已通过。

## 数据路线与事务

模型文件 registry 发布 → 提交后唤醒；assignment/scene/项目成员及生命周期数据库变更 → 同事务 domain outbox → 提交后唤醒 → Projection → PostgreSQL targets/inbox/changes → 每 binding 一条 push outbox → 可选 FCM 唤醒 → HTTPS snapshot/delta → App。文件与数据库不声称跨存储原子；启动及每60秒完整反熵重扫修复缺口。供应商发送独立循环，慢 FCM 不阻塞补偿扫描。业务写入不等待全设备分发。

扫描以 deviceId keyset 读取最多200个ID，拆成两个100设备批；PostgreSQL advisory transaction slots限制跨进程最多两个批。每设备独立事务，锁序为项目共享锁 → binding → 子记录；序号只在 binding 锁内分配并提交。失败不确认源事件，重启重新从当前真相构建；重复扫描不重置进度或隔离状态。不展开设备×历史版本矩阵。

库存仅表示客户端保留选择，绝不授予项目/下载/运行权限。完整库存缺项将来源epoch退休；较新inventoryRevision不能恢复旧epoch，显式重加须增加sourceEpoch。持久epoch ledger上限10000个来源且2MiB，超限413原子保留旧库存。每来源仅最新目标 is_current 进入全量快照；旧进度/终结事实留在changes。执行中旧目标可以完成文件，但不得提交旧批准；仅允许精确旧目标的superseded终结回执，或新库存已到最新目标后扫描收敛，撤权立即失效。

参数SHA沿用 `scene_parameter_digest.parameter_digest` 的Android规范数值编码；不是普通Python JSON浮点编码。场景artifacts顺序对应排序后的原memberIds，允许同modelId/version的不同成员具有不同参数身份，不按modelId去重。计划扩员超出原选择时不自动扩大安装。已由有效场景批准的版本不再产生同项目待审批发布提示。

## 七条API

所有路由使用现有登录session/token，拒绝legacy身份，不接受body指定账号。账号级路径不扩大现有项目下载scope；设备游标/票据绑定账号、设备及epoch。

| 方法与路径（均为 /aiyoloapi 前缀） | 输入与结果 |
|---|---|
| PUT /mobile/model-update-devices/{installationId} | binding_request → binding_response；绑定/能力/token generation |
| DELETE /mobile/model-update-devices/{deviceId} | unbind_request → 幂等退休绑定/token |
| PUT /mobile/model-update-devices/{deviceId}/inventory | 完整库存和revision → acceptedRevision；最多1000项/2MiB |
| GET /mobile/model-updates?deviceId=…&cursor=…&limit=100 | 不透明cursor → 增量、nextCursor、hasMore |
| GET /mobile/model-updates/snapshot?deviceId=…&pageToken=…&limit=100 | 固定高水位快照，票据10分钟 |
| POST /mobile/model-update-reports | 最多100条/1MiB → 每eventId逐项accepted/duplicate/stale/rejected |
| GET /projects/{projectId}/model-update-status | 管理能力与明确项目scope；updateId/deviceStatus/pageToken/limit过滤，无token |

分页默认100/最多200，单项32KiB、编码响应1MiB；快照工作集10000项/16MiB上限，超限明确413而不是截断身份。正文重复键/非有限数/额外字段/非法类型拒绝。401重新登录；403撤权；409绑定/目标变化；410游标/快照过期；413容量；429含Retry-After；数据库不可用503，无内存假成功。

远端回执允许漏报中间阶段后补报真实完成，但仍复核digest、successCriteria、授权代和单调reportSeq。本地安装状态机仍须严格执行下载/验签/准备/提交，远端接受补报不是跳过本地校验。进度itemRevision递增不推进authority_revision；不变进度不生成change，所有进度回执不触发新push，防止发现→推送循环。撤权前的旧回执不得恢复成功。

## HTTPS、续传与配置

现有两条项目模型产物下载与场景产物下载共用Range helper：单范围206、suffix、416、SHA256强ETag、准确Content-Range/Length；If-Range不匹配回200，不能拼接。每次请求仍重新鉴权与校验原expectedRevision，文件摘要不是授权。流结束/取消均幂等释放句柄和下载并发额度。

生产入口必须HTTPS。反向代理固定可信Host并保留外部scheme；只信任已配置TLS终止代理的转发头，不能信任任意客户端X-Forwarded-*。binding.origin来自校验后的request.base_url；改变公开origin需重新绑定，不能用临时localhost替代生产身份。受控HTTP TestClient仅验证协议，不代表HTTPS部署验收。

默认不配置FCM仍保留全部HTTPS补偿。启用需在部署中显式注入 `MODEL_UPDATE_FCM_PROJECT_ID` 和 `MODEL_UPDATE_FCM_CREDENTIALS_PATH`，只读挂载repo外service_account JSON；必须与凭据project_id完全一致，token_uri固定Google OAuth。无配置/错误配置不得宣称送达。不得把私钥/token写日志、证据或Git。无新增第三方包：复用已有cryptography完成RS256、标准库HTTPS，禁止携带Authorization跟随重定向。

FCM HTTP v1仅normal data，三字段type/contractVersion/eventId，TTL86400s，固定collapse_key=model_updates_changed_v1；不含模型/项目名、URL或通知自动展示payload。dirty/sent/lease分离，租约60秒，发送时新dirty不被旧响应抹掉；后续30秒聚合，失败指数退避最多1小时，并遵守更严格Retry-After；UNREGISTERED停止旧token，rotation旧结果不影响新token。供应商accepted不等于设备发现/安装。

## 监控、清理与迁移

控制面每binding 2请求/s burst10；绑定/管理入口按账号，部署共享200/s burst400。FCM独立共享100/s桶，不消耗控制面配额。无推送配置/none设备不占据可发送候选队列。

现有受鉴权 `/aiyoloapi/metrics` 的modelUpdates包括表数量、pending队列、最老源事件/dirty推送年龄、尝试次数、JSON文档存储字节以及持久measurements：控制面状态码计数/耗时总量/最大值、共享限流次数、projection_scan_seconds、provider状态累计。文档字节不是表/索引/WAL总磁盘占用，完整数据库增长与P95/CPU/内存由T05容量验收采样，不冒充远程安装证明。

每小时清理：终态changes/reports满90天压缩，旧游标floor推进并410要求当前快照；当前终态保留用于重建，非current旧终态可删除，孤立target与已处理源事件清理；有效未完成事实无TTL。快照/分页票据按10分钟到期清理，cursor票据90天。不可把目录缺项/404当作本地删除命令；全部安装资源生命周期扩展归M112-T03。

迁移revision `20261025_23` 依赖 `_22`，新增12张model_update表，不改业务历史模型。部署前对目标库做可恢复备份并确认正确DATABASE_URL，独立维护窗口运行既有Alembic upgrade head，先隔离演练再部署；启动仍verify_schema，不自动迁移。禁止把测试命令连接到开发/生产库。存在任何持久事实时downgrade拒绝，不能删表绕过；回退应用需保留数据库和补偿事实，正式降级须备份恢复与兼容评审。

复核命令（在server-video-service根执行）：`.venv/Scripts/python.exe tools/accept_m111_updates.py --postgres`。Runner创建随机临时数据目录、回环端口和独立schemas，核对data_directory/current_user，最后清schema并停实例核对portClosed。每轮result.json与失败日志保留，正式摘要在 `harness/evidence/M111/T02/postgres-result.json`。该命令不连接5432/aiyolo_dev、不改Default Project、不重启8080。

## M112-T03：全库存生命周期扩展

代码归属移动端 Harness 的 M112-T03，服务端不另改任务状态。冻结定义为 `../mobile-app/docs/mobile-resource-lifecycle-v1.md` 和其 schema；M111 schema 两份同步扩展，生命周期定义以 `lifecycle_` 前缀嵌入且不改冻结字段。

同一条路线：已接受库存 → 当前项目权限/精确分配/场景/注册表墓碑 → `Device.lifecycle_facts` → 原 `changes` 提交序列和聚合 dirty outbox → 原 HTTPS → 原 reports。生命周期 Change/Receipt 的 SQL `update_id` 为 NULL，线上事实与回执无 updateId。无需新版本、更新待办、通知权限或 GMS。复用原启动/60秒扫描、业务提交唤醒、两个批次槽位和限流；FCM仍是可选脏信号。自动更新开关属于端侧策略，不控制服务端失效投影。

| 原接口 | 扩展线格式与守卫 |
|---|---|
| bind | capabilities 可选 `resourceLifecycleVersions:[1]`；仅协商后返回 `resourceLifecycleVersion:1`。未声明时不返回新字段/kind。 |
| inventory | 原 `entries` 保留；协商后必须带完整 `lifecycleEntries`（可为空），含所有 retained/staging/unknown_legacy 来源。两个数组合计最多1000项/2MiB。未协商却传新数组或协商后缺数组均409；增强协议旧revision拒绝，旧M111客户端保留原幂等行为。 |
| changes | `operation:lifecycle` 携带冻结 `resource_lifecycle` fact；与原更新变化共用 sequence/cursor/页预算，无第二个计数器。 |
| snapshot | 外层 `items` 仍为更新项；协商后增加完整冻结 `lifecycleSnapshot` 对象。两种条目合计受 limit≤200/1MiB约束，所以前几页的生命周期 items 可以为空。外内层共用 snapshotId/cursor/nextPageToken；内层pageIndex逐页递增、coveredCount累计生命周期唯一条目数，最后必须覆盖全部已接受生命周期库存。 |
| reports | reports数组是原M111回执与`reportKind:resource_lifecycle`的判别联合，共用100项/1MiB、eventId去重及事务。生命周期按来源epoch/reportSeq/事实ID和修订复核，迟到发现不得倒退清理阶段。回执不再触发dirty，防止循环。 |

兼容映射：原M111 envelope 的 `binding.origin` 不改名；冻结M112 fact/内层快照/生命周期receipt使用 `binding.serviceOrigin`，其值严格等于该绑定origin。不可把两种对象直接替换。能力改变或增强库存revision变化后，旧票据410，重新上传/重建快照。

生命周期来源是精确的 assignmentId，或 sceneId/revision/planId/selectionDigest/memberId；共享字节不合并授权来源。既有 sceneId 是稳定 incarnation，软删除后不可复用。selectionDigest沿M111排序去重后的 `{planIds,memberIds}` 规范JSON SHA256。单方案可由该方案完整成员集验证；多方案/自定义合集从同次M111场景库存的selection恢复原选择并逐方案核验，无需updateId。缺少足够选择历史时返回unknown，不把不可逆摘要猜成删除或放行权限。Android T04应在同一库存事务上传两类来源。

分配停用/目标变更只失效精确来源；场景停用/软删对scene资源分别返回scene_disabled/scene_removed，成员模型返回project_grant_removed。项目/账号不可见时结果严格只有opaque/denied/scope_inaccessible，不回传资源键或名称。所有页释放前重新核对当前权限/授权结果；旧可见页或旧available增量不再可信时410，等待现有扫描重建。库存尚未完整投影时503，绝不用缺项代表移除。

删除终态只来自有操作ID、删除时间、生命周期修订和精确产物身份的持久注册表墓碑，或场景软删除行；旧UNINSTALLED历史不足时unknown。事实及来源终态水位不随90天传输日志/回执清理；重复扫描不增修订，仅库存revision改变不改事实修订，旧epoch/退休来源不能重放，终态不会被注册表异常复原或unknown复活。新绑定可从当前真相重建，不能依赖旧changes仍存在。

迁移 `20261026_24` 依赖 `_23`，增量添加设备库存/事实和快照覆盖文档，允许change/report的update_id为空；保留原M111库存、序号、来源水位和历史负载。存在设备安装或持久change/report时拒绝降级。设备facts上限16MiB，来源ledger沿用10000身份/2MiB；超限413事务回滚，不截断库存或释放旧水位。documentStorageBytes包含新增文档；这不代表数据库物理磁盘大小。

复核：`.venv/Scripts/python.exe tools/accept_m112_sync.py --postgres`。证据入口 `harness/evidence/M112/T03/postgres-result.json`；每轮原始日志、失败和result保留在runs。实际重启仅允许本runner-owned临时data directory；pg_ctl重启显式追加同一日志文件，防止Windows子服务持有测试输出管道。此阶段证明服务端协议、事务和真实数据库恢复，Android Room/作业/UI/API27及联合时延属于M112-T04～T06。
