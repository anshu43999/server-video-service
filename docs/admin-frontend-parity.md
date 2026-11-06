# 管理后台迁移功能对等与接口清单

> 2026-10-15 / M34-T04 视频范围修订：本文旧直播分发/移动远程播放条款由 [ADR-003](adr-003-analysis-alerts-only.md) 取代。保留PC同源预览、输入分析、项目隔离、正式告警和证据；回退须符合 [分发退役升级手册](media-retirement-upgrade.md)，不能恢复旧发布器/移动直播。本文其他账号、项目、迁移、恢复、安全与审计门禁仍有效；先本地真实验收，再部署。

基线日期：2026-10-08；适用：M32-T01；架构：[ADR-004](adr-004-admin-frontend-engineering.md)。  
清单状态：基线已核对，T02–T09 已迁移；T10 正式构建切换与验证结果见 [逐项验收矩阵](../evidence/M32/M32-T10-cutover-acceptance.md)。下文“当前”描述指 T01 冻结时的原生页面基线，稳定编号继续用于追踪。生产环境发布、真实模型转换与既有安全缺口见该验收的边界说明。

当前状态（M32-T11）：旧前端已归档至 `E:\aiyolo\archives\server-admin-legacy\20261009-M32-T11` 并从产品目录删除。下文 S1–S3 等路径为迁移时的历史基线，可在档案中查询；当前前端源码为 `admin-web/src/`。现版仅支持 Vue，历史回退需恢复托管兼容代码。真实业务/API 和 Vue 行为测试继续保留，旧 HTML/JS 专属断言已退役。详见 [发布与回退](admin-frontend-release.md)。

## 来源与标记

| 来源编号 | 当前代码依据 |
|---|---|
| S1 | `app/static/index.html`：9 个导航、8 个 dialog、模型页签与复核表单 |
| S2 | `app/static/app.js`：鉴权、路由式视图切换、看板、流、告警、规则、参数、推送 |
| S3 | `app/static/conversion.js`：动态模型/校准表单、XHR 上传、配置、任务轮询、登记及绑定覆写 |
| S4 | `app/main.py`：业务 HTTP、媒体、WS、权限和 Pydantic 请求模型 |
| S5 | `app/auth.py`：Cookie/Bearer、角色、账号初始化和会话 API |
| S6 | `app/conversion_api.py`：转换路由、原始文件上传、任务、校准集 |
| S7 | `app/alerts/rules.py`、`app/stream.py`：算子能力检查、单流单模型绑定 |
| S8 | `Dockerfile`、`.dockerignore`、`deploy/nginx/aiyolo.conf.example`、`deploy/k8s/production/ingress.yaml`：部署和透传路径 |

标记：**实接**表示当前页面已调用真实服务；**部分**表示页面有真实与占位混合；**演示**表示仅 Demo；**后端**表示现有 API 可用但旧 UI 未完整接入。各行的“迁移验证”是未来验收要求。

## 导航与主要工作流

Vue 路径以正式 `/admin/` 为 base；预览使用 `/admin-next/`，相对页面路径相同。

| 编号 | 菜单 / 相对路由 | 当前能力与接口编号 | 迁移验证 | 任务 / 来源 |
|---|---|---|---|---|
| F01 | 会话 / `login` | 实接：首次管理员初始化、登录、状态恢复、退出；A01 | 登录前不读业务；密码不持久化；401/403 分开处理；operator 显示权限说明 | T03 / S1 S2 S5 |
| F02 | 外壳 / 所有路由 | 部分：9 菜单、时钟、真实流/告警数字；项目名是固定文案 | 根页和深链刷新；窄屏导航；数字来自 API；项目标识不冒充配置；退出关闭订阅 | T04 / S1 S2 |
| F03 | 总览 / `overview` | 实接：流、告警、推理状态、趋势、最新事件和新建流；A02 A03 A05 | 零值与不可用区别；告警跳转；无证据回退；新建失败保留输入 | T09 / S1 S2 |
| F04 | 数据看板 / `dashboard` | 实接：today/7d/30d、资源、事件分布、处置、复核用量及四路视频墙；A02 A04 A05 | 周期切换重新请求；全屏/Escape；完整画面；未知 GPU 显示不可用；误报率无基线保持暂无 | T09 / S1 S2 |
| F05 | 视频流 / `streams` | 实接：列表/刷新、选择、创建、启停/删除、YOLO、置信度/FPS、诊断播放地址和检测旁路；A03 A04 W02 | 启停后新建预览连接；参数失败回滚；区分配置与运行状态；切流释放资源；真实 RTSP 恢复 | T06 / S1 S2 S4 |
| F06 | 告警中心 / `alerts` | 实接：严重度筛选/计数、列表、详情、证据、确认、误报、复核；A05 A06 W01 | eventId 一致；保留微秒时间语义；权限拒绝；证据失效；重复处置；WS 后刷新事实 | T05 / S1 S2 S4 |
| F07 | 报警推送 / `push` | 演示：目标新增、启停、模拟测试；Live 明确未保存。后端：通道状态、回执、测试投递；A08 | 接通已有状态/回执及显式测试；无目标 CRUD 时禁用编辑并说明；无伪成功、无演示地址泄露 | T08 / S1 S2 S4 |
| F08 | 规则配置 / `rules` | 部分：真实列表、审计、能力拒绝；Live 弹窗保存未写 API。后端：CRUD、绑定与校验；A07 | 用现有 API 保存；先校验再绑定；显示版本/拒绝；未实现算子不可启用；不新增多模型调度选项 | T08 / S1 S2 S4 S7 |
| F09 | 模型资产 / `models?pane=catalog` | 实接：搜索、场景筛选、目录/详情、参数、激活/卸载、流绑定和 Manifest 登记；A09 A10 A11 | `serverBindable` 为绑定依据；激活只改新流默认；当前激活/已绑定模型卸载拒绝；不回退 Mock | T07 / S1 S2 S3 S4 |
| F10 | 模型资产 / `models?pane=calibration` | 实接：列表/版本信息、ZIP 上传、刷新/删除、内容哈希和引用保护；A13 | ZIP 原始体；真实进度；非法 ZIP、413/429、被引用/内置不可删除 | T07 / S1 S3 S6 |
| F11 | 模型资产 / `models?pane=upload` | 实接：PT 上传、模型族选择/新 ID、配置、校准选择、任务/重试/日志/移动端转换；A12 A14 | 成功清空文件/名称/进度，失败保留；进度真实；排队/中断/签名未就绪清楚；并发按钮防重放 | T07 / S1 S3 S6 |
| F12 | 系统诊断 / `diagnostics` | 实接：健康、数据库、真实资源、流概况和 API 边界；A02 | healthz 非 2xx 不误报成功；未配置 DB/无 GPU 明确；可选 metrics 不增加伪数据 | T08 / S1 S2 S4 |
| F13 | 智能复核 / `verification` | 已退役：路由、菜单、配置及告警结果展示已移除；旧 API 写操作返回 410，历史记录保留 | 不作为当前后台功能或验收入口 | M25-T09 |
| F14 | 显式 Demo / 外壳控制 | 演示规则与推送；模型始终真实；告警不使用 Mock | 明显标识；不对生产写入；退出 Demo 刷新；接口失败不得自动进入 Demo | T04 T08 / S1 S2 S3 |

当前告警页面没有服务器分页接口、搜索或持久筛选；需要分页时仅可对已取回列表做客户端分页并标明范围，不能虚构服务器 total/page 契约。当前流编辑只直接暴露已有控件；展示名称等可复用已存在 PATCH 字段，不要求改后端。

## 弹窗、筛选、文件与表单细项

| 编号 | 原入口 / 当前字段 | 对等要求与接口 | 任务 |
|---|---|---|---|
| D01 | `new-stream-dialog`：stream-id、source-url | POST A03；ID 格式按服务端；空 source 为推帧；失败保留；取消无写入 | T06 |
| D02 | `register-model-dialog`：manifest-path | POST A09；由 S3 实接；路径是服务端受控 Manifest 位置；登记失败不关闭 | T07 |
| D03 | `model-parameter-dialog`：android/server、检测阈值、IoU、最大结果、类别规则、审计 | GET/PUT/DELETE A10；revision 原样携带；搜索/折叠、启用、名称/编码、拍照/相机阈值、连续帧/停留/冷却、严重度、恢复默认、解释提示 | T07 |
| D04 | `model-detail-dialog`：身份、状态、产物、原始类别 | 真实 modelId/版本及状态；下载链接按 A11；签名/可用性不能凭文件名推断 | T07 |
| D05 | `model-uninstall-dialog`：二次确认、反馈 | DELETE A09；409 展示占用；取消/关闭不触发卸载；不预先从列表移除 | T07 |
| D06 | `alert-detail-dialog`：证据、元数据、复核、确认/误报 | A05 A06；图片缺失；重复操作；处置与复核独立；仅注释不删除原始事实 | T05 |
| D07 | `rule-dialog`：name、operator、roi | 原表单不足以构成 RuleRequest；迁移为完整 ruleId、targetLabels、subjectKind、requires、thresholds、ROI/绑定编辑；A07 校验 | T08 |
| D08 | `push-dialog`：name、type、url | Live 未提供保存契约；保留不可用说明，Demo 可模拟；不得把 test-delivery 当配置保存 | T08 |
| Q01 | 告警 all/critical/important/normal | severity/notifySeverity 映射及真实统计；空/错/加载；eventId 稳定 | T05 |
| Q02 | 看板 today/7d/30d | A02 的 range；不缓存旧周期假装新周期结果 | T09 |
| Q03 | 模型关键字、scenario、3 页签 | 搜索模型身份/标签相关展示；场景筛选；查询参数保留选中页签；刷新不丢输入 | T07 |
| U01 | PT 上传：文件、名称、modelId/模型族、version、scenario、校准集 | A14；原始体；文件选择反馈、进度、上传成功/失败状态 | T07 |
| U02 | 校准上传：ZIP、name、version、scenario | A13；详情/内容哈希、受保护版本；真实上传进度 | T07 |
| U03 | 转换配置：mode、distribution、python_path、input_size、timeout_seconds、auto_convert、default_calibration_dataset_id | A12；展开/收起；当前任务冻结旧配置；环境检查是入队任务 | T07 |
| U04 | 远程转换配置：remote_endpoint、remote_token_env、remote_allow_insecure_http、remote_poll_interval_seconds、remote_verifier_mode | A12；仅环境变量名，不输入 Bearer 明文；HTTP 仅开发配置；remote 结果仍需本地复验 | T07 |
| U05 | 任务操作：queued/running/succeeded/failed/interrupted、attempt、queue_position、stage、progress、日志 | A12 A14；秒时间戳；活动页轮询；不确定进度；失败/中断可按当前配置重试；离页/退出停止轮询 | T07 |
| U06 | 下载：产物、误报 JSON、任务纯文本日志、事件证据 | A11 A05 A12；Blob/文本正确处理；文件名；释放 objectURL；日志与密码脱敏 | T05 T07 |
| V01 | 复核表单开关、授权、dailyLimit、modelId | A06；确认图像出站；读取已有配置；错误不报成功；无额度不抹去事件 | T08 |

全部对话框统一验证 Escape、关闭、取消不提交，提交禁重，失败保留内容，焦点返回触发按钮；关键写入结果进入 `aria-live` 提示。8 个原生 dialog 不要求原样保留 DOM ID，但必须由上述编号覆盖。

## HTTP 契约矩阵

所有下列相对路径的前缀是 `/aiyoloapi`（healthz 除外）。A=admin；R=已登录 admin/operator 可读；P=公开初始化/状态。未经实现不得新增 `/api` 别名。大括号为实际路由参数名。

| 编号 | 方法与相对路径 | 权限 | 输入 / 响应 / 必须保留语义 |
|---|---|---|---|
| A01 | GET `/auth/status`；POST `/auth/setup`、`/auth/login`；GET `/auth/me`；POST `/auth/logout` | P / 会话 | status 的 setupRequired/authenticated/user；setup/login JSON username/password，Cookie 与 accessToken/tokenType/expiresIn/user；me 非 legacy 会话；logout 撤销并清 Cookie；setup 已完成为 409 |
| A01b | GET/POST `/auth/users` | A | 现有 API，旧菜单无账号管理页；迁移不增加该页面；保持权限回归 |
| A02 | GET `/dashboard/stats?range=today|7d|30d`、`/metrics`；GET `/healthz` | A；healthz P | stats 的 summary/trend/streams/system/verification 等按真实响应定义；metrics `{system,streams}`；stats 不可用 503；healthz 自身可能 503 |
| A03 | GET/POST `/streams`；PATCH `/streams/{stream_id}/config`；POST `/streams/{stream_id}/yolo`；DELETE `/streams/{stream_id}`；GET/PUT `/streams/{stream_id}/model` | GET R；写 A | 列表是数组；创建 JSON stream_id/source_url/model_id/display_name/source_type/enabled，201；PATCH 仅发送变更字段；YOLO `{enabled}`；绑定 `{model_id}`；删除 204 |
| A04 | GET `/streams/{stream_id}/mjpeg`、`/streams/{stream_id}/playback` | R | MJPEG 持续图片流而非 JSON；playback 返回 stream_id 与媒体协议状态；停用/恢复与新连接；URL 隐私与缓存 |
| A05 | GET `/alerts`（可选 status）、`/alerts/{event_id}`、`/alerts/{event_id}/evidence`、`/alerts/false-positives/export`；POST `/alerts/{event_id}/acknowledge`、`/false-positive`、`/close` | 读 R；写 A | 列表 `{events}`；eventId、sourceId、ruleId、severity/notifySeverity、startedAtUs/confirmedAtUs、evidence、disposition 原样；写 JSON note 可选，actor 默认账号；证据二进制；导出 JSON attachment |
| A06 | 历史 GET/POST `/verification/config`；GET/POST `/alerts/{event_id}/verification` | GET 仅历史读取；写操作 410 | 已退役，不用于新客户端；历史结果/配置数据保留 |
| A07 | GET/POST `/rules`；GET/PUT/PATCH/DELETE `/rules/{rule_id}`；GET `/rules/audit`（可选 rule_id）；GET/POST `/rules/{rule_id}/bindings`；POST `/rules/{rule_id}/validate`；GET `/capabilities/sources` | A | `{rules}`、`{audit}`、`{bindings}`、`{sources}` 包装；RuleRequest 与 Patch 以 S4 为准；绑定/校验 `{sourceId,capabilities,modelId?}`；validate 可能 200 + accepted=false；bindings 拒绝为 409；delete 204 |
| A08 | GET `/alerts/delivery/status`；POST `/alerts/test-delivery` | A | channels/pending/recent；测试 JSON event/channels，202 `{accepted,deliveryIds}` 只表示入队，投递成功以回执为准；没有目标 CRUD |
| A09 | GET `/models`（可选 scenario）、`/models/{model_id}`；POST `/models/register`、`/models/{model_id}/activate`；DELETE `/models/{model_id}` | 读 R；写 A | `{models}`；register `{manifest_path}`；激活不覆盖已绑定流；卸载占用 409；serverBindable/androidBindable、readiness 不由 UI 重算为就绪 |
| A09b | GET `/models/{model_id}/versions`、`/versions/{version}`；POST `/models/{model_id}/migrate`、`/versions/{version}/deprecate`、`/versions/{version}/revoke`；DELETE `/models/{model_id}/versions/{version}` | 读 R；写 A | 后端版本/生命周期契约；旧 UI 主要展示当前投影，未提供完整写操作；需展现现有状态，新增操作只能用已存在模型和权限，禁止伪造版本 API |
| A10 | GET/PUT/DELETE `/models/{model_id}/parameters?platform=android|server` | GET R；写 A | 检测参数、类别 alertRules、revision/audit；PUT 把读取的 revision 放入 expectedRevision 进行乐观锁检查，409 提醒重载，不能覆盖他人修改；DELETE 恢复默认 |
| A11 | GET `/models/{model_id}/artifacts/{artifact_id}/download`、`/models/{model_id}/versions/{version}/artifacts/{artifact_id}/download` | R | 二进制下载、响应文件名/内容类型；签名、版本、产物可用性门禁；拒绝原因原样显示 |
| A12 | GET/PUT `/conversion/config`；POST `/conversion/check`；GET `/conversion/jobs`、`/conversion/jobs/{job_id}`、`/conversion/jobs/{job_id}/log`；POST `/conversion/jobs/{job_id}/retry` | A | config 包装 + 上传限制/supported_modes；jobs `{jobs}`；log 为 text/plain；check/retry 202 任务；配置字段保留 snake_case |
| A13 | GET/POST `/conversion/calibration-datasets`；GET/DELETE `/conversion/calibration-datasets/{dataset_id}` | A | `{datasets}` 与限制；POST 查询 filename/name/version/scenario + ZIP 原始体，201；DELETE 引用保护 409；ZIP 无效 422、超限 413、忙 429 |
| A14 | POST `/conversion/uploads`；POST `/conversion/uploads/{upload_id}/mobile` | A | 查询 filename/name/version/scenario/modelId + PT 原始体；202 `{upload_id,model_id,job}`；mobile 查询 calibrationDatasetId；服务端冻结校准快照；不可混淆 upload_id/model_id/job.id |

A09b 的简写路径均以 `/models/{model_id}` 为前缀。已存在的 `/alerts/{event_id}/ack`、`/mark-false-positive`、`/alerts/export/false-positives` 等兼容别名保持不变，新客户端使用矩阵的主路径。

类型不全局归一化：告警业务时间为微秒，转换 job 时间为秒，浏览器 Date 为毫秒。`platform` 是模型参数档案，不能与推理运行时或产物平台随意互换。流 source_url 的脱敏结果是展示数据，不可回填为真实凭据保存。

## WebSocket 与媒体

| 编号 | 路径 / 权限 | 当前格式 | 迁移处理 |
|---|---|---|---|
| W01 | `/aiyoloapi/alerts/ws`（别名 `/alerts/events`），A | JSON `{type:"alert",event}` | Cookie 认证；收到事件刷新告警/统计；退避重连；退出停；不无限重试 4401 |
| W02 | `/aiyoloapi/streams/{stream_id}/detections`，operator 或 admin | 检测 JSON；YOLO 关闭心跳 `{stream_id,yolo_enabled:false}` | 视频与检测独立；切流关闭旧连接；4404 刷新；保留检测信封字段 |
| W03 | `/aiyoloapi/alerts/notifications`（别名 `/alerts/app`），operator 或 admin；`/streams/{stream_id}/ingest`，operator 或 admin | App 通知 JSON；ingest 二进制 JPEG/PNG 与文本控制 | Android 既有契约，仅兼容回归；管理前端不接管采集 |
| W04 | `/aiyoloapi/streams/{stream_id}/ws` | 二进制 JPEG；当前无会话认证调用；4429 限制 | 仅诊断探针；新页面不作为默认视频通道；记录既有权限缺口 |
| M01 | A04 MJPEG、playback 中 WHEP/LL-HLS/RTSP | MJPEG 诊断；生产 WHEP，LL-HLS 回退，RTSP 诊断 | 保留 ADR-002 边界；contain；关闭/重开替换 MJPEG URL；卸载释放播放器 |

## 错误与安全行为

| 情况 | 客户端处理 |
|---|---|
| 网络失败/请求取消 | 取消不报业务错误；其他失败可重试读取；写入超时先查事实，不自动重发 |
| 401 | auth/me 去重核对；失效去登录，有效则提示权限不足；停止相关订阅 |
| 403 | 权限/处置拒绝，保留会话，禁止通过更换 header 绕过 |
| 404 | 事件/流/模型不存在；刷新上层列表，详情显示缺失 |
| 409 | revision 冲突、占用、产物不可用、绑定拒绝/已有任务；保留表单并显示原因 |
| 422 | 兼容 detail 字符串、`{code,message,missing}`、Pydantic 数组；对字段反馈 |
| 413/429/507 | 上传超限、忙或磁盘不足；保留所选文件，不能报上传成功 |
| 503 / healthz 非成功 | 服务或仓储不可用；显示不可用，不把失败当空库 |
| 204 / 文本 / Blob | 不强制 JSON 解析；下载检查状态后才提供文件 |
| 敏感内容 | 不打印 Cookie/token/密码/密钥/完整 RTSP 凭据；文本通过 Vue 转义；不从错误对象拼接 HTML |

## 基线缺口及裁定

| 缺口编号 | 源码事实 | 本次处理 / 归属 |
|---|---|---|
| G01 | Live rule-form 不保存，现有后端具备 CRUD/绑定/校验 | T08 补齐完整表单并接已有 API；不能继续显示“保存”却未保存 |
| G02 | Live 推送目标列表/新增无 API；只有 delivery/status 与 test-delivery | T08 展示真实通道/回执、显式测试；目标编辑标为不可用；目标 CRUD 另立后端任务 |
| G03 | 复核 GET config 未用于初始化；POST fetch 未检查 response.ok；endpoint/key/timeout 不在请求模型 | T08 恢复和验证现有五字段；供应商配置项只读/不可用；测试改为配置检查说明；真实探测另立任务 |
| G04 | 单个流 bind_model；COMPOSITE/RELATION/METRIC_THRESHOLD 绑定拒绝 | T08 明确能力边界；前端不得承诺多模型并行/融合；专门后端编排任务后才能开启 |
| G05 | require_admin 角色不足也返回 401；旧登录页可解锁 operator 后业务失败 | T03 核对真实身份再解释错误；operator 不进入完整后台；服务端契约不改 |
| G06 | 静态源码测试使用 DOM 字符串；新路由/组件尚不存在 | 每页补行为测试后才退役对应源码断言；不直接删除整套管理/API 测试 |
| G07 | 原生 StaticFiles 不提供 Vue 深链回退；外部字体、脚本覆写顺序有依赖 | T02 实现限定回退；T04 本地基础字体；Vue 不加载旧全局脚本 |
| G08 | 系统既有诊断 JPEG WS 无会话鉴权调用 | 前端不用该默认通道；后端安全整改须单独任务，不在文档任务中改代码 |

以上缺口必须在最终验收中注明处理结果。没有后端契约的配置能力以不可用说明交付，不填写“完成真实 CRUD/探测”；新增后端功能另行补任务和验收。

## 验证追踪与执行门禁

| 验证编号 | 方法 | 后续证据 |
|---|---|---|
| C01 | 对照 S1 的 data-view 逐一覆盖 9 菜单；dialog ID 逐一覆盖 D01–D08 | T01 源码覆盖核对；T04/T10 浏览器导航截图与深链验证 |
| C02 | 逐项核对 S2/S3 的 URL、方法、表单字段与 S4–S6 的路由/权限 | T01 静态路由审计；T03 类型/Client 契约；各页面行为回归 |
| C03 | 保留现有 `tests/test_admin_*.py` 基线；隔离的 API/权限测试 | T01 回归结果；迁移页测试记录 |
| C04 | 无权限/过期、断线、空库、503、上传失败、revision 冲突 | T03/T05–T08 使用独立测试夹具；不清空开发数据库 |
| C05 | 桌面与窄屏、全屏、键盘、对话框焦点、媒体卸载 | T04/T10 实际浏览器证据；不得以源码断言替代 |
| C06 | 两套构建 base、深链、静态 404、缓存、回退包/配置 | T02 静态托管自动验证；T10 部署切换与回退演练 |

T01 只验证文档、代码基线和任务结构。Vue 功能、生产媒体质量和最终部署验收仍待对应任务执行。
