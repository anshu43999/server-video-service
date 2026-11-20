# M32-T04 路由、应用外壳与通用组件验收证据

验收日期：2026-10-09

## 实现边界

- 新版后台建立 `overview`、`dashboard`、`streams`、`alerts`、`push`、`rules`、`models`、`diagnostics`、`verification` 九个菜单路由。
- 路由定义同时提供菜单名称、页头、面包屑、图标、允许角色和后续迁移任务，导航不维护第二份权限清单。
- 新版管理外壳仅允许 `admin`；`operator` 仍进入既有权限说明页。
- T05-T09 尚未迁移的页面只显示迁移边界及旧版入口，不请求业务接口、不显示 Mock 数据、不提供伪操作。
- `/engineering` 保留兼容跳转到 `/overview`，未知深链进入明确的不可用页面。

## 公共基础层

| 能力 | 文件 | 验收点 |
|---|---|---|
| 路由与权限元数据 | `admin-web/src/app/router.ts` | 九路由、admin 可见性、深链解析、兼容跳转 |
| 响应式应用外壳 | `admin-web/src/layouts/AdminLayout.vue` | 侧栏、移动抽屉、页头、面包屑、账号与退出、旧版入口 |
| 迁移占位页 | `admin-web/src/features/migration/MigrationPage.vue` | 真实边界、后续任务编号、无伪数据与伪操作 |
| 设计令牌 | `admin-web/src/styles/tokens.css` | 颜色、排版、间距、圆角、状态与外壳尺寸 |
| 通用状态 | `UiStatePanel.vue` | 加载、空数据、错误及重试 |
| 确认对话框 | `UiConfirmDialog.vue` | 初始焦点、焦点圈定、Escape、取消不确认、焦点归还 |
| 通知 | `UiNoticeStack.vue` | info/success/error 与可访问关闭按钮 |
| 表格 | `UiDataTable.vue` | caption、空行、水平可滚动数据区 |
| 筛选与表单 | `UiFilterBar.vue`、`UiFormField.vue` | 语义化 search form、查询/重置、提示与错误关联 |

## 自动化结果

- `npm run test`：7 个测试文件、29 项测试全部通过。
- `npm run test:e2e`：2 项 Chromium 验收全部通过。
  - 桌面：九项导航、规则页深链、刷新保持、无横向溢出、控制台错误为 0。
  - 390x844：抽屉完整可见、首项获焦、Escape 关闭并归还焦点、路由切换、`scrollX=0`、控制台错误为 0。
- `npm run build`：正式 `/admin/` 构建通过。
- `npm run build:preview`：预览 `/admin-next/` 构建通过。
- `.venv\\Scripts\\python.exe -m unittest discover -s tests -p "test_admin_frontend_hosting.py" -v`：7/7 通过。
- Playwright 使用请求拦截提供临时 UI 验收身份，只响应 `auth/status` 和 `auth/me`；未创建后端账号，未写入或使用真实凭据。

## 视觉证据

- `evidence/M32/M32-T04-desktop-shell.png`
- `evidence/M32/M32-T04-mobile-navigation.png`

## 遗留边界

- 告警与复核业务迁移：M32-T05。
- 视频流业务迁移：M32-T06。
- 模型资产业务迁移：M32-T07。
- 规则、推送、复核配置和诊断业务迁移：M32-T08。
- 总览与数据看板业务迁移：M32-T09。
- 默认入口切换、遗留清理和完整真实环境验收：M32-T10。
