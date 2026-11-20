# M32-T12 Element Plus 控件与主题适配层证据

日期：2026-10-09  
任务：M32-T12 统一管理后台 Element Plus 控件与主题适配层

## 结果

- 精确锁定 Element Plus `2.14.7`（MIT），保留 Vue 3、TypeScript、Vite 和 Lucide 技术栈。
- `admin-web/src/components/ui/` 成为唯一 UI 库适配边界；业务 feature、layout、store 和 API 代码没有直接导入 Element Plus。
- 九个菜单、登录页和模型子工作区的普通按钮、文本/数字/文本域、开关、选择、弹窗及表格已迁移到公共组件。
- 新增 `UiTag` 并用于模型状态、场景和用途；告警严重度、处置状态等领域标签保留其业务色阶。
- 保留绿色工业运维主题、Lucide 图标、API Client、原始文件上传、进度/取消、MJPEG、WebSocket 和业务错误语义。

## 兼容边界

- `UiSelect` 使用原生 select 加 Element Plus 主题外壳，保留原生键盘和 option 行为，并兼容 `v-model`、受控 `:value` 和既有浏览器测试。
- 文件输入保留原生能力，由 `UiInput` 统一外观和清空接口；传输仍由 `ApiClient.uploadWithProgress` 管理。
- 开关由原生可操作语义输入驱动，并以 `ElSwitch` 呈现视觉状态，确保 label、键盘和自动化操作一致。
- `UiConfirmDialog` 基于 `ElDialog`，将对话框容器设置为具名 `alertdialog`，保留取消聚焦、Esc、busy 门禁与焦点恢复。
- 通知队列和 loading/empty/error 由 `UiNoticeStack`、`UiStatePanel` 统一；不会用组件库反馈替代真实服务端结果。

完整约定见 `docs/admin-frontend-ui-library.md`。

## 构建优化

Element Plus 控件采用显式导入，不使用 `app.use(ElementPlus)` 全量注册。正式 JS 从全量注册时约 1,190.5 KB（gzip 381.6 KB）降至约 380.4 KB（gzip 128.8 KB），构建不再产生大于 500 KB 的 chunk 警告。

为降低首次统一控件的样式遗漏风险，本轮仍加载完整 Theme Chalk CSS：约 423.8 KB（gzip 59.8 KB）。逐组件 CSS 可作为后续独立优化，必须复跑九菜单和视觉验收。

## 验证

- `npm run typecheck`：通过。
- `npm run test`：12 个文件、63 项通过。
- `npm run build`：通过；正式 base `/admin/`。
- `npm run build:preview`：通过；预览 base `/admin-next/`。
- `npm run test:e2e:production`：43 项通过，覆盖九菜单、管理员/操作员/匿名权限、桌面、390px、告警处置、视频流、模型、上传、规则与复核。
- `git diff --check -- admin-web docs/admin-frontend-ui-library.md`：通过。
- 视觉抽查：`M32-T07-models-desktop.png`、`M32-T10-models-390.png`、`M32-T05-alerts-desktop.png` 无控件重叠、文字截断或页面横向溢出。

## 未覆盖边界

- 未构建 Docker 镜像，未执行生产环境部署或真实浏览器矩阵；生产容器仍由现有 Docker 多阶段构建流程负责前端打包。
- 本任务不增加规则编排、多模型并行识别或跨模型融合能力，也不改变后端 API 契约。
- npm 输出存在本机旧配置项 `home`、`sass_binary_site` 的弃用提示，不影响类型检查、构建或测试。
