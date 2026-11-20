# M33-T47 场景保存输入声明不一致修复

- 日期：2026-11-02
- 需求基线：`PRODUCT_REQUIREMENTS.md` FR-07 / FR-13；继续保持项目模型、项目场景、运行选择的职责分离。
- 开发任务：M33-T47；通过 Harness `add`、`show`、`start` 绑定，一次只执行此任务。
- 人工状态：**待人工复测**，不代填人工验收通过。

## 根因

新建场景的 `form.image` / `form.video` 决定场景 `inputTypes`，但添加模型成员直接复制模型的全部 `inputTypes`。例如场景只选图片、模型支持图片和视频时，请求仍提交成员 `['image','video']`，触发服务端 `validate_models` 的 `scene_input_not_supported`。先添加成员再取消一种场景输入也未同步成员。方案输入选项只求成员能力交集，没有同时受场景声明约束。

该业务校验返回 409，已有管理写保护要求关闭弹窗刷新后再操作，所以错误后出现了用户报告的附加提示。本次保留冲突、权限、服务器及未知结果的保护，不通过删校验或自动重试掩盖错误。

## 修复

1. `admin-web/src/features/scenes/ScenesView.vue`：新增成员和同步参数修订时使用场景与模型输入能力的交集；新建草稿修改场景输入时同步成员并保留仍有效的成员选择。交集为空保留空状态，显示中文原因，阻止无效保存；不把空交集回退成全部能力。
2. 成员输入开关仅能选择场景与模型共同支持的类型；方案输入还必须由所选全部成员支持。视频单输入场景的方案草稿默认使用视频。
3. 不静默删除或改写已添加的运行方案。保存前检测成员和方案输入不一致，以中文要求修改或移除失效方案，保留场景草稿并允许直接修正。
4. 编辑元数据时按后端已有继承规则预校验，避免另发不必要的成员写请求；管理成员同样按当前场景声明约束新增成员。服务端成员授权、输入检查、审批、CAS 和运行门禁均未修改。
5. `admin-web/src/features/management/api.ts` 为 `scene_input_not_supported` 增加中文解释；异常服务端冲突仍要求刷新核验，不会自动重放写请求。
6. 使用 frontend-design 技能核对现有表单交互与反馈，沿用现有 UI 组件和视觉规范，仅增加相关帮助与错误提示。

## 测试与证据

- 修复前新增回归：`npm run test -- tests/scenes.test.ts`，7 项失败、原有 13 项通过，复现未限制成员/方案输入及无交集仍发请求。日志：`evidence/M33/M33-T47-before-tests.log`。
- 修复后管理端全量单测：`npm run test --`，25 个文件、176 项通过（包括场景 23 项及中文错误/刷新保护用例）。日志：`evidence/M33/M33-T47-admin-tests.log`。
- 类型检查与生产构建：`npm run build`，vue-tsc 与 Vite production 均通过，正式资源输出到 `admin-web/dist/`。日志：`evidence/M33/M33-T47-admin-build.log`。
- 后端专项：`.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_project_scene*.py'`，75 项中 70 通过、5 跳过、0 失败。覆盖 PC/移动端的图片/视频单输入成员创建；越界请求维持 409 且不落半成品，然后同 ID 合法请求返回 201。原有权限、项目隔离、快照、安装、修订、SQLite 持久化和迁移等相关用例通过。日志：`evidence/M33/M33-T47-backend-scenes.log`。
- 浏览器首轮因本机缺少 Playwright 默认 Chromium 可执行文件而未运行成功，保留日志 `evidence/M33/M33-T47-browser.log` 和两份 `M33-T47-browser-missing-chromium-*.zip`；没有把环境失败记作产品通过。
- 随后通过项目已有 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 配置指定本机 Chrome，执行 `npm run test:e2e:production -- tests-e2e/scene-inputs.spec.ts --workers=1`，2 项通过（25.6 秒）。使用生产构建、隔离临时目录/内存仓储、真实认证和未修改的业务路由；1440 / 390px 各覆盖图片/视频、先修改输入/先添加成员 4 种组合，共 8 次保存均明确返回 201。读取服务端详情核对 scene/member/default plan 输入一致，revision=1、approved=false，保存前后项目模型分配一致。日志：`evidence/M33/M33-T47-browser-chrome.log`；截图：`evidence/M33/M33-T47-create-*.png`。已检查窄屏截图，成员输入开关与禁用状态正确，无横向溢出。
- Harness 单测：34 项通过，日志 `evidence/M33/M33-T47-harness-tests.log`；范围化 `git diff --check` 通过。

## 范围与限制

- 本次只修后台场景表单，不修改 Android、服务端输入授权规则或数据库结构。不操作 Default Project、现有运行数据库或部署容器。
- 未启用隔离 PostgreSQL，5 项 PostgreSQL 用例明确跳过；不能用 SQLite/内存结果宣称 PG 集成已复测。前端单测仍有既有代理测试 `socket hang up` 输出，退出码为 0，全部 176 项通过。
- 真实账号、用户当前项目及完整运行/模型推理链路尚待人工复测；本次不证明模型精度。
- 未提交或推送 Git，未代填人工通过。M33 其他未完成任务及既有改动保持原样。

## 人工复测步骤

1. 关闭旧弹窗，刷新加载本次前端资源；如果浏览器缓存旧资源，使用强制刷新。此步骤用于获取修复后的代码，不代表刷新本身解决旧代码缺陷。
2. 在测试项目中新建场景，只勾选图片并添加支持图片/视频的已分配模型，成员应只勾选图片，视频开关不可选；点击保存应成功。
3. 同样验证只勾选视频；再分别验证先添加模型、再关闭图片或视频的顺序。
4. 场景与模型没有共同输入时，应看到中文提示并保留草稿，不发送无效保存；调整场景输入或更换模型后可继续保存。
5. 若已有运行方案因输入变更失效，应明确提示编辑或移除该方案；保存后场景仍待批准，项目模型清单不变，不自动开始运行。
