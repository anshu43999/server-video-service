# M33-T16 管理后台多角色端到端与视觉验收

日期：2026-10-13。工程：`E:/aiyolo/server-video-service`。本任务只验证管理后台和隔离浏览器服务；未把本机浏览器测试当作 M33-T17 部署演练或 M33-T18 Android/现场媒体验收。

## 角色流程覆盖

- 平台管理员：创建账号和项目、指定初始负责人、编辑项目、停用/恢复/归档项目、进入项目成员和审计页面；全平台账号、项目和平台审计入口只在平台角色显示。
- 项目负责人：登录后只进入所属项目，维护普通成员、流、规则、复核/推送配置和项目模型分配；负责人移交后立即清空旧项目数据并重新验证，不能继续写入。
- 项目用户：只能读取获准项目数据、使用项目流/模型并处置告警；维护按钮、模型分配、规则编辑、推送/复核写入口及平台资产入口均隐藏，直接 HTTP 写请求仍返回 403。
- 数据与权限变更：跨项目同 ID 资源不可见；成员移除、账号会话失效、项目停用/归档和恢复均有即时清理或只读语义；最后负责人保护、并发修订和失败恢复均已覆盖。

## 浏览器验收

运行环境：Playwright production 配置、本机 Chrome `C:/Program Files/Google/Chrome/Application/chrome.exe`、本地隔离 FastAPI 服务 `127.0.0.1:4174`。服务使用内存数据库、临时模型目录和合成测试资产，不连接在线业务数据库或 MinIO。

| 验证 | 结果 |
| --- | --- |
| `npm run typecheck` | 通过 |
| `npm run test` | 15 个文件、91 项通过 |
| `npm run build` | vue-tsc 与 production Vite 构建通过 |
| 项目上下文专项：`npm run test:e2e:production -- projects.spec.ts` | 13/13 通过 |
| 管理/业务/切换专项：`... projects.spec.ts management.spec.ts project-business.spec.ts cutover.spec.ts --workers=2` | 26/26 通过 |
| 正式浏览器全量：`npm run test:e2e:production -- --workers=4` | 68/68 通过 |
| 后端双项目矩阵（隔离数据库/MinIO 环境） | 7/7 通过 |

全量浏览器覆盖了项目创建、账号创建、成员分配、负责人移交、项目切换、流和规则维护、模型分配、项目用户只读与告警处置、成员移除、项目停用/归档/恢复、刷新、深链、双标签、390px 窄屏、加载失败、会话过期和权限变更。追加的项目上下文回归验证项目目录失败时清除旧数据、重试恢复；会话过期时清除项目数据并返回登录页。

## 视觉证据

真实隔离服务截图：

- `evidence/M33/M33-T16-platform-1440.png`、`M33-T16-platform-390.png`
- `evidence/M33/M33-T16-owner-1440.png`、`M33-T16-owner-390.png`
- `evidence/M33/M33-T16-user-1440.png`、`M33-T16-user-390.png`
- `evidence/M33/M33-T16-project-directory-failure-production.png`
- `evidence/M33/M33-T16-session-expired-production.png`

截图核对了平台/项目上下文持续显示、角色标签、负责人维护入口、用户只读与告警处置入口、加载失败和登录失效状态；1440px 与 390px 均通过无横向溢出断言。

## 修改范围与遗留边界

本次新增管理后台项目上下文加载失败/会话失效 E2E 回归，补充 T16 专属平台、负责人、用户和错误状态截图，并为既有九菜单刷新流程提高合理超时。未提交或推送 Git，未修改 Android 工程。

M33-T17 仍需真实部署升级、备份恢复、密钥轮换和回滚演练；M33-T18 仍需真实服务端、PostgreSQL、管理后台和 Android 联合验收，包括已建立 WebRTC 连接撤权行为。上述现场范围不由本机浏览器测试替代。
