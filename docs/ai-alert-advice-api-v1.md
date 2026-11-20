# AI 告警处置建议模拟服务契约 v1

## 系统统一资料与项目只读使用（2026-11-16，M41-T12）

本节取代 M41-T11 的项目固定继承、主动升级、复制覆盖及项目启停规则。平台管理员维护唯一系统资料草稿，通过 `/aiyoloapi/platform/alert-advice/publish` 显式发布不可变版本。所有获授权项目只读取最新已发布系统版本，未发布草稿不可见；项目内的平台管理员同样只读，维护须进入平台入口。

新项目不建立知识版本绑定；旧项目资料、修订和绑定行仅保留供历史审计，不再参与当前检索，也不自动合并到系统库。`GET /alert-advice/base` 兼容返回最新系统发布的 `version`、目录修订 `revision`、`mode=SYSTEM` 与空 `versions`，不表示项目关系。旧项目写入、覆盖、升级接口经认证与项目授权后统一返回 `410 PROJECT_KNOWLEDGE_READ_ONLY`，不写入知识数据。

发布后所有项目后续查询/生成使用新版本；客户端已有有界缓存按既有周期刷新，不承诺离线即时更新。新建议冻结 `knowledgeOrigin=SYSTEM` 与 `systemKnowledgeVersion`，既有建议仍展示原快照（含旧项目来源），不被系统更新改写。

实现清理（2026-11-16，M41-T13）：系统草稿校验/修订由独立模块管理，项目读取仓储无新增、编辑、启停、播种或本地资料回退方法。旧项目资料、修订和绑定表不再是运行时数据库健康检查的必需表；只保留ORM历史映射及原迁移链，没有删除现存业务数据。旧写接口410及历史来源兼容继续保留。

## 2026-11-05 详情读取约定（M29-T21）

打开告警详情时自动 GET `advice-generations/latest`，展示该项目/告警最近一次已保存的完整快照；这不是生成请求。仅用户点击生成、重新生成或明确的生成重试才 POST，历史版本保持不可变。`ADVICE_GENERATION_NOT_FOUND` 表示暂无建议，其他读取错误独立展示并只重试 GET。历史入口无需先生成，详情同身份后台刷新不重复读取；切项目、切告警或关闭后拒绝迟到响应。两端共享服务端快照，不要求对方实时推送；重新进入详情读取最新结果。仍为模拟资料/模拟生成。

状态：M41-T01 冻结；适用于服务端与 PC 管理后台。Android M114 仅作为字段语义对齐依据，本任务不修改 Android。

## 1. 目的与边界

告警建议是人工处置的辅助参考。只有用户在告警详情明确点击后才生成；告警产生、列表加载、详情打开、通知投递均不得自动触发。结果不得自动确认、关闭、标记误报告警或创建处置事实。模拟服务不读取、复制或外发证据图片/视频，不调用外部知识库或在线大模型。

“制度依据”统一表述为“可能相关的制度依据”。系统只返回资料原文及来源，不作违法违规认定。生成说明和制度原文必须保存、传输和展示为不同字段。

## 2. 规范化匹配键

唯一资料匹配键为 `(normalize(alertTypeId), normalize(recognitionCategoryId))`；`projectId` 仍用于请求授权、事件及建议快照隔离，不再决定资料所属或版本。`normalize` 与 Android M114 一致：去除首尾空白后使用与语言环境无关的大写转换。两个字段均不能为空；实现不得移除、替换或猜测中间字符。模型 ID、模型名称、展示名称、中文翻译、相似类别和证据内容都不能参与兜底匹配。

服务端只从已持久化告警事实解析匹配字段：

1. `alertTypeId` 优先取显式 `alertTypeId`；兼容既有事件时可取稳定 `ruleId`，不得取 `displayName`。
2. `recognitionCategoryId` 优先取显式字段；兼容既有事件时可取模型原始 `label`，不得取中文显示名或从模型名称推断。
3. 任一字段不存在、不是字符串或规范化后为空，结果为 `NO_MATCH`，`reasonCode=EVENT_MATCH_KEY_UNAVAILABLE`。
4. 知识仓储只允许返回完全相同的规范化键。返回键不一致属于 `RETRIEVAL_KEY_MISMATCH`，不能继续生成。

示例：`PPE_NO_HELMET + head` 规范化为 `PPE_NO_HELMET + HEAD`。`PPE_NO_HELMET + helmet`、正常佩戴类别或仅模型名称相同均不匹配。

## 3. 领域对象

### 3.1 KnowledgeEntry

知识条目包含稳定 `entryId`、规范化匹配键、标题、风险说明、零个或多个处置步骤、至少一条制度引用、适用条件、`status`（`ACTIVE`/`INACTIVE`）、单调递增 `revision`、创建/修改时间和操作者。

系统库同一规范化匹配键只能对应一个条目（含已停用项）；当前检索仅使用 `ACTIVE` 条目，不回退到旧项目资料或旧发布版本。项目读取保留 `projectId` 作为授权上下文，`entryId=system:<系统ID>`、`sourceEntryId` 为原始系统 ID、`origin=SYSTEM`，`systemVersion` 为发布版本；平台维护接口使用原始系统 ID。条目可以只有制度引用而没有建议步骤，此时生成 `PARTIAL`，不能伪造步骤。历史修订不可被原位改写。

### 3.2 AdviceStep 与 PolicyReference

每个建议步骤包含 `stepId`、`order`、`title` 和 `instruction`。制度引用包含稳定 `referenceId`、制度标题、可选制度编号、制度版本、章节、条款号、原文 `excerpt`、资料来源和 `sourceType`。M41 只允许 `sourceType=MOCK_KNOWLEDGE_BASE`。

`excerpt` 是制度资料原文；模拟生成的解释只能出现在 `advice` 或 `matchExplanation`，不能写入 `excerpt`。

### 3.3 AdviceGeneration

生成记录绑定 `generationId`、`eventId`、`projectId`、请求账号、幂等键、告警匹配键快照、状态、建议内容、制度引用快照、知识条目及修订、检索/生成提供方、匹配说明、错误和时间。后续知识修改不得改变历史记录。记录不包含媒体字节、data URL、本机路径、对象存储凭据或内部提示词。

终态如下：

| status | 含义 |
|---|---|
| `GENERATED` | 建议和制度引用均生成 |
| `NO_MATCH` | 无精确匹配或事件缺少稳定匹配键 |
| `PARTIAL` | 找到制度资料但生成建议失败或知识没有步骤 |
| `FAILED_RETRIEVAL` | 检索器内部失败或返回错误键 |
| `FAILED_GENERATION` | 生成器失败且没有可展示制度引用 |

运行内部阶段 `RETRIEVING`、`GENERATING` 不作为 v1 同步响应的持久终态。

## 4. 可替换服务边界

`AlertAdviceRetriever.retrieve(eventSnapshot, matchKey)` 返回 `NoMatch` 或包含知识修订、制度引用和生成种子的 `Matched`；`AlertAdviceGenerator.generate(eventSnapshot, matchedKnowledge)` 返回 `AdviceContent`。

Retriever 必须回传其实际命中的规范化键，服务层再次与请求键比较。Generator 只能读取脱敏事件快照、匹配说明、建议模板和制度引用；v1 不向它提供证据 URI 或媒体字节。

提供方枚举预留 `SIMULATED_KNOWLEDGE_BASE`、`KNOWLEDGE_BASE`、`SIMULATED_LLM`、`LLM`。M41 只能产生两个 `SIMULATED_*` 值，真实提供方启用须另行需求、配置和安全验收。

## 5. 项目 API

所有路径均以 `/aiyoloapi/projects/{projectId}` 为前缀，不提供无项目兼容别名。JSON 响应符合 `ai-alert-advice-v1.schema.json`。

### 5.1 知识资料只读使用

| 方法与路径 | 能力 | 语义 |
|---|---|---|
| `GET /alert-advice/knowledge-entries` | `project.alert_knowledge.read` | 最新系统发布列表与精确筛选，返回 `entries` 和 `systemVersion` |
| `GET /alert-advice/knowledge-entries/{entryId}` | `project.alert_knowledge.read` | 当前修订详情 |
| `GET /alert-advice/knowledge-entries/{entryId}/revisions` | `project.alert_knowledge.read` | 当前发布修订，`action=PUBLISHED`；不暴露草稿历史 |
| `POST /alert-advice/knowledge-entries/match-preview` | `project.alert_knowledge.read` | 精确键预览，不读取告警 |

以下项目路径均位于 `/alert-advice` 下，已退役：`POST /knowledge-entries`、`PUT /knowledge-entries/{entryId}`、`POST /knowledge-entries/{entryId}/status`、`POST /knowledge-overrides`、`POST /base/upgrade`。认证及项目授权通过后返回410。项目角色不再授予 `project.alert_knowledge.manage`。

平台维护以 `/aiyoloapi/platform/alert-advice` 为前缀，要求 `platform.alert_knowledge.manage`：条目 GET/POST/PUT、`/{entryId}/status`、`/{entryId}/revisions` 与 `/knowledge-entries/match-preview` 操作系统草稿；`GET /versions`、`GET /versions/{version}` 读取发布历史；`POST /publish` 发布。编辑/启停使用条目 `expectedRevision`，发布使用目录 `expectedRevision` 做 CAS；重复旧修订请求返回409，维护操作写入审计。

### 5.2 告警建议

| 方法与路径 | 能力 | 语义 |
|---|---|---|
| `POST /alerts/{eventId}/advice-generations` | `project.alert_advice.generate` | 用户主动生成 |
| `GET /alerts/{eventId}/advice-generations/latest` | `project.alert_advice.read` | 最近一次结果 |
| `GET /alerts/{eventId}/advice-generations` | `project.alert_advice.history.read` | 生成历史 |
| `GET /alerts/{eventId}/advice-generations/{generationId}` | `project.alert_advice.history.read` | 指定历史快照 |

生成请求可包含 `retryOfGenerationId`，但不能由客户端提交匹配键、建议、制度引用或媒体。相同项目、事件和幂等键以相同请求重放时返回原记录；载荷不同返回 `409 IDEMPOTENCY_CONFLICT`。新重试必须使用新幂等键。

模拟生成同步完成，首次创建返回 201，幂等重放返回 200。领域失败也返回持久化终态记录，只有请求、权限或基础设施失败使用 HTTP 错误。

## 6. 权限矩阵

| 行为 | 项目普通用户 | 项目负责人 | 显式进入项目的平台管理员 |
|---|---:|---:|---:|
| 查看/生成当前告警建议 | 允许 | 允许 | 允许 |
| 查看生成历史 | 允许 | 允许 | 允许 |
| 查看知识资料 | 允许 | 允许 | 允许 |
| 经项目接口新增、编辑、启停、覆盖、升级知识资料 | 禁止 | 禁止 | 禁止 |

系统资料仅平台管理员在平台入口维护。导航和按钮只用于可用性，服务端 capability 检查是授权边界。项目暂停/归档时遵循现有项目生命周期策略：历史和知识只读可保留，建议生成禁止。撤销成员关系或会话失效后立即拒绝。

## 7. 错误契约

错误响应使用 `detail={code,message,retryable?}`。

| HTTP | code | 含义 |
|---:|---|---|
| 400 | `PROJECT_CONTEXT_REQUIRED` | 缺少显式项目上下文 |
| 401 | `UNAUTHENTICATED` | 登录无效 |
| 403 | `CAPABILITY_REQUIRED` / `PROJECT_INACTIVE` | 无能力或项目不可写 |
| 404 | `EVENT_NOT_FOUND` / `KNOWLEDGE_ENTRY_NOT_FOUND` / `ADVICE_GENERATION_NOT_FOUND` | 资源不存在或不可见 |
| 409 | `REVISION_CONFLICT` / `IDEMPOTENCY_CONFLICT` / `ACTIVE_MATCH_KEY_CONFLICT` | 并发或唯一性冲突 |
| 410 | `PROJECT_KNOWLEDGE_READ_ONLY` | 项目知识写接口已退役，请使用平台维护入口 |
| 422 | `KNOWLEDGE_ENTRY_INVALID` / `MATCH_KEY_INVALID` | 字段或业务约束无效 |
| 503 | `ADVICE_STORE_UNAVAILABLE` | 持久化基础设施不可用 |

`NO_MATCH`、`FAILED_RETRIEVAL`、`FAILED_GENERATION` 和 `PARTIAL` 是可审计领域结果，不映射为 404/500。

## 8. v1 非目标与演进规则

v1 不包含向量数据库、PDF/Word 解析、语义检索、在线大模型、提示词管理、自动判责、自动处置或 Android 服务化接线。后续真实实现必须保持匹配键、结果分层、历史快照和权限语义；新增异步执行必须使用新契约版本，不能静默改变 v1。
