# 模型目标端能力与项目场景配置契约（历史 v1）

> 历史契约，项目模型/场景边界已由 M33-T36 取代。下文项目授权和旧场景迁移规则不再作为实现依据；当前规则见 `project-model-assignments.md` 与 `project-scenes.md`。平台模型目标端能力和产物就绪语义仍可参考本文件。

版本：`1.0`（M36-T01）；状态：冻结，服务端、PC 管理后台与 Android 后续实现共用。

本契约定义模型版本的目标端能力，以及项目场景作为独立业务配置的身份、授权和成员关系。它只冻结元数据/API 语义，不实现多模型推理编排。第一阶段继续使用既有单模型运行链路；同步/异步多模型调度属于后续任务。

## 1. 核心对象与边界

- **模型族**：稳定 `modelId`。
- **逻辑模型版本**：不可变的 `(modelId, version)`。版本拥有平台声明的 `supportedTargets`，取值为 `pc`、`mobile` 的非空子集；仅 `pc` 表示 PC 模型，仅 `mobile` 表示移动端模型，两者均有表示双端模型。该字段是支持/发布目标声明，不由文件扩展名推断。
- **端侧产物**：绑定到逻辑模型版本并按 `target` 独立登记、签名/哈希校验和计算就绪状态。`pc` 与 `mobile` 的产物可独立存在和独立就绪；缺少未声明为支持目标的产物不构成失败。双端版本也允许其中一端先就绪，目录必须分别报告端状态；只能向已就绪且授权的端分配/下载。
- **项目场景**：项目内有稳定 `sceneId` 的业务配置；场景不是模型分类，也不等同于模型版本已有的 `scenario` 标签。一个场景包含一项或多项精确模型版本成员以及图片/视频输入适用性。
- **模型成员**：场景内有序引用 `(modelId, version)`，并可附带仅供后续运行编排使用的运行语义声明。成员不能复制或覆盖平台模型元数据。

模型版本现有 `scenario` 字段继续兼容旧目录、搜索过滤和历史分配，不再作为新场景主键或隐式授权条件。新项目可建立任意 `sceneId`，即使成员模型的旧 `scenario` 值不同。

## 2. 目标端就绪与发布规则

模型目录 v3 在现有 v2 字段上增量增加：

```json
{
  "modelId": "person-detection",
  "version": "2.1.0",
  "supportedTargets": ["pc", "mobile"],
  "targetReadiness": {
    "pc": {"ready": true, "artifactIds": ["pc-onnx"]},
    "mobile": {"ready": false, "reason": "artifact_missing", "artifactIds": []}
  }
}
```

`targetReadiness` 是服务端根据登记产物存在性、大小、SHA-256、签名和目标端发布策略计算的投影，不信任客户端上报的 ready 值。目标端未声明时可返回 `supported=false`，不得把缺少产物说成校验失败。`serverReady` / `androidReady` 保留为旧客户端兼容别名，语义映射到 `pc` / `mobile`；旧 `artifacts[].platform` (`server` / `android`) 和现有格式保持可读，新写入规范化为 `target=pc|mobile`，兼容层负责映射。

发布与授权以目标端为单位：只有请求/分配端必须在 `supportedTargets` 中且该端 `ready=true`。PC-only 发布不要求 TFLite、Android Manifest 或 Android 签名；mobile-only 不得用于 PC 推理；双端可以先发布/授权其中一个已就绪端，另一端之后补齐。转换是按目标端按需执行的可选工作，不是逻辑模型版本发布的通用前置条件。签名、哈希、许可证和生命周期策略仍适用于对应端产物，不因放宽跨端转换要求而移除。

下载与项目目录响应必须过滤到当前项目已批准、当前用户可见、目标端匹配且产物就绪的精确模型版本；下载前复验产物。响应不暴露服务端绝对路径、签名私钥或非授权端产物下载地址。

M36-T02：上传通过重复查询参数 `supportedTargets=pc&supportedTargets=mobile` 声明目标，显式 PC-only 不自动触发或允许移动转换；省略参数保留旧数据派生语义。平台发布使用 `POST /aiyoloapi/models/{modelId}/versions/{version}/publish`，载荷 `targets`、`licenseApproved=true`、`reason`。`targetReadiness` 表示端产物就绪，`targetReleaseEligible` 才表示该端已发布可分配，不能用全局 `releaseEligible` 推断所有端均已发布。既有登记产物的启动完整性检查保持 fail-fast；独立就绪不意味着容忍已登记文件篡改。历史 READY 版本若无服务端验证证据，须重新验证后才可新发布，不从旧 ready 标记补造试推理成功。

## 3. 项目场景数据与 API 草案

场景是项目隔离资源，建议新增以下路径；不得复用当前以 `(projectId, scenario)` 为键且只保存单模型的旧 assignment 表来表达多成员：

```text
GET    /aiyoloapi/projects/{projectId}/scenes
POST   /aiyoloapi/projects/{projectId}/scenes
GET    /aiyoloapi/projects/{projectId}/scenes/{sceneId}
PATCH  /aiyoloapi/projects/{projectId}/scenes/{sceneId}
PUT    /aiyoloapi/projects/{projectId}/scenes/{sceneId}/models
POST   /aiyoloapi/projects/{projectId}/scenes/{sceneId}/approval
```

场景创建/编辑、成员增删排序和批准都必须从会话重新解析当前项目成员与 capability；客户端自报用户/角色不授权。建议 `project.scenes.manage` 管理场景，批准/启停当前项目可用场景由 `project.scenes.approve` 控制；若落地前后端 capability 命名已有统一决议，实现任务应按同等或更严格权限映射并更新此契约。没有项目上下文返回 `400 project_context_required`，项目不可见返回 `404`，可见但 capability 不足返回 `403`。每次写入带 `expectedRevision`；过期返回 `409 revision_conflict`，不产生部分更新。项目暂停/归档遵循既有项目生命周期写入限制。每次成功写入记录操作人、项目、资源、revision、前后快照摘要及 request ID 审计。

创建请求示例：

```json
{
  "sceneId": "site-safety",
  "name": "现场安全",
  "inputTypes": ["image", "video"],
  "models": [
    {"modelId": "person-detection", "version": "2.1.0", "position": 0,
     "execution": "single"}
  ],
  "expectedRevision": 0
}
```

`inputTypes` 是非空集合，元素为 `image`、`video`。成员必须指向已发布、未撤回的精确版本；校验模型目标端、该端就绪、项目授权与适用输入。初期单成员场景沿用现有运行消费；多成员场景可保存和展示，但不得因此自动触发多模型运行。`execution` 现阶段只允许 `single` 或作为未来扩展存储的 `sync` / `async` 声明（默认 `single`）；对 `sync` / `async` 的运行请求必须返回明确 `409 execution_mode_not_supported`，不串行伪装并行、不丢弃成员、不宣称调度已实现。

读取示例：

```json
{
  "projectId": "project-123",
  "sceneId": "site-safety",
  "name": "现场安全",
  "inputTypes": ["image", "video"],
  "models": [{"modelId": "person-detection", "version": "2.1.0",
    "position": 0, "execution": "single",
    "targetReadiness": {"pc": true, "mobile": false}}],
  "enabled": true,
  "revision": 3
}
```

成员顺序仅为稳定展示/未来调度顺序，不定义同步/异步语义。`enabled`/批准状态只控制项目目录可用性，不等于运行时多模型支持。删除/停用、模型撤回和授权撤销必须在目录读取与实际执行前重新校验；沿用项目级授权与撤权后丢弃结果的既有安全边界。

## 4. 旧契约兼容与迁移（已退役）

本节规则已退役。测试阶段的新模型清单、场景与运行配置以当前迁移链和
`project-model-assignments.md`、`project-scenes.md` 为准。模型目录中的
`scenario` 仍可作为平台元数据读取，但不参与项目授权或场景成员解析。

## 5. 稳定错误码

| HTTP | code | 条件 |
|---:|---|---|
| 400 | `project_context_required` | 缺少显式项目上下文 |
| 403 | `project_capability_required` | 项目可见但缺少相应场景能力 |
| 404 | `project_not_found` / `scene_not_found` | 项目或场景不在操作者可见范围 |
| 409 | `revision_conflict` | `expectedRevision` 已过期 |
| 409 | `model_target_not_supported` | 模型版本未声明请求端 |
| 409 | `model_target_not_ready` | 请求端产物未就绪 |
| 409 | `model_not_project_authorized` | 精确版本未获项目批准/授权 |
| 409 | `scene_input_not_supported` | 场景/成员不适用请求输入类型 |
| 409 | `execution_mode_not_supported` | 请求 sync/async 运行但本阶段未实现编排 |
| 422 | `invalid_scene_request` | ID、输入类型、成员、顺序或 revision 格式无效 |

所有错误均遵循服务端统一错误 envelope（`error.code`、安全消息、可选 `request_id`、`retryable`）；兼容旧 FastAPI `detail` 表示，但客户端归一化为上述 code。

## 6. 阶段边界与验收方向

2026-10-20 M36-T08 增量澄清：一个模型版本可有 PC/mobile 独立项目分配，按端批准参数与 CAS；双端批量变更原子提交。旧单端不隐式授权另一端。场景预检按请求 target 的成员计算，每端单个 single 可解析，同端多成员或 sync/async 仍拒绝。详见 project-model-assignments.md 和 project-scenes.md；不扩大实际推理能力。

M36 第一阶段交付目标端能力声明、按端独立产物就绪/授权、项目场景 CRUD 与模型成员配置/授权及旧客户端兼容。不交付多模型推理执行器、同步并行策略、异步队列、聚合检测结果语义或多模型性能承诺；后续需单独冻结调度、超时、失败隔离、排序/合并、追踪及资源预算契约。

M36-T03/T04 是历史实现记录。当前成员必须引用项目模型清单项，当前运行与审批契约见 `project-scenes.md` 和 `project-scene-suite-v2.md`。

M36-T12 增量冻结见 `project-scene-suite-v2.md`：场景同时作为面向用户的业务模型套件，成员分别声明图片或本机 CameraX 输入适用性，运行方案显式选择成员；套件、安装准备和运行授权分离。同一可信精确产物允许被单独保留和多个套件引用，但不得以单值来源覆盖关系；清理受所有引用、运行槽位和回滚保护约束。v2 只冻结契约，单成员方案沿用当前运行门禁，同端多成员/sync/async 仍拒绝执行，远程视频不在范围内。
