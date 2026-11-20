# M33-T53 识别场景列表紧凑化与按需详情

## 结果

- 将项目空间“识别场景”大卡片改为紧凑表格，每行显示名称/ID与修订、状态、输入能力、模型数、方案数及固定可达的“查看详情”。
- 成员、运行方案、获准参数及执行边界按需在详情弹窗查看；编辑、成员管理、启停、审批、重新批准参数及软删除入口保留。软删除继续先预览影响并明确勾选。
- 详情从当前列表数据按 sceneId 派生，不保留上次打开的陈旧对象；无权限用户可查看已获授权场景详情，但不会看到写入操作。
- 长名称在表格单行省略、通过原生 title 可读，详情内换行完整显示。桌面表格行高约58px；窄屏内部滚动且详情列固定，不造成页面横向溢出。
- 更新了界面说明、UI 表格适配器的可选宽度/固定列能力，以及单元和隔离浏览器回归。

## 验证

- `npm run test`：25个测试文件，183项通过。
- `npm run build`：类型检查、production Vite 构建通过。
- production Playwright：4项通过，包含1366×768与390×768列表/详情、键盘打开与Escape、长名称、无页面横向溢出、原场景创建/审批/参数编辑/角色可见性流程。项目输入能力回归同次执行通过2项。
- 桌面1366×768：完整可见6行，实测行高58.28px；390×768完整可见5行。
- Harness：34项通过，`validate` 与 `render` 通过。
- 浏览器回归使用 `tests/admin_frontend_server.py` 的隔离临时模型目录及测试账号；布局密度用路由mock的20条合成只读场景，不写入业务API或 Default Project。

## 证据文件

- `admin-web/tests-e2e/scene-list.spec.ts`
- `admin-web/tests-e2e/scenes.spec.ts`
- `admin-web/tests-e2e/scene-inputs.spec.ts`
- `evidence/M33/M33-T53-browser.log`
- `evidence/M33/M33-T53-build.log`
- `evidence/M33/M33-T53-all-unit-tests.log`
- `evidence/M33/M33-T53-harness-tests.log`
- `evidence/M33/M33-T53/list-1366.png`
- `evidence/M33/M33-T53/list-390.png`
- `evidence/M33/M33-T53/long-name-390.png`
- 桌面与窄屏详情、编辑截图见本目录 `details-*`、`edited-*`。

## 遗留与状态

- 人工验收：**待人工复测**，未代填人工验收通过。
- 未更改业务项目/模型/场景数据，未部署或重启业务服务，未提交或推送 Git。
- 浏览器使用本机已安装 Chrome；不代表其他浏览器或真实业务数据人工验收。
