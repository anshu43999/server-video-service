# 项目场景与运行方案

项目场景是项目内的业务工作配置，与模型资产分类和项目模型授权清单分离。项目模型回答“本项目可用哪些精确模型版本及目标端”；场景/方案回答“本次业务任务选择哪些已分配模型、使用什么输入和运行策略”。项目模型页不按场景分组。

## 存储与升级

场景以 `(project_id, scene_id)` 隔离；成员引用同项目的稳定 `projectModelId`，并在场景 revision 中固定目标端、成员顺序、输入能力及方案参数快照。position 从 0 连续排序，不是成员身份。一个项目模型可以被多个场景复用；场景成员不能越过项目模型清单直接引用全局模型目录。

未配置数据库时使用显式进程内存后端；配置数据库则场景、成员与成功审计同事务提交，失败全部回滚。PostgreSQL 使用项目行锁串行化跨进程首次创建与更新，所有写入校验 expectedRevision。启动 schema 健康检查要求新表；发布时应通过既有迁移流程升级，本次未执行生产升级。非空场景表禁止 downgrade，避免误删配置。

## 管理 API

以下路径以 `/aiyoloapi/projects/{projectId}/scenes` 为前缀，创建、修改要求 `project.scenes.manage`，批准/撤销要求 `project.scenes.approve`，当前授予 PROJECT_OWNER 及显式平台项目入口；普通 PROJECT_USER 不具备管理权限，暂停/归档项目不可写。读取要求 project.read；管理者可诊断未批准/不可用配置，用户只看到当前活动项目内已启用、已批准、模型端产物有效的场景。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | 空路径 | 当前项目内创建的场景列表 |
| POST | 空路径 | 创建（expectedRevision=0），201 |
| GET | `/{sceneId}` | 场景详情，缺失 404 |
| PATCH | `/{sceneId}` | 修改 name/inputTypes/enabled |
| PUT | `/{sceneId}/members` | 原子替换、增删或重排成员 |
| POST | `/{sceneId}/approval` | 批准或撤销，携带 approved、expectedRevision、reason |
| GET | `/{sceneId}/members/{memberId}/artifacts/{artifactId}/download` | 仅下载获准场景成员的精确目标端产物 |
| POST | `/{sceneId}/resolve` | 解析单成员配置，不启动推理 |

创建载荷：

```json
{"sceneId":"site-safety","name":"现场安全","inputTypes":["image","video"],"enabled":true,"expectedRevision":0,"members":[{"memberId":"member-helmet","projectModelId":"pm-helmet-pc","position":0,"inputTypes":["image"],"parameterRevision":4}],"plans":[{"planId":"image-safety","inputTypes":["image"],"memberIds":["member-helmet"],"execution":"single","enabled":true}]}
```

至少一个成员、最多 100 个；inputTypes 非空无重复。同一项目模型在一个场景内不可重复，成员位置连续。每个 `projectModelId` 必须属于当前项目且处于启用状态；服务端从该清单项读取精确模型版本/目标端，并复核目标端发布、产物就绪及输入能力。不能通过传入 modelId/version 绕过项目模型分配，也不存在以模型 `scenario` 标签关联成员的规则。

所有修改递增 revision 并清除 approved；创建不是批准或运行授权。可停用包含已撤回/损坏成员的场景；重新启用、修改输入、成员或方案必须重新校验。项目模型停用或移除后，依赖该模型的场景不能批准或取得新的运行授权，且必须显式修订场景解除引用。项目模型参数 revision 更新后，旧场景成员快照不会被静默替换；批准将返回 `project_model_revision_conflict`，管理者必须通过 `PUT /{sceneId}/members` 重新提交该 `projectModelId` 与最新 `parameterRevision`，待场景 revision 更新后再批准。

成功写入产生 `scene.create` / `scene.update` / `scene.approval` 项目审计，含操作者、服务端生成 requestId、前后 revision 和快照。批准记录 reason，批准和撤销都递增 revision。失败不会生成成功审计。过期写入 `409 revision_conflict`，重复创建 `409 scene_id_conflict`，格式问题 422。写入在项目锁内重新检查数据库账号/当前成员角色；请求开始时的 capability 不替代事务内的撤权检查。

## 用户目录和下载

GET 列表/详情可带 `target=pc|mobile` 与 `inputType=image|video`。过滤后保留 revision、精确版本、成员位置、双方就绪状态和 execution；仅返回当前请求端成员，不把另一端缺失误报为本端失败。M36-T08 增加 `executionSupportByTarget.pc/mobile`：每端恰好一个 single 成员才支持该端预检。带 target 时 executionSupported 表示该端；省略时只有所有有成员的端均满足单模型 single 才为 true。同一版本双端两条部署不再误判为同端多模型。

普通用户没有权限看到草稿、禁用、撤销批准或成员损坏的查询投影；直接访问详情统一 404。每次读取重新计算模型生命周期、已发布目标、文件完整性和输入适用性。返回产物仅包含当前成员目标端与场景作用域下载 URL，不暴露主机路径或其他版本下载地址；下载请求再次校验当前会话成员、项目生命周期、批准状态、目标、精确版本及哈希。即使 PROJECT_OWNER 也不能用草稿下载。权限撤销、暂停/归档、模型撤销及文件篡改在下次读取/下载生效，不使用旧目录响应作为授权令牌。已开始传输的字节无法追溯撤回。

场景批准冻结当前成员身份、目标端、方案选择和批准参数修订；它不创建或修改项目模型清单。安装准备、目录读取、场景 resolve 和运行授权仍是不同操作，只有显式选择的 sceneId/planId 可进入运行流程。

## 执行边界

resolve 要求 `project.inspection.use`，并绑定 sceneId、planId、sceneRevision、target 和 inputType。resolve 是在线解析，不会替调用方选择默认场景/方案，也不是离线授权凭证或运行授权；运行开始必须再获得与当前场景/方案及完整成员集合一致的 runtime grant。支持的 single/sync/async 语义由方案明确声明，未被服务端和客户端共同支持的执行方式必须拒绝，不能静默丢弃成员或回退到项目模型单模型执行。
