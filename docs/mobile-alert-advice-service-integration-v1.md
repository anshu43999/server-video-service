# Android AI 告警处置建议服务化接入方案 v1

状态：M41-T10 冻结方案；基于服务端 M41 契约 1.0 与 Android M114 已交付边界。本文只定义后续实施方式，不表示手机端已经接线，也不作为 API 27 联调通过证据。

## 1. 目标和边界

后续 Android 在告警详情中继续由用户点击“AI 处置建议”后发起请求，通过当前登录会话和当前项目访问 M41 生成 API，显示不可变结果快照。详情打开、识别完成、告警同步、通知到达均不自动生成。

本接入不得上传或读取证据图片/视频，不自动确认、关闭或标记误报告警，不把“可能相关的制度依据”改写成违规认定。v1 不在手机端提供知识资料维护、提示词管理、在线文档上传或真实大模型配置。

## 2. 兼容基线

| 层 | 冻结版本 | 兼容规则 |
|---|---|---|
| 服务端生成契约 | contractVersion=1.0 | 只接受已知字段与状态；未知主版本必须明确提示升级，不降级猜测 |
| Android 领域边界 | M114 AlertAdviceRetriever / AlertAdviceGenerator | 保留现有 UI 和 AlertAdviceUiGate；网络 DTO 不直接进入 View |
| 匹配键 | trim + locale-independent uppercase | 以服务端持久化告警事实为准；客户端不得在生成请求中提交或覆盖匹配键 |
| 提供方 | SIMULATED_KNOWLEDGE_BASE / SIMULATED_LLM | M41 阶段只能展示为模拟；真实提供方须由后续版本和安全验收放行 |

Android 请求仍可构造 M114 AlertAdviceRequest 用于界面身份和本地模式，但远端 POST 只提交可选 retryOfGenerationId。modelId、modelVersion、recognizedLabel 和媒体均不得作为远端生成请求体。

## 3. 认证、项目与资源身份

生成、历史和详情路径分别为：

- POST /aiyoloapi/projects/{projectId}/alerts/{eventId}/advice-generations
- GET /aiyoloapi/projects/{projectId}/alerts/{eventId}/advice-generations
- GET /aiyoloapi/projects/{projectId}/alerts/{eventId}/advice-generations/{generationId}

使用 App 现有动态账号 Session，不新增静态 token 或知识库密钥。projectId 必须来自当前 ProjectScope；eventId 必须来自该项目内当前告警。切换项目、退出登录、成员撤权或页面切换时取消请求并使 AlertAdviceUiGate token 失效。

平台管理员也必须显式选择项目。客户端不以 404 区分“资源不存在”和“无权访问”。响应的 projectId、eventId 必须与请求及 UI token 一致，否则作为协议错误丢弃且不展示。

## 4. 请求、幂等和重试

首次点击为本次操作生成 UUID Idempotency-Key，请求体为 {}。同一次仍在进行的请求只复用相同 UUID，按钮保持禁用，避免并发双发。

只有用户明确点击“重试生成/重新生成”才创建新 UUID。针对已持久化结果重试时，请求体包含 retryOfGenerationId。

网络在“已发送但未收到响应”状态下，不得立刻换新 UUID 盲重试；先用原 UUID 重放同一 POST，服务端返回原快照。载荷变化导致 409 IDEMPOTENCY_CONFLICT 时停止自动重试并提示刷新历史。

建议连接超时 10 秒，同步响应总超时 30 秒。401 走既有登录恢复；403/404 不重试；409 需用户刷新；429/503 和网络错误可在用户确认后重放原操作。退避不得跨越当前页面、项目或账号作用域。

## 5. 服务端 DTO 到 M114 的映射

DTO 必须先校验 contractVersion、资源身份、枚举和值约束，再转换为 Android 领域对象。

| 服务端字段 | Android M114 字段 | 规则 |
|---|---|---|
| matchKey.alertTypeId | AlertAdviceMatchKey.alertTypeId | 再次按 M114 规则规范化并校验 |
| matchKey.recognitionCategoryId | recognitionCategoryId | 不做相似类别兜底 |
| advice.title | AlertAdviceContent.title | GENERATED 时必需 |
| advice.steps[].title/instruction | AlertAdviceStep | 按 order 排序；GENERATED 至少一项 |
| advice.cautions | AlertAdviceContent.cautions | 不与制度原文合并 |
| references[].referenceId | AlertAdviceReference.sourceId | 稳定引用身份 |
| documentTitle / clauseId / excerpt | 同名展示字段 | excerpt 是制度原文 |
| sourceName | sourceName | 原样展示 |
| documentVersion | sourceVersion | M114 对应字段 |
| sourceType | AlertAdviceSourceType | MOCK_KNOWLEDGE_BASE 映射同名枚举 |
| retrievalProvider | AlertAdviceProvider | SIMULATED_KNOWLEDGE_BASE |
| generationProvider | AlertAdviceProvider | SIMULATED_LLM |
| matchExplanation | AlertAdviceResult.matchExplanation | 不得编造命中理由 |

终态映射：

| 服务端 status | M114 结果 | 展示与重试 |
|---|---|---|
| GENERATED | AlertAdviceOutcome.Generated | 展示建议和制度引用，可主动重新生成 |
| NO_MATCH | AlertAdviceOutcome.NoMatch | 明确无精确匹配，不启用本地其他类别兜底 |
| PARTIAL | Failed(GENERATING, references) | 保留制度引用，提示建议生成失败并允许重试 |
| FAILED_RETRIEVAL | Failed(RETRIEVING) | 不展示建议，按 error.retryable 决定文案 |
| FAILED_GENERATION | Failed(GENERATING, references) | 引用存在则保留；无引用只显示失败 |

M114 当前 Outcome 不保存 generationId、知识修订和错误码。后续实现应增加独立 RemoteAdviceMetadata 保存 generationId、knowledgeRevision、reasonCode、error.retryable 和完成时间，供历史、重试与诊断使用，不能塞入展示文本。

## 6. 建议的 Android 适配结构

Alert detail UI 调用 AlertAdviceCoordinator（用户操作、scope token、取消）；Coordinator 调用 RemoteAlertAdviceRepository（生成、历史、幂等）；Repository 内含 AlertAdviceApi（HTTP DTO）与 AlertAdviceDtoMapper（contract 1.0 到 M114 outcome）。LocalMockAlertAdviceRepository 只用于显式离线演示模式。

不建议直接把 HTTP 调用塞进 M114 的同步 AlertAdviceRetriever，否则检索和生成阶段会被错误拆成两次远端调用。远端 M41 是一次原子生成 API；RemoteAlertAdviceRepository.generate 应返回完整终态，再映射为现有 Outcome。M114 Retriever/Generator 保留给本地模拟与未来可拆分的真实 SDK 实现。

统一抽象建议为挂起式 AlertAdviceRepository，至少提供 generate(ProjectScope, eventId, AdviceOperation) 和 history(ProjectScope, eventId)。网络层不得持有 Activity/Fragment；取消沿协程传递。缓存键至少包含账号、项目和 eventId，退出登录、撤权或项目切换立即清理内存快照。除非另立数据留存任务，不把制度全文和建议历史写入无项目隔离的本地持久库。

## 7. 离线、降级与本地模拟退役

第一阶段建议提供三种显式模式：

- REMOTE_SIMULATION：默认；调用 M41，并显示服务端 sourceNotice。
- LOCAL_DEMO：只用于开发/演示构建；使用 M114 MockAlertAdviceCatalog，界面明确“本地模拟”。
- UNAVAILABLE：生产环境离线且无已验证快照时提示联网重试，不自动切到本地模拟。

可选离线只读缓存必须保存服务端快照身份、项目、完成时间和“离线历史”标识，不允许离线新生成。恢复网络后不自动重发用户已离开的操作。

退役顺序：先完成远端契约/JVM 测试，再由灰度开关将生产默认改为 REMOTE_SIMULATION；通过双项目撤权、离线和 API 27 联调后，删除生产构建中的本地目录注入；最后仅在测试 source set 保留 mock fixture。不得先删除 M114 fallback 再补网络链路。

## 8. 安全与可观测性

- 日志只记录 requestId、generationId、projectId、eventId 摘要、终态和耗时，不记录 Session、制度全文、内部提示词、媒体引用或响应全文。
- 埋点区分点击、HTTP 失败和领域终态；NO_MATCH 不是基础设施错误。
- UI 永远显示“可能相关的制度依据”和模拟来源，不得隐藏 sourceType。
- 未知字段可忽略，未知主版本、状态或提供方必须失败关闭。
- 历史快照只读；客户端不得把当前知识条目覆盖到旧结果。

## 9. 后续可执行任务建议

1. 冻结 Android 网络 DTO、RemoteAdviceMetadata 与金样的 JVM 契约测试。
2. 实现 AlertAdviceApi、Repository、DTO Mapper、同幂等键未知结果恢复与错误分类。
3. 将详情页 coordinator 接到远端 Repository，覆盖项目/账号/事件切换取消和结果防串。
4. 增加历史列表及指定快照读取，验证知识更新后旧结果不变化。
5. 在隔离服务/PostgreSQL、两个项目、负责人/普通用户/撤权账号上完成 HTTP 对账。
6. 固定使用 Codex_API_27 / emulator-5554 完成主动生成、无匹配、部分结果、超时、离线恢复、撤权、项目切换和进程重建测试。
7. 完成灰度开关和本地模拟退役；生产构建不得静默 fallback。

这些任务应在 Android 仓库按产品需求基线和 Harness create-major 流程另行评审创建；不得把 M41-T10 当作手机端实现或设备验收完成的替代证据，也不得让服务端任务反向依赖尚未创建的 Android 任务。

## 10. 验收金样

机器可读映射金样见 mobile-alert-advice-service-integration-v1-golden.json。实现至少验证：生成、无匹配、保留引用的部分结果、未知主版本拒绝、项目/event 身份不一致拒绝、禁止字段缺失保证和同幂等键重放。
