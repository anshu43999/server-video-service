# 平台统一模型参数（2026-11-16）

本规则替代旧的项目参数继承/覆盖、场景成员独立参数及参数重新审批流程。模型文件与运行参数由平台维护；项目管理模型使用清单与场景方案。

| 内容 | 维护者 | 生效方式 |
|---|---|---|
| 模型文件、精确版本、目标端产物、签名和发布状态 | 平台管理员 | 沿用资产发布与撤销流程 |
| 检测阈值、IoU、最大检测数、类别启停、图片/视频告警规则 | 平台管理员 | 保存草稿后显式发布 |
| 项目可用模型版本、目标端、启停 | 项目负责人 | 清单revision与权限校验 |
| 场景成员、顺序、输入、single/sync/async方案、相机调度策略及审批 | 项目负责人 | 场景revision与审批 |

## 草稿与发布

参数身份为精确`modelId + modelVersion + platform(server/android)`。GET平台参数接口返回草稿、`publishedRevision`（未发布为null）和`hasUnpublishedChanges`。PUT保存、DELETE重置都只改变草稿，不改变运行参数。

`POST /aiyoloapi/platform/models/{modelId}/parameters/publish?version=...&platform=...`携带`expectedRevision`及`expectedPublishedRevision`，两者均作CAS校验，冲突409。仅平台模型管理权限可调用。发布在同一事务内复核平台账号，记录审计。发布记录存于既有`model_parameter_audits`的`PUBLISHED`快照，不引入新的迁移或删表。

项目参数读接口、场景目录/resolve、设备更新投影统一返回最新发布快照，`source="platform"`。项目和场景参数写接口退役，具备原权限的调用返回410；无权调用仍由权限检查拒绝。请求中的旧`parameterRevision`不再固定参数版本；新客户端不提交该字段。

## 启动、运行及更新

### 模型目录中的项目添加条件（2026-11-18）

平台“模型资产 → 模型目录”按精确版本分别展示 PC / 移动端的模型文件与运行参数发布状态，给出“待发布参数”“项目可添加”或“状态待核实”等提示。模型文件发布与参数发布是两次明确操作：仅发布文件不会让缺少参数发布版的目标端进入项目候选。通过“去发布服务端参数 / Android 参数”可打开该版本、该端的参数档案；关闭档案或刷新目录会重新读取状态。

平台 `GET /aiyoloapi/models` 增加只读 `parameterPublication.server/android` 摘要，包含 `state`（`published` / `unpublished` / `unavailable`）、`publishedRevision`（未发布或不可核实时为 null）及 `hasUnpublishedChanges`。r0 是有效发布版；已发布后编辑草稿不影响已有发布版可用性。摘要不含完整参数或审计内容，不进入项目目录响应；数据库使用批量查询，参数读取失败不阻断模型文件目录，也不冒充未发布。该摘要仅作界面提示，分配时仍由既有授权、文件、发布状态和参数门禁重新校验。

首次明确发布前不允许分配/启动该目标端；历史授权清单中缺少发布的项不可用于新运行。不会以默认值、草稿、旧项目覆盖或旧场景快照作为回退。

新启动解析最新平台发布，保存完整参数快照及摘要。服务器运行中保持启动参数；停止后再启用推理会取得最新发布。移动端场景续租保留原启动参数revision/digest，同时重新核验账号、项目、场景revision、成员、模型/产物和输入能力。单纯发布参数不撤销已有租约；权限撤销、场景变更、资产撤回仍阻止续租。离线客户端最多受既有租约有效期约束，不能承诺即时远程停止。

项目/场景的revision与审批不会因平台发布参数而改变。设备更新目标摘要包含参数摘要，因此相同权重与同一场景revision也能产生参数更新。权重/manifest哈希保持不变，客户端可复用本地文件；新启动仍须核验参数摘要，不能凭旧缓存授权。运行中安装更新与启动快照应隔离。

## 历史资料与上线

旧PROJECT参数行、历史assignment/member快照、参数/项目审计及历史告警保留，不再作为新运行的参数来源。禁止把任意项目覆盖自动提升为平台发布版，也不自动清空数据库或Default Project。

只读差异检查：显式设置专用环境变量后执行`.venv/Scripts/python.exe tools/audit_platform_model_parameters.py --database-url-env PARAMETER_AUDIT_DATABASE_URL`。工具不读取.env连接，不执行迁移或写入，列出旧项目覆盖/清单/场景历史与平台发布版的差异和缺失发布情况。运行生产检查须另行授权，命令不能输出凭据。

本次本地实现没有迁移或发布业务环境。上线前需平台管理员核对差异、为每个在用版本/目标端明确发布参数，并完成Android兼容及真实设备验收。隔离数据库回归命令为`.venv/Scripts/python.exe tools/accept_platform_model_parameters.py`；唯一报告为`harness/acceptance/M36-model-capabilities-scenes.md`。
