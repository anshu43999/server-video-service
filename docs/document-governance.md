# 后端与管理后台文档治理

> 生效日期：2026-11-12。类型：文档状态与使用规则，非独立需求基线。  
> 当前产品需求唯一来源：[PRODUCT_REQUIREMENTS.md](../PRODUCT_REQUIREMENTS.md)，同时覆盖服务端和admin-web。Android另见[App基线](../../mobile-app/docs/产品需求基线.md)。

## 1. 使用顺序

1. 先读需求基线的当前生效口径及FR/NFR，再读该能力的当前契约。代码、迁移清单和旧设计稿只帮助核对实现，不能自行扩大需求或降低验收标准。
2. 任务状态用本工程Harness CLI与task-state.json核对；已完成、阻塞、未验证及用户豁免分别保留。旧任务标题中仍出现视频墙/复核等是历史事实，不据此恢复功能。
3. 新增范围先登记需求和任务。整理现行口径引用已有决定，不将文档版本号、编译或镜像构建当作功能/生产验收。
4. 旧文档保留原位并加状态和替代入口；历史验收、失败日志、审计及发布交接不得删除或改写成通过。文档退役不等于数据清理授权。
5. 跨端分工及根目录设计资料的替代关系统一查[工作区文档导航](../../docs/文档导航与资料状态.md)，不新建第三份产品功能清单。

## 2. 当前领域入口

| 主题 | 当前资料 |
|---|---|
| 视频输入、PC按需预览与直播分发退役 | [ADR-003](adr-003-analysis-alerts-only.md)、[视频协议](video-protocol.md)、[退役升级手册](media-retirement-upgrade.md) |
| 账号与项目权限 | [多项目RBAC](multi-project-rbac-contract.md)、[授权内核](project-authorization-kernel.md)、[项目生命周期](project-lifecycle-api.md) |
| 模型与场景 | [项目模型](project-model-assignments.md)、[套件V2](project-scene-suite-v2.md)、[运行许可V2](project-scene-runtime-grants-v2.md) |
| 后台项目业务 | [项目工作台](admin-project-business.md)、[项目场景](admin-project-scenes.md)、[后台发布](admin-frontend-release.md) |
| 知识与建议 | [模拟建议API](ai-alert-advice-api-v1.md)、[移动端服务集成](mobile-alert-advice-service-integration-v1.md) |
| APK发布与恢复 | [升级协议](app-update-v1.md)、[升级服务](app-update-service.md)、[外链核验](app-apk-external.md) |
| Git优先发布 | [工作区统一流程](../../docs/deployment/GIT_FIRST_RELEASE_WORKFLOW.md)，具体版本交接只陈述该次实际结果 |

## 3. 历史与退役资料

| 文档/资料 | 状态与替代关系 |
|---|---|
| [ADR-001](adr-001-output-protocol.md)、[ADR-002](adr-002-production-transport.md) | 历史决策链；旧输出已由ADR-003替代，不据此恢复分发 |
| [transport-comparison](transport-comparison.md) | 历史选型；技术背景可复核使用，所有旧播放选型/契约/验收均非当前依据 |
| [h264-encoder](h264-encoder.md)、[player-compatibility](player-compatibility.md)、[mediamtx-publisher](mediamtx-publisher.md)、[capacity-benchmark](capacity-benchmark.md) | 已退役输出实现/测试历史；旧参数和压测结果不作为现架构验收 |
| [multimodal-verification](multimodal-verification.md)、[project-verification-provider](project-verification-provider.md) | 已退役智能复核设计；保留历史，当前FR-10建议能力不受影响 |
| [admin-frontend-parity](admin-frontend-parity.md) | 历史迁移编号与证据映射；不是当前全量菜单或功能需求；现行范围以FR-07/FR-10/FR-12/FR-13为准 |
| harness/records、harness/acceptance、evidence及版本发布交接 | 指定版本/环境的历史事实；保留原结果与未测项，不自动对新版本生效 |

退役操作手册本身仍是当前辅助资料，例如media-retirement-upgrade.md；不能因文件含MediaMTX等字样就一并退役。领域文档局部过时需加限定或修正该处，不把仍有效的权限、审计、恢复和数据保留门禁取消。
