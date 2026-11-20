# M32-T13 Element Plus 控件全量迁移验收

日期：2026-10-09

## 实施范围

- `admin-web/src/components/ui/` 中的选择/选项、开关、文件选择和进度均由 Element Plus 实现；业务页面继续经由 Ui 适配层使用控件。
- 检查 `admin-web/src` 未发现直接实现原生 `select`、`option`、`input`、`textarea`、`progress`、`button`、`details`、`summary`、`dialog` 或 `table` 的页面模板。
- 使用 Vite `manualChunks` 函数将 Element Plus 拆为独立 JS/CSS chunk，避免业务入口过大。
- 更新 `docs/admin-frontend-ui-library.md`，明确适配层职责、控件范围、主题和迁移边界。

## 验证

- `npm run build`：通过，包含 TypeScript 检查；业务 JS 211.44 kB，Element Plus JS 331.18 kB。
- `npm run build:preview`：通过，包含 TypeScript 检查；业务 JS 211.52 kB，Element Plus JS 331.18 kB。
- `npm run test`：12 个测试文件、64 项通过。
- `PLAYWRIGHT_CHROMIUM_EXECUTABLE="C:\Program Files\Google\Chrome\Application\chrome.exe" npm run test:e2e:production`：43 项通过；包含桌面 1440px 和窄屏 390px 工作流、登录、九菜单、表单和控件交互。
- `python -m unittest discover -s harness/tests -p "test_*.py"`：30 项通过。
- 源码控件审计：业务源码无原生控件实现命中；组件库内部渲染的原生 HTML 属 Element Plus 实现，不属于业务兼容分支。

## 遗留风险

- 无已知功能性遗留。Element Plus Theme Chalk CSS 仍为完整样式包（约 422 kB，gzip 约 60 kB）；后续如按组件裁剪，需重跑全量视觉与菜单回归。
