---
major_task_id: M36
result: passed
owner: codex
accepted_at: 2026-10-21T21:21:57+08:00
---

# M36 模型端能力与项目场景配置第一阶段测试验收报告

## 2026-11-18 M36-T53 编辑场景直接回填与一次保存

- L2，Windows 工作树 `4e9faf4` 上含未提交修改；仅管理台编辑场景及回归用例，未改服务接口、业务数据库或 App。
- 单方案直接展示已保存字段；多方案按名称、成员和执行方式展示，可切换编辑；显式新增，统一保存。取消和仅查看不写入，校验错误展开对应方案。
- 在 `admin-web` 运行 `npm run test -- tests/scenes.test.ts`：52/52，通过，含单方案异步、相机参数回填、取消后重开、无修改及错误时零写入、有效修改一次 PATCH。`npm run build` 和 `npm run build:preview` 均通过（含类型检查）。
- 隔离内存服务及系统 Chrome：`npm run test:e2e:production -- scenes.spec.ts --workers=1 --timeout=60000`，1440/390px 共 2/2 通过（39.2 秒）。验证查看已批准场景、多方案来回切换、保留改名、一次保存后修订从 2 变 3 并回到待批准。测试结束服务报告一次 Windows 连接重置，未影响断言或退出状态。未连接实际项目库、未部署、未做真实业务账号验收。

## 2026-11-18 M36-T52 创建场景内联方案、一次保存

- L2；Windows 本地、Chrome 157.0.8103.52，基于 `4e9faf4` 工作树（含未提交和未跟踪改动）。本轮仅管理台创建流程与回归测试。未更改后端、业务数据、数据库结构或 App，未发布。
- 单/双模型自动方案直接显示实际字段，仅展开不会转成自定义。可以修改或明确新增另一份方案；收起保留编辑，点击保存场景一次提交；无效方案提示序号与原因。已有场景仍使用原编辑流程。
- `admin-web`：`npm run test -- --run tests/scenes.test.ts`，51/51；`npm run build`、`npm run build:preview` 均通过（含类型检查）。
- `npm run test:e2e:production -- scene-create-simple.spec.ts scenes.spec.ts --workers=1 --timeout=60000`，最终 6/6。隔离内存后端，`DATABASE_URL` 指向不可达测试地址，使用已安装 Chrome。1440/768/390/320px 各验证默认方案名称与编号、两个已选成员、改名再折叠后提交；各写入一次，取消零写入、无页面异常。1440/390px 还走通手动新增两个方案、实际创建 API、审批、只读查看平台参数和已有场景编辑。
- 首轮浏览器测试失败：测试查找 checkbox，而实际为 switch；多方案用例直接点击隐藏的组合框输入超时。修正定位后 5/6，一例在取消流程重新选择第二项时与下拉框关闭过渡竞争；等待列表收起后串行复测 6/6。最终夹具输出一次连接被关闭的 Windows 网络日志，不影响断言或退出状态。
- 未验证线上部署与实际业务账号；此次不涉及手机推理或正式签名包。无生产操作。

## 2026-11-18 M36-T50 新建多模型场景默认联合使用

### 范围、实现与环境

- 验证级别：L2，管理前端创建默认值与交互修复。本节为本任务唯一最终测试报告，复测及失败事实一并保留；文首历史验收状态不代替本轮实际测试。
- 新建场景仅选一个模型时仍生成一个single方案；选多个模型时生成一个覆盖全部成员的联合方案，默认sync，可在基础表单直接改为async。未自定义时，新增、移除及重排成员会更新该方案，memberIds完整保留且顺序与场景成员一致；不再默认拆成多个独立single方案。
- 联合运行能力沿用已有双移动端视频边界：超过两个成员、PC/跨端、含图片用途或缺少共同视频能力时，默认创建明确展示限制，禁用保存且在提交处理函数再次阻止写入。两个移动端模型均支持视频时提供“仅使用视频巡检”，仅用户点击才调整用途，不静默丢弃成员或图片输入。
- 基础摘要展示同步/异步区别，沿用原依次推理语义和默认相机策略frameInterval=5。创建仍不批准或启动巡检；在线预检、运行授权、设备预算和客户端能力门禁不变。已有场景及显式自定义的方案不自动重写，自定义后新增成员会提示用户检查方案覆盖。
- 产品修改仅涉及`admin-web/src/features/scenes/automaticPlans.ts`、`ScenesView.vue`、`scenes.css`和场景文档，配套增加/更新定向测试与场景浏览器配置。遵循frontend-design技能，沿用既有绿色后台样式、字体和弹窗结构，仅调整本次摘要、选择框与提示正常流布局。未修改服务端业务实现、数据库结构或Android代码。
- 代码基线：HEAD `4e9faf48dbd4800f7af7d09599337ec2d872840d`，含大量既有及本轮未提交/未跟踪改动；验证针对工作树，非干净提交发布认证。本轮未commit/push、迁移业务库、重启后端、部署或打包App。执行前已通过服务端Harness validate/status/next，新增并show/start M36-T50；未进入mobile-app。
- 环境：2026-11-18 Asia/Shanghai，Windows/PowerShell，Node v24.19.0，npm 11.17.0，Chrome 157.0.8103.52（`C:\Program Files\Google\Chrome\Application\chrome.exe`）。浏览器由独立`127.0.0.1:5188/admin/`提供本地production构建，全部业务HTTP与WebSocket经隔离夹具处理，不连接业务后端或数据库。

### 实际命令、结果与指标

以下前端命令均在`E:\aiyolo\server-video-service\admin-web`执行。

1. `npm run test -- tests/scene-automatic-plans.test.ts tests/scenes.test.ts tests/scene-runtime-capabilities.test.ts --maxWorkers=2`：最终3文件91/91通过，无跳过，25.84秒。此前两轮同范围89/89通过，后补充两个组件回归用例。
   - 覆盖空集合、单模型图片/视频、sync/async完整成员及顺序、默认相机策略、添加/移除/重排、无输入/成员缺少共同视频、图片/PC/跨端/三个模型组合的明确阻止。
   - 组件验证含图片时直接触发表单也无API写入；显式切视频后两种mode均只生成一个plan，memberIds与实际models完全一致，成员顺序及刷新后mode保持，不传approved或历史参数快照。
   - 新增第三个成员会重新阻止，移除后恢复；重新勾选图片再次阻止，取消图片后仍保持用户选择的async。自定义后新增第三个成员保持原自定义方案；打开已有双single场景并原样保存，不改计划、不调用成员/方案/metadata写入、不改变源对象。
2. `npm run build`、`npm run build:preview`：最终均通过vue-tsc与Vite，均3646模块，Vite 620ms/631ms，本地`dist`与`dist-preview`已更新。
3. `node node_modules/typescript/bin/tsc --noEmit --skipLibCheck --strict --target ES2022 --module ESNext --moduleResolution Bundler --lib ES2022,DOM,DOM.Iterable --types node,vite/client playwright.scene-create.config.ts tests-e2e/scene-create-simple.spec.ts tests-e2e/scene-parameter-layout.spec.ts`：通过。
4. 设置`PLAYWRIGHT_CHROMIUM_EXECUTABLE=C:\Program Files\Google\Chrome\Application\chrome.exe`，执行`npm run test:e2e -- --config playwright.scene-create.config.ts --max-failures=1`：最终8/8通过，27.5秒；此前8/8通过，18.6秒，后补充新摘要截图、提示与按钮几何断言和取消流程再完整复测。
   - 四种视口1440/768/390/320×960，各选择两个不同移动端模型helmet/phone，确认默认联合、含图片时不能保存；主动点击仅视频，1440/390保持sync，768/320选择async，刷新保留草稿、自动ID及全部成员；键盘展开高级设置，只有一个覆盖两个模型的方案，改名称后收起仍保留，键盘确认后仅一次夹具POST。
   - 四次创建载荷均为video、一个联合plan、两个完整成员，plan.memberIds与models.memberId逐项一致，cameraPolicy.frameInterval=5，无approved字段。重新打开创建，选同样两个模型后取消，额外业务写入0；各例页面JS异常0。
   - 四宽度新联合警告文字与按钮垂直间距均10px，警告、弹窗与页面无横向溢出。人工回看最终1440警告、320警告及320异步就绪摘要截图，模式说明自然换行、提示边界完整、按钮与文字分离；截图仅作当轮临时诊断。
   - 原参数提示布局回归四例全部通过：初始/长名称状态的提示至刷新操作区间距均12px，桌面操作文案至按钮间距20px，390/320纵排间距12px，均无横向溢出。每例三次模型读取、业务写入0；不把此夹具验证视为真实参数发布联调。
5. 定向`git diff --check`通过。npm配置、NO_COLOR与Git换行符提示未阻断验证。本轮无后端或Android产品改动，未执行后端全量/数据库集成、Android JVM/Lint/Release或Harness单元测试。

### 失败与修正事实

- 首轮89项测试通过后，生产构建的vue-tsc失败：新测试工厂缺少`SceneMember`必需字段`parameterRevision`。补全测试夹具为r1，去除自动方案函数中不必要的类型断言，后续89/89及build通过。随后补充原场景保留和组合重新校验两例，最终91/91及两种构建均通过；未放宽产品类型契约或测试断言。
- 本轮两个浏览器批次均8/8通过，无失败或跳过；最终批次增加视觉/取消验证，未通过删除测试减少范围。

### 边界与留存

- 这是新建默认方案修复，已有多single场景未自动迁移。如需让已有场景共同识别，仍需用户显式编辑联合方案、核对输入/成员并重新批准；自定义方案由用户维护。当前联合仍仅支持两个移动端视频模型，多模型图片、PC/跨端及超过两个模型的运行未开放；本次不增加App多线程。
- 本机前端两种构建已生成，使用该构建的管理页面刷新后可见；本次不需要数据库迁移或后端代码重启。远端须按Git优先流程发布前端才能生效。未验证真实账号/业务后端创建联调、Android真机推理、Docker/K8s发布、其他浏览器或任意缩放；旧App不因后台默认改变而取得联合运行能力。既有M36-T48哈希断言问题仍不在本任务范围。
- 本次临时诊断仅归属`.tmp/m36-t50-scene-joint-default`，最终16张PNG和1份Playwright状态JSON。报告已写入并回读，确认测试/5188预览进程停止、核对绝对路径/父目录/后代无链接及精确清单后，已依留存规则精确删除17项并确认目录不存在。临时截图不可恢复，结论与指标保留本节；未清理源码、业务数据、模型、密钥、安装包、构建或其他历史证据。

## 2026-11-18 M36-T49 压缩平台模型目录卡片

### 范围、实现与环境

- 验证级别：L2，管理前端局部布局与交互。本节为本任务唯一最终测试报告，历史章节及既有失败结论保留。
- 模型目录移除重复的独立文件状态块，PC/移动端文件与参数状态集中在“项目添加条件”中。逐端状态与参数入口横向组合；尚未发布、状态未知、文件不可用和有新草稿时保留原因说明，已满足条件时省略重复的成功说明。
- 名称、版本、发布状态、场景、目标端、逐端添加条件及常用操作默认可见。完整模型ID、全部类别、移动签名、PC运行验证及设为新流默认收进原生可键盘操作的“技术信息”展开区；类别总数始终可见。默认收起，以原生文档流展开，不截断完整类别或限制展开高度。
- 刷新目录并入页签栏，收紧本页筛选区与卡片间距，沿用原绿色主题与字体，目录标题16→15px、逐端辅助字段保持11px、按钮统一32px。发布/校验/卸载处理函数保持不变。新增样式使用目录专有类，未全局调整项目模型卡片、共享UI、其他页面布局、业务接口、数据库或App。
- 代码基线：HEAD `4e9faf48dbd4800f7af7d09599337ec2d872840d`，工作树存在大量既有未提交/未跟踪改动，本次仅增量修改；没有提交、推送、重启后端或部署。执行前已通过服务端Harness validate/status/next，新增并show/start M36-T49；没有进入mobile-app。
- 环境：2026-11-18 Asia/Shanghai，Windows/PowerShell，Node v24.19.0，npm 11.17.0；Chrome使用 `C:\Program Files\Google\Chrome\Application\chrome.exe`。使用frontend-design技能检查层级、密度和截图，遵循现有后台视觉而未重设计。

### 实际命令与结果

以下前端命令在 `E:\aiyolo\server-video-service\admin-web` 执行。

1. `npm run test -- tests/catalog-readiness.test.ts tests/models.test.ts tests/catalog-changes.test.ts tests/category-parameters.test.ts --maxWorkers=2`：最终4文件32/32通过，无跳过，89.79秒；此前相同范围32/32通过。覆盖逐端发布与r0/新草稿/未知状态/文件门禁、精确版本与参数端入口、关闭档案刷新，以及原模型接口与分类参数逻辑。
2. `npm run build`、`npm run build:preview`：最终均通过vue-tsc及Vite，均3645模块；最终production Vite 17.71秒、preview 1.04秒。本机 `dist` 和 `dist-preview` 已更新，不是Git可追溯镜像发布。
3. `node node_modules/typescript/bin/tsc --noEmit --skipLibCheck --strict --target ES2022 --module ESNext --moduleResolution Bundler --lib ES2022,DOM,DOM.Iterable --types node,vite/client playwright.catalog-readiness.config.ts tests-e2e/catalog-readiness.spec.ts`：最终通过。
4. 设置 `PLAYWRIGHT_CHROMIUM_EXECUTABLE=C:\Program Files\Google\Chrome\Application\chrome.exe`，执行 `npm run test:e2e -- --config playwright.catalog-readiness.config.ts --max-failures=1`：最后一轮11/11通过，41.4秒。上轮11/11通过后，人工截图发现筛选栏“场景”被挤成两行，定点修正标签/选择框宽度后再次完整复测通过，未降低首屏断言。
   - 生产构建由独立 `127.0.0.1:5194/admin/` 提供；所有业务HTTP/WebSocket均被隔离夹具拦截，不连接真实业务后端或数据库。参数流程写入仅更新内存；5个整卡布局用例业务写入0、页面JS错误0、意外业务请求0。
   - 原6例：1440/390/320宽度×server/android参数入口，验证未发布→正确模型版本和端的参数档案→保存草稿→取消发布无额外写入→确认发布→关闭后刷新为已发布。每例2次预期夹具PUT/POST，另一端保持未发布；12组发布前后状态均无横向溢出、提示/按钮重叠，桌面按钮与主信息间距12px。
   - 新5例：1440×900、1366×768、1280×720、390×844、320×740，两个不同模型，第二个为较长中文名称，各80个类别。验证初始收起技术信息、默认常用按钮可见、展开后完整ID及第80个类别可见、PC运行验证入口可见及设为默认按钮启用、收起、打开并取消按端发布、读取版本详情、打开卸载影响并取消；卸载确认在未勾选前仍禁用，业务写入0。
   - 三种桌面视口，两张卡片同排，顶部y=321.97px，底部分别y=714.73/691.14px，高度分别392.77/369.17px；初始无滚动即完整可见，1280×720同样满足。窄屏按单列自然流动，320px最长卡片541.95px，不承诺窄屏同时显示两个完整模型。展开技术信息会增加高度，80类别不再占用默认卡片高度。
   - 人工回看最终1366px和320px整页截图，确认标题/版本、状态分隔线、原因、技术信息摘要、按钮换行及“场景”横排清楚，无遮盖；截图为当轮临时诊断，不作为永久附件。
5. 定向 `git diff --check`：通过；npm本机配置、NO_COLOR及Git换行符提示未阻断验证。仅改产品前端和测试，未执行后端全量测试、Android JVM/Lint/Release或Harness单元测试。

### 失败与修正事实

- 第一轮浏览器：7通过、1失败、3未执行；1366×768下卡片底部y=845.92px，超过视口。原因是原独立刷新行、页签和筛选留白仍将卡片顶部推至437.16px。合并刷新/页签并收紧本页工具区后重测。
- 第二轮浏览器：8通过、1失败、2未执行；1366×768已通过，1280×720底部y=733.11px仍超出。进一步将卡片gap调整为8px、逐端边界上下间距6px，保留字号与按钮高度，后续11/11通过。两次失败均保留本节，未绕过或放宽首屏几何条件。

### 边界与留存

- 此次为前端展示调整，本机使用新构建后刷新管理页面即可；不增加数据库迁移，不改变模型可用性，也不替用户发布参数或卸载模型。前次T47新增API仍需后端运行相应代码，不能用本轮UI测试声称已修复/验证真实接口状态。
- 未验证真实账号/业务服务联调、服务器/Docker/K8s发布、其他浏览器、任意缩放比例/超长名称组合或Android真机。此前M36-T48跟踪的既有项目目录哈希断言问题仍未在本任务修复。
- 临时材料仅归属 `.tmp/m36-t49-compact-catalog`；报告已写入回读，确认测试/5194预览进程停止、绝对路径及父路径/后代均无链接，核对清单后已精确删除本轮17个PNG和1个Playwright JSON并确认目录不存在。临时图片不可恢复，失败事实与最终指标保留本节；未清理其他历史材料、源码、业务数据、模型、密钥或发布构建。

## 2026-11-18 M36-T47 模型目录说明项目添加缺失条件

### 范围、实现与环境

- 验证级别：L2，平台模型目录局部交互及只读 API 摘要。本节为本任务唯一最终测试报告；文首历史 passed 不代表本轮所有扩展回归通过。
- 平台“模型资产 → 模型目录”增加每个精确版本、各支持端的“项目添加条件”，分列模型文件与运行参数状态。顶部发布标签明确为“模型文件已发布”；文件就绪不再暗示参数已发布。文件发布确认及成功提示也说明还需发布对应端参数。
- 未发布显示“待发布参数”，明确说明为什么项目添加候选看不到，并提供“去发布服务端参数 / Android 参数”按钮，打开原参数档案的精确模型版本和对应端。关闭档案后重新读取目录；原刷新目录入口仍可使用。仅打开档案不会保存或发布。
- 正确区分 r0 发布版、有未发布新草稿、文件未就绪/未发布、版本撤回及参数状态未知。已有发布版加新草稿仍显示“项目可添加”，说明项目使用发布版。状态读取失败不显示成“尚未发布”。
- 平台目录增加 `parameterPublication` 摘要；不返回完整参数或审计，不加入项目目录，不改变授权、模型分配、发布或新运行门禁。数据库沿用既有参数存储，首次沿用已有 legacy 导入约定，之后每批摘要两次查询，避免浏览器对每个模型逐端请求。无数据库结构变更。
- 使用 frontend-design 技能保持既有绿色配色、字体和卡片结构，仅增加状态信息层级、分隔线及正常文档流中的提示/按钮。320px 下两列参数信息转为纵排。
- 代码基线：服务端 HEAD `4e9faf48dbd4800f7af7d09599337ec2d872840d`，含大量既有和本轮未提交/未跟踪改动；本轮仅按请求增量修改，未提交、推送或部署。
- 环境：Windows/PowerShell，Python 3.13.15，Node v24.19.0，npm 11.17.0，Chrome 157.0.8103.52，2026-11-18 Asia/Shanghai。仅服务端/管理前端目录，不读取或改动 Android 工程，不启动 App Harness。

### 实际命令与结果

命令除注明外在 `E:\aiyolo\server-video-service` 执行；前端命令在其 `admin-web/` 执行。

1. `python harness/harness.py validate`、`status`、`next`，以及 `add/show/start M36-T47`：通过，编辑前已绑定本任务。
2. `$env:DATABASE_URL=''; .\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_platform_model_parameter*.py' -v`：发现34项，23通过、11项 PostgreSQL 测试跳过，退出0，21.900秒。覆盖精确版本/目标端、未发布/发布r0/新草稿/再发布、无效发布状态、读取故障脱敏、项目可用候选变化、项目隔离及已有平台运行快照规则。内存/临时SQLite数据，明确覆盖 DATABASE_URL，不使用业务库；批量测试31个模型身份仅执行2条SQL，项目覆盖不进入摘要。
3. `npm run test -- tests/catalog-readiness.test.ts tests/models.test.ts tests/catalog-changes.test.ts tests/category-parameters.test.ts tests/assignment-targets.test.ts --maxWorkers=2`：5文件54/54通过，71.35秒。末轮补充目录顶部中文发布标签断言后，`npm run test -- tests/catalog-readiness.test.ts --maxWorkers=1`：5/5通过，3.05秒。
4. `npm run build`、`npm run build:preview`：两轮均通过 vue-tsc 与 Vite；末轮均3645模块，Vite耗时631ms/681ms。本地 `dist` / `dist-preview` 已更新，未复制到服务器或镜像。
5. `node node_modules/typescript/bin/tsc --noEmit --skipLibCheck --strict --target ES2022 --module ESNext --moduleResolution Bundler --lib ES2022,DOM,DOM.Iterable --types node,vite/client playwright.catalog-readiness.config.ts tests-e2e/catalog-readiness.spec.ts`：通过。
6. 设置 `$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE='C:\Program Files\Google\Chrome\Application\chrome.exe'` 后，`npm run test:e2e -- --config playwright.catalog-readiness.config.ts --max-failures=1`：修正测试定位后6/6通过，23.7秒；最终补充文件发布文案并缩小截图至新提示区域后复测6/6通过，20.6秒。
   - 独立5194端口提供生产构建，全部业务HTTP及WebSocket由隔离夹具处理，未连接真实业务后端。1440/390/320×960三个宽度，各验证服务端和Android入口，共6例。
   - 各例验证初始两端“待发布参数”→直达正确端档案→修改并保存草稿→取消发布无额外写入→明确发布→关闭档案自动刷新→本端“项目可添加 / 已发布r1”，另一端仍待发布。每例仅两次夹具写入 PUT/POST，均为 `phone / 1.0.0` 和指定端，未发起模型文件发布、分配或其他业务写入。
   - 12组发布前/后页面状态均无页面/提示区域横向溢出；两端提示文本与按钮间距均12px；页面JS错误0、意外业务请求0。人工回看最终1440未发布、320 Android已发布提示截图，文字换行与边框完整，提示、标签和按钮没有重叠。初次整卡截图受原有悬浮页头覆盖顶部，最终截图改为只截本次新增提示区域，未据顶部被裁切的图片宣称整页视觉通过。
7. 定向 `git diff --check`：通过。npm配置、NO_COLOR、Git换行符及Starlette弃用警告未阻断结果。首次后端测试继承本机worker开关出现 `apk_worker_iteration_failed` 日志；后续扩展回归显式关闭 `APP_APK_WORKER_ENABLED` / `APP_UPDATES_ENABLED`，没有把该日志计为业务验收通过。

### 扩展回归失败与对照结论

- 额外设置 `DATABASE_URL=''`、`APP_APK_WORKER_ENABLED=false`、`APP_UPDATES_ENABLED=false`，用 `unittest.defaultTestLoader.loadTestsFromNames(['test_catalog_read_api','test_project_model_inventory'])` 加载并执行，运行39个测试，9跳过，2个测试方法共4个失败断言，退出1，77.833秒；其余28个方法通过。不能声称扩展回归全绿。
- `test_assignment_guard_does_not_hash_or_change_public_display_fields` 期待内部assignment读取不调用catalog.get，实际调用1次；`test_each_list_request_hashes_each_file_once_without_cross_request_reuse` 的三个项目路径子用例，期望2/2/6次hash，实际5/5/9次。当前已有项目参数解析会读取模型，这些失败位于项目读取/原有assignment路径。
- 对照复现：在同一工作树进程内用 `patch.object(main, '_platform_catalog_models', side_effect=lambda: main.model_catalog.list_models())` 绕过本轮新增平台摘要，加载上述两个完整测试方法重跑；仍为同样4项断言失败，4.172秒，退出1。未修改产品文件来做对照，未降低断言凑通过，也未扩展修复原有项目目录的hash行为。
- 兼容性断言已按本次平台API新增字段调整：剔除新增摘要后原模型字段仍完全相同，并验证项目目录无该摘要。原平台每请求6文件hash断言通过；原文件变更、权限撤销、worker有界/取消/超时、跨项目隔离等扩展用例通过。
- 浏览器首轮1失败/5未执行：数值输入实际可访问名称带“减少数值 增加数值”，精确匹配“识别置信度”超时，发生在首次保存前。按实际名称前缀及中文关闭按钮修正测试脚本后通过，产品输入组件未因此修改。

### 边界、上线与留存

- 需要发布本次前后端并重启后端进程，再刷新管理页面，才能取得新增摘要；旧后端缺少字段时前端显示“状态待核实”，不会误报未发布。不需要数据库迁移或构建App；本轮未重启正在运行的服务，未替用户发布phone参数。
- 未验证真实业务账号/服务联调、PostgreSQL独立实例、Docker/K8s生产部署、其他浏览器或Android真机。本次内存/SQLite/API夹具和浏览器验证不替代这些验收。既有两个hash计数测试方法仍失败，已如实保留为风险，未在本任务解决；后续核查已登记M36-T48（pending，未启动），不因T47完成而将这些失败改为通过。
- 本次唯一临时材料归属 `.tmp/m36-t47-catalog-readiness`（最终12张PNG、1份Playwright状态JSON）。报告已写入并回读；核对5194监听0、对应Node测试/预览进程0、绝对路径及父路径/后代无链接、文件清单仅本轮13项后，已精确删除并确认目录不存在。临时截图不可恢复，失败事实、结论和指标保留在本节；未删除源码、业务数据、模型、密钥、安装包、构建产物或其他历史证据。

## 2026-11-17 M36-T46 阻止项目模型重复添加并明确重新启用

### 范围、实现与环境

- L2，管理前端项目模型分配流程修复。按当前项目清单中的精确`modelId + modelVersion + target`识别已有条目，不按显示名称判断。后端原有同键更新/CAS和数据库唯一约束保持不变，不增加迁移或改变接口语义。
- 候选模型和目标端选项显示“已添加”或“已停用，可重新启用”。已有启用条目展示原清单修订、禁止按钮/表单提交及确认处理函数继续写入；保留候选可选，便于切换到尚未分配的另一目标端。已停用条目使用“重新启用项目模型/确认重新启用”，明确复用原条目及其修订，不声称创建新条目。不同模型ID、不同版本、不同目标端仍可独立添加。
- 候选加载/失败、清单加载/失败和需要重新核验时禁止提交；保留权限及冲突禁重试。产品改动仅位于`admin-web/src/features/models/ProjectModelsView.vue`，保留该文件已有未提交改动；沿用frontend-design技能要求的既有绿色视觉及布局，未新增CSS或改动共享组件。
- HEAD `4e9faf48dbd4800f7af7d09599337ec2d872840d`；工作树包含既有及本轮未提交/未跟踪文件，验证针对工作树，不是干净提交的发布认证。Windows/PowerShell，Node v24.19.0，npm 11.17.0，Chrome 157.0.8103.52；2026-11-17 Asia/Shanghai。本轮使用服务端Harness任务M36-T46，已在编辑前启动，未进入Android工程。

### 实际命令、结果与指标

- 在`admin-web/`执行`npm run test -- tests/assignment-targets.test.ts tests/category-parameters.test.ts tests/models.test.ts --maxWorkers=2`：最终3文件44/44通过，3.15秒，无跳过。分配组件22项覆盖PC/移动端已启用精确版本禁提交/直接确认无写入、切换端允许新增且原条目不变、从添加弹窗重新启用原ID/修订且取消无写入、新版本/同名不同ID独立添加、候选加载失败及显式重读、权限、卸载不可用条目和冲突禁重试；其余22项为既有参数及模型回归。
- `npm run build`、`npm run build:preview`均通过vue-tsc和Vite，3641模块，Vite耗时601ms/638ms；本地`dist`及`dist-preview`已更新。未上传、部署或重启服务。
- 最终独立检查通过：`node node_modules/typescript/bin/tsc --noEmit --skipLibCheck --strict --target ES2022 --module ESNext --moduleResolution Bundler --lib ES2022,DOM,DOM.Iterable --types node,vite/client playwright.assignment-duplicates.config.ts tests-e2e/project-model-duplicates.spec.ts`。定向`git diff --check -- src/features/models/ProjectModelsView.vue tests/assignment-targets.test.ts`通过。
- 设置`PLAYWRIGHT_CHROMIUM_EXECUTABLE=C:\Program Files\Google\Chrome\Application\chrome.exe`后执行`npm run test:e2e -- --config playwright.assignment-duplicates.config.ts --max-failures=1`：最终2/2通过，21.4秒。在独立`127.0.0.1:5193/admin/`预览生产构建，业务HTTP及WebSocket经隔离夹具拦截，写入仅更新内存，不连接真实业务后端/数据库。
- 1440×960与390×960各完整操作：已添加版本禁止提交→同版本另一端取消/确认新增→重新打开识别该端已添加→已停用版本取消/确认重新启用→同端新版本新增。每项只有3次预期PUT：`helmet/1.0/mobile/expectedRevision=0`、`helmet/2.0/pc/expectedRevision=8`、`helmet/3.0/pc/expectedRevision=0`。PC 1.0仍为原ID/r3；PC 2.0复用原ID并变为r9、条目数不增；总数2→3→3→4。重复选择和取消确认均无额外写入，非预期写入0，页面JS异常0。
- 两宽度“已添加/重新启用”共4组布局检查：表单、预览和弹窗体无横向溢出，页面无横向溢出，预览至操作区间隔均22px。人工回看1440已添加及390重新启用截图，状态、说明与按钮清楚分离，窄屏预览自然纵排；选择框长标签沿用既有省略显示，完整状态在预览中可见。

### 失败、修正与复测事实

- 首轮组件测试41通过/3失败：将Element Plus传送到浮层的选项文字当作选择框本体文字读取，实际只读到“Select”。改为断言选项组件的解析label；产品逻辑未因此改变。
- 第二轮组件测试43通过/1失败：测试对话框替身没有可检索组件名，读取标题时报空wrapper。为替身声明`UiDialog`名称和title属性后，第三轮44/44通过；以上是测试替身/定位问题，不将失败记录删掉或冒充通过。
- 首次独立TypeScript命令仅含`--types node`，从API类型引入项目类型后缺少Vite的`ImportMeta.env`环境声明，退出1；补全`--types node,vite/client`后通过。生产及预览的vue-tsc本来均通过，无产品类型代码改动。
- 首轮浏览器1失败/1未运行：精确匹配“模型版本”找不到实际可访问名称“模型版本 请选择”，在首次选择前失败。改用带空白边界的标签前缀定位，最终2/2通过，无产品逻辑调整。

### 边界与留存

- 本轮没有后端产品代码/数据库结构变更，不需要数据库迁移或为此重启后端；远程需依Git优先流程发布管理前端后生效。未commit/push、部署或构建APK。
- 未验证真实业务账号/后端集成、并发多用户、Docker/K8s生产部署、其他浏览器或Android真机；后端唯一键/CAS沿用原实现，本轮未重新执行数据库集成测试。隔离浏览器和组件测试不替代上述验证，也不代表整个M36最终验收。
- npm配置/NO_COLOR和Git换行符提示未阻断验证。本节为本轮唯一最终测试报告；写入并回读后，确认5193监听0、对应Node测试/预览进程0，核对`.tmp/m36-t46-assignment-duplicates`的绝对路径及父目录/后代无链接、内容仅本轮4张PNG及1份Playwright状态JSON，已精确删除该目录并确认不存在。临时截图不可恢复，结论与指标保留于本节；未删除其他历史材料、源码、业务数据、模型、APK或构建产物。

## 2026-11-17 M36-T45 修复参数类别卡片底部边框缺失

- L1，局部CSS边框修复。按frontend-design技能保留既有卡片配色/布局及交互，仅对平台编辑和项目只读的参数类别卡片取消内部折叠项的负下边距，使父卡片底边完整露出；不修改共享折叠组件，不改参数、接口或业务行为。
- 用户截图问题已在原生产构建复现：Element Plus的`.el-collapse-item:last-child{margin-bottom:-1px}`让标题/内容背景覆盖父卡片底边中间部分。1440平台编辑的三个收起卡片底边计算样式均为1px solid、颜色`rgb(217, 226, 220)`，内部末项margin-bottom=-1px，与卡片下沿间距0，遮住1px底边；原截图复现并人工回看。
- 修复前执行`PLAYWRIGHT_CHROMIUM_EXECUTABLE=C:\Program Files\Google\Chrome\Application\chrome.exe`及`npm run test:e2e -- --config playwright.parameter-border.config.ts --max-failures=1`：第1项按预期在间距应>=0.99px的断言失败（实际0），其余3项未执行。保留失败事实，不计为通过。所有请求经隔离夹具拦截，无真实业务写入。
- 版本/环境：HEAD `4e9faf48dbd4800f7af7d09599337ec2d872840d`，含既有及本轮未提交/未跟踪改动，保留既有工作；本轮测试针对工作树，不代表干净提交发布认证。Windows/PowerShell、Node v24.19.0、npm 11.17.0、Chrome 157.0.8103.52，2026-11-17 Asia/Shanghai。
- 在`admin-web/`运行`npm run build`、`npm run build:preview`：均通过vue-tsc及Vite，3641模块，Vite耗时689ms/583ms，已更新本地`dist`与`dist-preview`。`node node_modules/typescript/bin/tsc --noEmit --skipLibCheck --strict --target ES2022 --module ESNext --moduleResolution Bundler --lib ES2022,DOM,DOM.Iterable --types node playwright.parameter-border.config.ts tests-e2e/parameter-card-border.spec.ts`通过。
- 修复后`npm run test:e2e -- --config playwright.parameter-border.config.ts`：4/4通过（8.3秒）；两次仅调整长卡片截图滚动位置后的复测也均4/4通过（8.4秒/最终10.3秒），产品代码未随截图调整改变。初次长卡片整元素截图受弹窗视口裁切，因此最终将卡片底部滚入可见区后截图，没有据被裁切截图宣称底边视觉通过。
- 浏览器以`127.0.0.1:5192/admin/`运行生产构建，拦截业务HTTP及WebSocket。四项为平台编辑Android参数/项目只读服务端参数×1440/390宽度，分别检查3个类别“收起→全部展开→全部收起”的36组卡片状态：末项margin-bottom均0px，内部末项距父卡片下沿均1px，收起时标题距下沿1px；底边均1px solid且与顶边同色，无卡片横向溢出，写请求0、页面JS异常0。
- 已人工回看修复前底边缺失图及修复后桌面编辑收起、窄屏只读收起、窄屏编辑展开底部、桌面只读展开底部，线条完整连接圆角。没有通过加粗/换色或全局裁切隐藏问题。
- 本次L1范围未重复业务单元测试或完整保存/发布回归；相关结果见M36-T44，本节不将其冒充本轮新测。真实业务后端/生产部署/其他浏览器及Android真机未验证；未部署、重启、迁移、commit/push或构建APK。此CSS修复不需要后端重启，远程需按Git优先流程发布前端后生效。
- 本节是本轮唯一测试报告。报告写入并回读后，确认最终浏览器服务已结束、5192监听数0、`.tmp/m36-t45-parameter-border`绝对路径及父目录/后代均无链接，内容仅12张PNG及1份Playwright状态JSON，已精确删除该临时目录并确认不存在。临时截图不可恢复，结论与指标保留在本节；未清理其他历史材料、源码、业务数据或构建产物。npm配置/NO_COLOR提示不影响验证结论。

## 2026-11-17 M36-T44 优化平台模型参数档案编辑弹窗

### 任务、范围与实现

- L2，优化平台管理“模型参数档案”的编辑呈现，按frontend-design技能沿用现有绿色主题与项目只读详情的层次；不重设计全站。编辑分为模型身份、目标端、修订摘要、识别基础参数、类别与告警规则、审计和操作区。
- 新增模型版本、草稿修订、已发布修订（包括未发布/r0）和参数来源摘要；明确显示“与发布版一致”“有未保存编辑”“草稿待发布”“尚未发布”“需要重新核验”及对应说明。搜索/展开不产生脏状态。
- 基础参数增加简短说明；类别标题展示名称/原始标签、启用状态及严重度；启用开关与业务名称/事件编码/严重度分组，拍照识别与相机巡检各自成组，保留置信度、毫秒/帧单位和全部原始范围。保留关闭类别的参数，提供搜索无结果/空类别提示。长名称/标签/审计账号换行，窄屏自然纵排。
- 操作区位于内容正常流中，说明与按钮分行；桌面辅助操作居左、保存/发布居右，窄屏两行排列。沿用既有保存、重置、发布函数及参数校验、精确版本/目标端、确认、冲突禁重试/重新读取行为，不改变HTTP/数据库契约、权限、参数值、模型/场景或Android运行逻辑。项目与场景继续只读。

### 环境与实际验证

- HEAD `4e9faf48dbd4800f7af7d09599337ec2d872840d`，工作树含既有及本轮未提交/未跟踪改动，已保留；测试针对当前工作树，不是干净提交的发布认证。Windows/PowerShell，Node v24.19.0、npm 11.17.0、Chrome 157.0.8103.52，2026-11-17 Asia/Shanghai。
- 在`admin-web/`执行`npm run test -- tests/category-parameters.test.ts tests/assignment-targets.test.ts tests/scenes.test.ts tests/models.test.ts --maxWorkers=2`：4文件83/83通过，20.23秒，无失败/跳过。新增编辑摘要/状态与搜索展开无写入、置信度关系校验、重置确认且不影响发布修订、冲突保留编辑并禁重试/重新读取恢复；保留平台保存发布及项目/场景只读与既有模型/场景回归。
- `npm run build`与`npm run build:preview`均通过vue-tsc和Vite，均3641模块；最终Vite耗时分别667ms/918ms。本地`dist`/`dist-preview`已更新，没有上传或远程发布。初次生产构建也通过（671ms），之后仅因底栏铺满宽度调整重新构建。
- 浏览器文件独立TypeScript检查通过：`node node_modules/typescript/bin/tsc --noEmit --skipLibCheck --strict --target ES2022 --module ESNext --moduleResolution Bundler --lib ES2022,DOM,DOM.Iterable --types node playwright.parameter-editor.config.ts tests-e2e/platform-parameter-editor.spec.ts`。
- 设置`PLAYWRIGHT_CHROMIUM_EXECUTABLE=C:\Program Files\Google\Chrome\Application\chrome.exe`，最终执行`npm run test:e2e -- --config playwright.parameter-editor.config.ts --max-failures=1`：11/11通过，约1.2分钟。独立`127.0.0.1:5191/admin/`服务生产静态产物，业务HTTP/WebSocket由夹具拦截；所有写入仅修改内存夹具，没有连接业务后端/数据库。
- 4项编辑流程分别在1440/768/390/320×960，逐一操作Android（初始r7）和服务端（初始r11）：摘要及干净状态、搜索/无结果、修改识别置信度/类别名称/编码/严重度/连续帧/停留时间、类别关闭再启用、展开审计、保存草稿、取消发布/确认发布、取消重置/确认重置、重新读取。核验每端精确`platform`与`version=2.0.0`和预期草稿/发布修订。每项仅有`PUT,POST,DELETE,PUT,POST,DELETE`六次夹具写入；保存不隐式发布，取消操作不写入，重置保留已发布修订，每端参数GET两次。
- 编辑布局四宽度/两端均无内容或弹窗体横向溢出、长名称与状态标签无重叠、数字输入值无裁切，拍照/相机组间距12px，底栏说明/按钮间距14px，390/320宽度纵向排列；上述流程页面JS错误均0。另1项冲突流程通过，保留编辑值、禁用保存/重置/发布、无自动重试，读取后恢复。
- 其余6项为项目只读与未发布状态回归：四宽度分别验证PC/Android只读参数，精确版本/目标端及重新读取，写请求和页面JS错误均0，无横向溢出/名称标签重叠，组/底栏间距12px；1440/390验证未发布→重新读取发布r0。人工回看编辑1440/390总览、规则、操作区共6张最终截图及390项目只读规则截图，未见提示与按钮重叠；长内容通过正常滚动查看。
- 定向`git diff --check`通过。npm home/sass配置、NO_COLOR及Git换行符警告未阻断验证。本轮定向检索误进入历史受限APK证据目录时收到拒绝访问；未读取/修改/删除其中内容，后续检查限定当前源码与本轮临时目录。

### 失败、修正与复测事实

- 首轮浏览器：1440和768用例超时，均停在脚本直接点击Element Plus内部不可见的`input[role=switch]`，没有进入保存/发布。第三项开始后主动中断，剩余用例未完成，不能计为通过。改为点击组件可见`.el-switch`容器，产品开关/写操作逻辑未因此修改。
- 第二轮浏览器：1440用例已完成Android保存、取消/确认发布和取消/确认重置，切换服务端后因脚本仍等待“全部展开”而超时（实际沿用“全部收起”状态）；1失败、其余10项未执行，不能计为通过。修正为仅在尚未展开时点击，保留目标端切换时已有展开状态。
- 人工回看第二轮1440三张截图后，将编辑底栏显式铺满可用宽度，说明居上、辅助与提交按钮分列。重新生产构建后第三轮11/11通过，上述失败历史保留，不用最终通过覆盖。

### 边界、风险与留存

- 真实业务后端/账号/数据、远程Docker/K8s及Android真机未验证；浏览器写流程为真实浏览器加隔离夹具，不替代真实业务集成、M198-T02或整个M36验收。本节不继承文首历史passed作为本轮整体验收结论。
- 无后端产品代码或数据库结构变更，本轮不需要重启后端或迁移数据库。未commit/push、部署、重启或构建APK；远程需按Git优先流程发布管理前端后生效。
- 本节为本轮唯一最终测试摘要。报告写入并回读后，确认最终浏览器进程已退出、5191监听数0，核对`.tmp/m36-t44-parameter-editor`绝对路径、目录/父目录/后代均无链接且内容仅12张PNG和1份Playwright状态JSON，已精确删除该目录并确认不存在。临时截图不可恢复，关键布局指标及结论已保留于本节；未清理其他历史材料、源码、业务数据、模型、APK或构建产物。

## 2026-11-17 M36-T43 优化项目模型只读平台参数弹窗

### 任务、范围与实现

- L2，管理后台只读参数弹窗的呈现优化。原项目入口复用禁用输入框的编辑表单，版本、数值与类别条件缺少只读阅读层次；本轮采用frontend-design技能，保留现有后台配色和弹窗尺寸，增加共享`ParameterReadOnly.vue`，不重设计全站。
- 标题改为“查看平台参数”，突出模型名称/ID与只读标识；展示模型版本、参数修订、参数来源，存在场景修订时也显示。基础参数直接展示实际数值，最大检测结果带“项”；类别折叠区显示启用状态与严重度，事件编码可换行，拍照/相机条件分组展示并保留原始毫秒/帧单位。搜索、全部展开/收起、单项键盘展开、修改审计与重新读取保持可用。
- 项目及场景只读入口共用该呈现；没有输入开关、保存、重置或发布按钮。未发布、403/404、网络失败仍分别呈现，版本不一致明确提示重新核验。空类别与搜索无结果有独立提示；缺失参数不伪装成已发布。
- 不更改平台端参数编辑、保存/重置/发布逻辑，不更改HTTP/数据库契约、精确版本/目标端读取、角色权限、模型/场景运行逻辑或Android；不写真实业务数据。本次仅整理弹窗样式和只读呈现，不改变参数值。

### 环境与实际验证

- HEAD `4e9faf48dbd4800f7af7d09599337ec2d872840d`，当前工作树包含此前及本次未提交/未跟踪变更；保留既有变更，测试结果属于当前工作树，不是干净提交的发布认证。Windows/PowerShell，Node v24.19.0、npm 11.17.0、Chrome 157.0.8103.52，2026-11-17 Asia/Shanghai。
- 在`admin-web/`运行`npm run test -- tests/category-parameters.test.ts tests/assignment-targets.test.ts tests/scenes.test.ts tests/models.test.ts --maxWorkers=2`：4文件79/79通过，22.46秒，无失败/跳过。覆盖项目/场景/显式readOnly三种只读入口，无参数写调用与对象改写；精确模型版本/平台及场景绑定重新读取；类别搜索/空结果/展开、r0、空类别、版本不一致；保留原未发布/读失败/平台保存与发布测试及模型、场景回归。
- `npm run build`、`npm run build:preview`均通过vue-tsc和Vite；3640模块，Vite分别636ms/654ms。本地`dist`与`dist-preview`已更新，无上传/远程部署。
- 浏览器相关文件通过独立TypeScript检查：`node node_modules/typescript/bin/tsc --noEmit --skipLibCheck --strict --target ES2022 --module ESNext --moduleResolution Bundler --lib ES2022,DOM,DOM.Iterable --types node playwright.parameter-details.config.ts tests-e2e/project-parameter-details.spec.ts tests-e2e/platform-parameter-state.spec.ts tests-e2e/scenes.spec.ts`。
- 设置`PLAYWRIGHT_CHROMIUM_EXECUTABLE=C:\Program Files\Google\Chrome\Application\chrome.exe`，执行`npm run test:e2e -- --config playwright.parameter-details.config.ts`：6/6通过，20.3秒。使用独立`127.0.0.1:5190`生产静态构建服务，HTTP/WebSocket均由路由夹具拦截，不连接业务后端/数据库。
- 新增4项分别在1440/768/390/320×960验证PC（server，r7）和Android（android，r11）参数：精确版本读取与重新读取各1次/端；类别搜索、空结果、展开/收起、键盘Enter展开、长模型名/类别名/无空格标签/事件编码/审计账号、关闭类别说明、毫秒与帧单位。所有宽度页面/弹窗/内容区横向溢出均无；状态标签与名称无重叠，分组及底栏说明/按钮间距均12px；窄屏两类条件纵向排列。每项4次参数GET，业务写请求0、页面JS错误0。
- 另外2项既有发布状态用例在1440/390验证未发布→重新读取已发布r0，保留精确版本/目标端查询和只读边界；发布后显示基础数值与空类别提示，不再断言禁用输入框。已人工回看1440/390总览、规则展开及390未发布共5张截图，未见文字/按钮重叠或裁切；长规则需正常滚动查看，不使用浮动底栏遮挡内容。
- 定向`git diff --check`通过。npm home/sass配置、NO_COLOR及Git换行符警告未阻断本轮验证。所有实际测试首轮通过，没有把未运行项目计入通过。

### 边界、风险与留存

- 真实业务后端/账号/数据、远程Docker/K8s及Android真机未验证；本轮为真实浏览器加隔离数据的界面验收，不替代M198-T02或整个M36业务验收。既有`scenes.spec.ts`只同步只读弹窗标题并类型检查，整份历史脚本仍含已退役的独立场景参数编辑流程，本轮未执行，不宣称其业务E2E通过。
- 无后端产品代码/数据库结构变更，本轮无需重启后端或迁移数据库。未commit/push、重启、远程部署或构建APK；远程仍需按Git优先流程发布前端后生效。本段不继承报告顶部历史passed为新的整体验收结论。
- 本节为唯一最终测试摘要。报告写入并回读、浏览器测试结束且确认5190监听数0后，核对`.tmp/m36-t43-parameter-details`的绝对路径、目录与父目录均无链接、内容仅6张PNG及1份Playwright状态JSON，已精确删除该本轮临时目录并确认不存在；截图不可恢复，关键布局指标与结论保留于本节。未清理其他历史材料、源码、业务数据、模型、APK或构建产物。

## 2026-11-17 M36-T42 同步与异步简明区别说明

### 任务、范围与环境

- L1，管理后台场景界面的静态说明调整。新增共享`SceneExecutionHelp.vue`，在高级运行方案的执行方式选项下方和只读场景详情中使用同一份三行说明；按frontend-design技能关注可读性与现有界面一致性，沿用现有颜色和字号，文字自然换行，不使用悬浮提示或固定高度。
- 文案：同步“对同一帧依次识别，整组识别结束后统一展示结果”；异步“各模型按自己的间隔依次识别，完成一个就先展示该模型的结果”；共同注明“目前都依次推理，不会同时运行多个模型”。没有改变执行方式、调度、线程、平台参数、默认单模型方案或客户端能力边界。
- HEAD `4e9faf48dbd4800f7af7d09599337ec2d872840d`，测试对象为含此前及本次未提交改动的工作树，不代表该提交的干净检出。Windows/PowerShell、Node v24.19.0、npm 11.17.0；不连接真实业务库。

### 实际命令与结果

在`admin-web/`执行：

```powershell
npm run test -- tests/scenes.test.ts tests/scene-runtime-capabilities.test.ts tests/camera-policy.test.ts
npm run build
```

- 3文件71项全部通过，0失败/跳过，耗时15.47秒。新增编辑区说明展示与默认single配置不变的组件测试；扩展只读详情用例验证同步、异步和依次推理说明，保留不改写场景、不调用patch及图片/PC能力边界断言。
- `npm run build`包含`vue-tsc --noEmit`及Vite生产构建，退出码0；3636模块，Vite耗时635ms。本地`dist`已更新，没有上传或部署。
- 在服务端根目录执行`git diff --check -- admin-web/src/features/scenes/SceneExecutionHelp.vue admin-web/src/features/scenes/ScenesView.vue admin-web/tests/scenes.test.ts`，退出码0；新组件与两处引用另已回读确认。保留既有npm配置警告及Git换行提示，没有测试失败。
- 无本轮独立原始日志目录、截图或测试服务；结果统一留在本段。Harness实现未修改，不运行其单元测试。

### 未验证与风险

- 未执行真实浏览器宽窄屏视觉/E2E、生产后端或Android真机验收；本轮通过不替代M198-T02真机验收，也不继承报告顶部历史passed为新的整体验收结论。
- 未重启后端、修改数据库、构建APK、commit/push或部署。远程后台需要按Git优先流程发布前端后才能显示新说明；本次纯前端说明调整不要求后端迁移或重启。

## 2026-11-17 M36-T41 对齐新版App异步视频能力提示

### 任务、范围与环境

- 验证级别L2；仅后台能力呈现、文案和相关测试。沿用现有组件设计，没有重做布局、改变HTTP/数据库契约、修改已保存场景或扩大PC/图片联合能力。对应Android M198-T01。
- HEAD `4e9faf48dbd4800f7af7d09599337ec2d872840d`，含此前及本次大量未提交/未跟踪改动；测试的是当前工作树。Windows/PowerShell、Node v24.19.0、npm 11.17.0。
- 新版App两个移动端视频成员的sync/async方案显示“新版 App 仅视频 · 需在线预检”；禁用、待批准、不可用和参数未就绪提示优先。图片-only、PC、混合端、成员不支持视频、单/三成员联合、重复/缺失成员不宣称可运行。旧executionSupported投影不等于新App能力，不修改后端该字段。
- 模式选项去掉笼统“仅配置”，草稿按实际成员/输入显示范围；明确需要升级App、在线授权及预算核验。旧场景不自动改模式，新建场景默认仍逐成员single，联合异步由用户高级设置明确选择。

### 实际命令与结果

在`admin-web/`执行：

```powershell
npm run test -- tests/scenes.test.ts tests/scene-runtime-capabilities.test.ts tests/camera-policy.test.ts
npm run build
```

- 最终3文件70项全部通过，无跳过/失败；新增能力矩阵22项，并增加真实Vue组件详情展示断言，覆盖只读视图、图片/PC边界及不改写配置。
- `npm run build`包含`vue-tsc --noEmit`及生产Vite构建，均退出码0。Vite转换3634模块；前端产物仅用于本地验证，没有上传/部署。
- 最初命令误写`tests/scene-camera-policy.test.ts`，只匹配到2文件66项；随后核对实际文件名并改用`tests/camera-policy.test.ts`，最终70项包含新增组件用例与该文件。没有把未匹配的文件计为已执行。
- `git diff --check`通过；npm既有home/sass_binary_site配置警告及Git换行符提示未阻断测试/构建。
- 更新`tests-e2e/scenes.spec.ts`中受影响的模式文案断言，但**未执行真实浏览器E2E**；该历史脚本还包含旧场景参数编辑流程，不代表目前全链路已通过，本次不扩大迁移范围。

### 未验证与风险

- 浏览器宽窄屏视觉、真实业务库、生产后端/Android端到端及ARM真机未验证；Android人工验收保持M198-T02待办。本文本轮段落不继承报告顶部历史passed为新的大任务验收结果。
- 未重启后端、未迁移数据库、未安装/正式签名App、未commit/push/部署。使用新能力需要后续发布后台并升级到包含M198修改的App；本次不承诺用户当前已安装版本可异步运行。
- 未创建独立原始日志目录/测试服务，未删除历史材料或构建产物。测试结果以本段为唯一摘要记录。

## 2026-11-17 M36-T40 简化创建场景弹窗

### 范围与设计

- L2，管理后台创建表单的交互/默认方案调整，不改后端产品接口、数据库、Android或运行时策略。原界面同时要求理解场景ID、成员声明、方案ID、成员输入及相机时序，常用创建流程操作过多。本次按frontend-design技能采用现有绿色后台的克制布局和渐进展示，不重设计全站。
- 常用流程为名称→用途（图片/视频）→选择精确版本/目标端模型→保存。场景ID用UUID生成并允许高级设置中编辑，选择模型立即加入，已选区保留名称、版本、目标端、发布状态、实际输入能力和移除操作。
- 新场景默认每个已选成员生成独立single方案；不是联合识别，也不是自动启动推理。方案ID与成员身份绑定，自动模式随成员删除/输入收窄更新。视频沿用工程默认cameraPolicy（5帧、5000/6000/1500ms），不改平台推理参数，也不保证设备性能。
- 高级设置默认收起，保留ID/启用开关、成员排序/输入/声明、自定义方案与相机策略。已保存自定义方案后停止自动重建；收起/展开和刷新模型状态均保留草稿。未保存的方案草稿会阻止提交并展开提示；主动移除全部方案后要求明确配置方案，不依赖服务器隐式补回。已有场景编辑与管理成员不自动生成或覆盖方案。
- 平台参数发布、角色权限、精确分配身份、CAS和409禁重试不放宽；保存仍待批准，未自动发布参数或批准场景。未修改业务数据库、未创建真实业务场景、未重启服务/部署/commit/push。

### 环境、命令与最终结果

- 基础Git提交`4e9faf48dbd4800f7af7d09599337ec2d872840d`，dirty工作树；大量既有变更保留，仅增量修改场景Vue/CSS、相关测试、M36任务元数据及本报告。本机Windows/PowerShell，Node v24.19.0，项目.venv Python，Chrome 157.0.8103.52，2026-11-17 Asia/Shanghai。
- admin-web：`npm run test -- tests/scenes.test.ts tests/assignment-targets.test.ts tests/models.test.ts --maxWorkers=2`，最终3文件67/67通过，15.70秒；其中场景44项。新增覆盖自动ID/独立方案/默认视频策略、逐成员输入与移除、刷新及折叠保持、自定义策略不覆盖、未完成草稿、无方案拦截、未发布及409无重试、新建重开复位；既有编辑/CAS/权限/平台状态等回归通过。
- `npm run build`和`npm run build:preview`均通过vue-tsc和Vite（3634模块，627ms/721ms），本地dist及dist-preview已更新。新增浏览器配置及4个相关E2E源文件使用`node node_modules/typescript/bin/tsc --noEmit --skipLibCheck --strict --target ES2022 --module ESNext --moduleResolution Bundler --lib ES2022,DOM,DOM.Iterable --types node playwright.scene-create.config.ts tests-e2e/scene-create-simple.spec.ts tests-e2e/scene-parameter-layout.spec.ts tests-e2e/scenes.spec.ts tests-e2e/scene-inputs.spec.ts`检查通过。
- server-video-service：本进程显式清空DATABASE_URL/TEST_DATABASE_URL（不改.env），运行`.venv/Scripts/python.exe -c "import sys,unittest;sys.path.insert(0,'tests');suite=unittest.defaultTestLoader.loadTestsFromName('test_project_scenes.SceneApiTests');result=unittest.TextTestRunner(verbosity=1).run(suite);sys.exit(not result.wasSuccessful())"`，12/12通过，29.742秒。现有fixture使用临时模型目录与内存项目/场景存储；新例证实与UI相同的双目标端、UUID编号、独立单模型方案请求201，保持revision=1/approved=false、普通成员不可见、无运行流。未执行PostgreSQL/全后端套件。
- 浏览器：设置PLAYWRIGHT_CHROMIUM_EXECUTABLE为`C:\Program Files\Google\Chrome\Application\chrome.exe`，`npm run test:e2e -- --config playwright.scene-create.config.ts`最终8/8通过、16.0秒。127.0.0.1:5188独立静态服务，HTTP/WebSocket全使用路由夹具，不访问真实业务API。1440/768/390/320×960四种宽度各验证常用创建和未发布提示；创建用例每例仅1次被夹具拦截的POST，方案2个、无批准调用；参数布局用例每例3次状态GET/0写入。8例JS异常均0。
- 真实浏览器覆盖自动加入两端模型、默认方案、折叠隐藏技术字段、键盘Enter展开/保存、刷新保留名称/成员/ID、自定义后收起再提交、无横向溢出。参数提示与按钮独立：纵向间隔12px，桌面横向20px，窄屏纵向12px；长名称可断行。最终1440/390截图已人工回看，保存操作为正常文档流，不用浮层遮挡内容；长列表需在弹窗内滚动。
- 定向`git diff --check`通过。既有npm home/sass配置、NO_COLOR、CRLF、Starlette/httpx弃用及测试启动apk_worker_iteration_failed诊断保留；场景断言无失败，不据此宣称APK后台worker健康。

### 首轮失败与修正

- 第一轮原36项场景回归通过；扩展后66项中65通过/1失败：happy-dom中Vue Test Utils isVisible与实际v-show内联display:none判断不一致，改为断言隐藏样式并在真实浏览器验证隐藏/展开，不删除该覆盖。
- 第一轮浏览器6通过/2失败：390/320选模型后立即测量页面，teleported下拉关闭过渡仍造成短暂横向溢出；诊断窄屏有scrollWidth=391/viewport=390、可见元素无越界，截图等待后恢复。模型候选下拉增加视口宽度上限/长文本换行，检查改为等待关闭过渡收敛，不放宽最终无溢出阈值。首轮视觉检查还发现尝试的sticky底栏会遮挡摘要，已改回正常布局。最终全8项通过。

### 留存与交接

- 唯一最终测试报告为本节，Harness完成记录仅链接本报告与代码。报告回读后，已确认测试进程退出、5188无监听，并核验精确目录/无链接/文件类型，删除唯一当前临时浏览器目录`.tmp/m36-t40-scene-create`（8张PNG和1个状态JSON），再次确认目录不存在。截图不可恢复，测试结论/失败原因/修正均留于本节；后端fixture自动清理临时目录。本轮未清理其他历史证据、模型、业务库、APK或备份。
- 未验证：真实用户业务库端到端创建/审批/巡检，PostgreSQL并发、Android真机、远程Docker/K8s发布。既有真实后端E2E脚本已适配高级展开/新用途文案并类型检查，但本轮未运行其登录真实隔离后端流程；不将夹具结果冒充生产验收。
- 本任务无后端产品代码或数据库结构改动，不需因本次改动重启后端或做迁移；本地静态构建已更新，浏览器刷新加载。远程环境仍需经授权按Git优先流程发布。此结论不代替此前M36-T39后端改动的重启要求。
- M36-T40已通过Harness complete登记，validate/render通过；未修改Harness实现，不运行Harness单元测试。父任务其他验收边界保持原状，不以本小任务替代整体验收。

## 2026-11-17 M36-T39 平台卸载后项目模型名称与启用状态

### 诊断、实现与边界

- L2，精确版本的展示元数据与项目清单交互修复。项目停用保留分配条目，平台卸载只将启用分配算作阻塞项，同时仍检查未删除场景、方案、流及活动槽位。卸载后版本从活动models移入modelHistory；原tombstone未保留name，项目名称查询只调用catalog.get，导致“未命名模型”。前端仍打开“重新启用”弹窗，但已卸载版本不在候选中，未解释原因。
- 保持原卸载政策：停用条目本身不阻止平台卸载；未删除场景/在用流等门禁不放宽，也不恢复已卸载模型。同一modelId/version的卸载身份仍不可复用。没有把停用视为项目条目删除，也不自动删除任何真实分配/场景。
- 新卸载tombstone额外保留name。`ModelCatalog.display_metadata`仅返回精确版本的name/status，优先活动版本，其次精确UNINSTALLED历史；不能提供产物、不能用于运行授权、不能借用另一个版本。`catalog_model_name`在活动版本不存在时使用历史名称；项目分配展示新增modelStatus，分别表示UNINSTALLED、MISSING、UNKNOWN及活动生命周期状态。
- 老卸载记录如果没留名称，不能凭空恢复：前端显示“已卸载模型（历史名称未留存）”，模型ID与版本仍在原位；真正找不到版本显示“模型版本已不可用”。名字仅用于显示，保存/删除仍用精确身份、权限与CAS。
- PC/移动端项目列表显示平台已卸载、产物已卸载、参数不可用；“重新启用”明确禁用并通过独立可读说明告知原因，保留“移除”及原确认。建议移除旧条目、添加平台已发布可用版本；重新上传不会自动恢复旧引用。后端直接提交卸载版本时返回409 model_uninstalled，含具体modelId/version及中文处理建议；其他发布/参数/授权门禁不变。
- frontend-design技能用于保持现有配色、列表层次和独立浅色说明区，不改全站视觉。未修改Android、数据库结构、生产环境或真实业务参数；未进行真实卸载/移除/重装。

### 环境与真实执行

- 基础Git提交`4e9faf48dbd4800f7af7d09599337ec2d872840d`，dirty工作树，已有其他任务未提交/未跟踪内容均保留。Windows/PowerShell，Python 3.13.15（项目.venv）、Node v24.19.0、Chrome 157.0.8103.52，日期2026-11-17 Asia/Shanghai。
- 后端命令在server-video-service执行，显式将本进程DATABASE_URL与TEST_DATABASE_URL设为空（不改.env），`.venv/Scripts/python.exe -c`载入unittest模块：`test_model_display`、`test_project_model_inventory`、`test_project_model_removal_history`、`test_resource_lifecycle`；使用各测试自身临时文件/SQLite及内存API隔离，无业务库连接。
- 首轮69项：40通过、28跳过、1错误。新测试错误地从普通项目用户读取停用条目，权限过滤正确返回空，导致IndexError；修正为负责人查看完整清单，增加普通用户仍看不到停用条目的断言。追加SQLite重开回归后，最终71项：42通过、29跳过、0失败/错误，55.431秒。跳过均为未启用的PostgreSQL/行锁测试，本轮不声明PG通过。
- 新增覆盖：真实测试API分配→停用→平台卸载→保留精确历史名称/状态→重新启用409→负责人移除；另一版本仍发布，catalog.get仍拒卸载版本；旧无name历史不借其他版本名称、不改注册表；缺失状态；SQLite存储/目录重开后保持名称、停用及revision，仍可显式移除。原场景/权限/生命周期回归通过。
- 追加`test_model_catalog`、`test_model_catalog_source`同样以项目Python unittest运行：10/10通过，5.181秒。后端总计52通过、29跳过。
- 在admin-web运行`npm run test -- tests/assignment-targets.test.ts tests/scenes.test.ts tests/model-display.test.ts tests/models.test.ts --maxWorkers=2`：实际匹配3文件59/59通过，12.68秒（不存在独立model-display.test.ts文件，不计虚构覆盖）。新增5项涵盖PC/mobile卸载名/禁用原因/显式移除和历史缺名、缺失、未知状态。
- `npm run build`、`npm run build:preview`均通过vue-tsc与Vite（3634模块，622ms/643ms），本地正式及预览构建更新。新增独立E2E配置/测试通过`node node_modules/typescript/bin/tsc --noEmit --skipLibCheck --strict --target ES2022 --module ESNext --moduleResolution Bundler --lib ES2022,DOM,DOM.Iterable --types node playwright.inventory-lifecycle.config.ts tests-e2e/project-model-lifecycle.spec.ts`。
- 浏览器：设置PLAYWRIGHT_CHROMIUM_EXECUTABLE为本机Chrome绝对路径，执行`npm run test:e2e -- --config playwright.inventory-lifecycle.config.ts`。独立127.0.0.1:5189加载真实生产静态构建，HTTP与WebSocket全拦截测试夹具，未登录真实账号。1440/390×960分别验证PC与移动端，每端3条已卸载/缺名/缺失记录。
- 首轮浏览器2失败：确认框实际语义是alertdialog，测试错误使用dialog；窄屏原有8px间距被测试错误要求至少10px。修正测试以遵循实际组件语义与现有响应式间距，未借此放宽重叠检查。最终2/2通过、8.8秒，长名称无横向溢出，按钮与说明至少8px间距；启用按钮禁用、移除按钮可用，移除确认正确显示名称并可取消；业务写请求0、页面JS错误0。回看1440 PC与390移动端截图确认实际排版。
- 定向git diff --check通过。保留既有npm配置、NO_COLOR、Git CRLF、Starlette/httpx弃用警告，不当作产品失败。

### 留存、交接与未验证

- 最终测试报告为本节，不另存整套日志。临时目录唯一归属`.tmp/m36-t39-model-lifecycle`，最终4张PNG和1个Playwright JSON；失败的测试预期及原因已保留本节。临时服务退出且5189无监听，报告回读后核对精确路径/文件类型/无链接，已删除本次目录并确认不存在；临时截图不可恢复，结论保留。不清理其他任务历史材料、模型、业务库或备份。Harness complete后validate/render通过。
- 未验证：本轮PostgreSQL并发测试、用户已运行后端上的实际记录、真实业务卸载/重装/场景运行、Android真机、远程生产。fixture浏览器与内存/SQLite接口通过不替代上述验收。
- 此次含后端改动，现有本地进程需要用户重启以加载新代码，同时刷新浏览器；无需新增数据库迁移。本任务未重启后端、未部署容器、未commit/push。
- 修复前已卸载且未留存name的历史无法自动恢复原名称；若用户需要恢复具体名称，须另外核实该精确版本的可信备份/记录后再决定，不能从同名/其他版本猜测。

## 2026-11-17 M36-T38 场景参数提示与刷新操作响应式布局

### 范围、版本与环境

- 验证级别L1，管理后台局部布局与说明文字调整，不修改模型发布条件、接口、权限、场景保存逻辑、数据库或Android。按frontend-design技能采用克制的现有绿色界面风格，以浅琥珀色标注待处理状态，未重设计整页。
- 用户截图的提示文字和刷新按钮紧贴：原按钮与small说明直接位于同一警告div内，没有独立布局及gap。改成上方状态提示卡、下方独立中性刷新操作栏；模型名称和版本/目标端分行，PC明确补充“服务端”。未发布模型不影响其他就绪模型的说明更准确，正常状态不保留警告底色。
- 桌面操作栏左侧说明、右侧刷新按钮；600px以下上下排列且按钮全宽。提示卡与操作栏12px间距；说明与按钮桌面20px、窄屏12px；模型卡片自适应列数和长名称断行。保留刷新草稿、未发布禁选/禁保存、未知状态及409禁止重试逻辑。
- 基础Git提交`4e9faf48dbd4800f7af7d09599337ec2d872840d`，已有大量未提交/未跟踪变更，本任务只增量修改场景Vue/CSS、场景组件测试和新增隔离布局测试/配置及本报告、Harness记录。未commit/push。
- Windows/PowerShell，Node v24.19.0、Python 3.13.15、Chrome 157.0.8103.52，日期2026-11-17 Asia/Shanghai。浏览器只访问本次临时127.0.0.1:5188静态构建，HTTP API为测试夹具，未登录真实账号、未发布参数、未创建真实场景。

### 实际执行与结果

- 在`admin-web`运行`npm run test -- tests/scenes.test.ts --maxWorkers=2`：36/36通过，14.40秒。新增测试覆盖提示与操作区结构分离、目标端、辅助说明关联、发布后警告消失及草稿保留；既有未发布/未知状态禁选、已发布r0、409等场景回归均通过。
- `npm run build`及`npm run build:preview`：均通过vue-tsc与Vite构建，3634模块，Vite分别626ms和608ms；本地`dist`与`dist-preview`已更新。另行`npm run typecheck`通过。
- 设置`PLAYWRIGHT_CHROMIUM_EXECUTABLE=C:\Program Files\Google\Chrome\Application\chrome.exe`后执行`npm run test:e2e -- --config playwright.scene-layout.config.ts`：最终4/4通过、4.8秒。真实Chrome渲染生产构建，1440/768/390/320×960四种视口；标准3模型和6个超长无空格名称，均无提示/操作区横向溢出或按钮说明重叠。1440/768左右排列间距20px，390/320上下排列间距12px；两个区域间距约12px。
- 每个浏览器用例模拟3次模型状态GET，写请求0次，页面JS异常0；键盘Enter刷新不提交表单，刷新前后ID/名称草稿保留，模拟已发布状态后警告消失。人工回看1440与390截图，确认标题、模型卡片、说明与操作层次清晰，未只依靠DOM测试推断视觉。
- 首轮浏览器4/4通过但应用壳的WebSocket尝试连接Vite代理并出现ECONNABORTED诊断；HTTP业务写请求仍为0。已补充WebSocket路由拦截，最终重跑4/4通过且该代理诊断不再出现。没有真实服务重启或配置变更。npm既有home/sass配置警告、NO_COLOR提示与Git CRLF提醒保留，不当作产品失败。
- 定向`git diff --check`通过；新增测试与独立配置通过`node node_modules/typescript/bin/tsc --noEmit --skipLibCheck --strict --target ES2022 --module ESNext --moduleResolution Bundler --lib ES2022,DOM,DOM.Iterable --types node playwright.scene-layout.config.ts tests-e2e/scene-parameter-layout.spec.ts`。未修改Harness实现/测试，不运行Harness单元测试。

### 留存与边界

- 本次临时诊断目录唯一归属`.tmp/m36-t38-scene-layout`，包含4张本轮浏览器截图及Playwright状态JSON；无业务数据、模型、APK或迁移备份。临时预览服务已停止、5188端口已确认关闭；报告回读后核对精确绝对路径、文件类型及无链接，已清理4张PNG和1个JSON并确认目录不存在。临时截图不可恢复，验证结论及失败/诊断事实保留于本报告；未删除其他历史目录或业务材料。
- 未验证：真实管理员发布参数后创建业务场景、Android真机、远程/生产页面与用户浏览器缓存。上述夹具浏览器结果只证明本次布局/前端刷新行为，不等价业务端到端验收。
- 不需要后端重启或数据库迁移；使用本地新构建需刷新浏览器。远程环境仍须另行授权按Git优先流程发布。本次未部署、未改真实参数。

## 2026-11-17 M36-T37 场景创建的平台参数未发布提示

### 任务、诊断与范围

- L2，管理后台状态判定与提交前校验修复。截图中项目模型ID`cebb3b7b-0a84-4867-abcd-2264bf1ac4e8`对应Default Project的`uploaded-c8dffd82f6a24deca8d03afdae24956f / 1.0.0 / android`（显示名ppe），不是内置modelId=ppe。通过本地数据库只读事务核验，该精确平台参数档案无已保存草稿行，按精确参数profile key直接检查PUBLISHED审计记录为0；迁移版本已是20261117_35。本轮没有发布参数、修改业务库或创建真实场景。
- 后端`resolve_inventory_members`拒绝缺少平台发布快照，符合现有平台统一参数规则；本次不取消该门禁、不回退默认草稿/旧项目参数，也不把模型文件发布当成参数发布。结构迁移本身不会生成平台发布记录。
- 原场景编辑器仅按assignment.enabled标注可用，并把未发布的parameterRevision=0显示成“参数r0”，未检查parameterPublished。新逻辑必须parameterPublished=true才允许加入成员；false显示“平台参数尚未发布”，缺失状态显示“参数状态待核实”，可用数量不再包含两者。合法的已发布r0继续允许使用，精确区分版本和Android/服务端。
- 在编辑器显示未发布模型名称、版本、目标端及平台参数发布路径；已有成员随候选状态刷新显示正确状态，提交前拒绝未发布/未知状态。新增“刷新项目模型状态”，仅刷新候选不清空场景ID、名称、成员或方案草稿。
- 服务端返回platform_parameters_unpublished时统一映射为中文平台发布说明；保留既有409关闭刷新/禁止自动重试机制。没有修改共享写入重试策略、权限、场景审批或参数发布API。
- 使用frontend-design技能维持现有界面组件/提示样式，不重设计页面。仅修改ScenesView.vue、management/api.ts及scenes.test.ts，保留其他任务的未提交变更。

### 版本、环境与验证

- 基础提交`4e9faf48dbd4800f7af7d09599337ec2d872840d`，dirty工作树；Windows/PowerShell，Node v24.19.0，日期2026-11-17 Asia/Shanghai。没有commit/push、部署、重启、APK构建或真实参数发布。
- 在`admin-web`执行`npm run test -- tests/scenes.test.ts tests/category-parameters.test.ts tests/assignment-targets.test.ts tests/models.test.ts --maxWorkers=2`：4文件61/61通过，7.91秒。新增5项覆盖未发布/未知状态禁选、双目标端区别、已发布r0、刷新状态保留草稿并阻止保存/发布后恢复、后端冲突中文提示且不重试。
- `npm run build`通过vue-tsc和正式Vite构建，3634模块，Vite625ms；`npm run build:preview`通过vue-tsc和预览构建，3634模块，Vite621ms。已更新本地dist与dist-preview，远程产物未发布。
- 定向`git diff --check`通过。npm保留既存home/sass_binary_site未知配置警告，Git保留CRLF转换提示；无测试失败。初期检索出现无关历史测试目录访问拒绝和不存在的文档文件名，后续改用已存在的权威`docs/platform-model-parameters.md`，未改权限或历史材料。
- 仅读取业务库确认具体身份及参数发布缺失；未调用可能触发旧数据导入的参数读取服务。末次直接profile key查询仍为0条PUBLISHED，未伪造参数发布成功。

### 未验证与交接

- 用户需以平台管理员进入“平台模型资产 → ppe / 1.0.0 → 模型参数档案 → Android参数”，核对检测阈值与类别开关，需要修改时先保存草稿，再明确点击“发布参数”。发布会影响引用该精确版本/目标端的各项目新运行，必须由用户确认，不能由本任务默默代发。
- 发布完成后重新打开场景编辑器，或在新界面点击“刷新项目模型状态”再保存。若已进入409锁定态，仍按既有提示关闭弹窗刷新后重开；不自动重放写入。
- 本次只有前端源码和本地静态构建变化，不要求再次数据库迁移或后端重启。浏览器需加载新前端构建；正式远程环境需按Git优先发布流程另行授权。
- 本次未进行浏览器视觉验收、真实业务创建场景、平台发布参数、Android联调或生产部署；不能用组件测试代替用户实际创建成功。没有生成需清理的临时日志目录。

## 2026-11-17 M36-T36 经用户授权迁移本地数据库

### 范围、环境与结果

- 用户明确授权“进行本地数据库结构迁移，我来重启后端”。本次仅对本机`127.0.0.1:5432/aiyolo_dev`的`public` schema执行`20261105_34 → 20261117_35`；没有自动重启、移除模型、删除场景、发布Docker/K8s或commit/push。前文T35的“未迁移”是当时事实，本节记录后续已授权的本地迁移；其他环境仍未迁移。
- 服务端数据库结构迁移按L3高风险操作核验（非Android代码任务）；只执行已完成T35的精确迁移文件，不改产品源码、不重跑无关App构建或隔离业务套件。前置T35的迁移、权限及事务测试结果保留。
- Windows/PowerShell，项目Python 3.13.15，PostgreSQL服务和pg_dump均17.11；Asia/Shanghai日期2026-11-17。基础提交`4e9faf48dbd4800f7af7d09599337ec2d872840d`，工作树已有未提交更改，不代表已发布提交。
- 只读前检确认：driver为postgresql+psycopg、用户aiyolo_app、地址127.0.0.1、端口5432、数据库aiyolo_dev、schema public、版本20261105_34，旧表无archived_project_model_id；数据库83949235字节，检查时其他活动事务为0。密码仅由应用配置在内存传给备份子进程，未输出或写入报告。

### 迁移前备份（保留，不属于临时日志）

- 路径：`E:\aiyolo\server-video-service\backups\M36-T36-20261117-scene-history\aiyolo_dev-before-20261117_35.dump`。
- 完整数据库custom逻辑备份，7643597字节；SHA256：`72c216972f572fe0a7f8faf705aa8b00caf1c4519d0183713daa8b31ddf65aba`。备份含业务数据，仅留本地且由现有`backups/` Git忽略规则覆盖，未上传或删除。
- 实际调用`D:\PostgreSQL\bin\pg_dump.exe --format=custom --compress=6 --no-password --lock-wait-timeout=5000 --file <上述精确路径>`，连接身份通过子进程环境传递，明确限定上述本地数据库。新建专用目录，拒绝覆盖已有文件。
- `pg_restore --list <备份>`成功，含91项TABLE DATA以及场景成员和版本表；`pg_restore --file=NUL <备份>`完整解码成功。以上是备份可读性验证，不等于已执行恢复演练；本次没有向任何数据库恢复备份，也没有备份外部模型文件、对象存储或集群级角色。
- 执行前再次核验备份SHA256与迁移文件SHA256：`74dac6aff499b0c78748bafe73a8960b6db420679fc0e1305078c30cafb1d7c5`（`alembic/versions/20261117_35_scene_history_inventory_reference.py`）。

### 实际执行与完整性验证

- 在`E:\aiyolo\server-video-service`通过项目`.venv/Scripts/python.exe -B -c`调用Alembic `command.upgrade(config, '20261117_35')`，使用显式传入的同一个SQLAlchemy事务连接；没有使用`upgrade head`、stamp或回放历史迁移。
- 事务内设置`lock_timeout=5s`、`statement_timeout=60s`；锁定版本表并复核起点，短时锁定7张相关表防止摘要比较期间并发写入。迁移前后比较原字段内容（排除新列），断言版本、可空性、CHECK存在、原外键完全不变；通过后提交。整个迁移加提交后验证耗时0.269秒，退出码0。
- 新增归档列、project_model_id可空及身份二选一CHECK均验证通过；archived_project_model_id非空记录0、非法双空/双非空身份0。未自动将已删除场景的引用脱钩，该动作仍由用户后续显式移除项目模型触发。
- 提交后重新建立连接：版本为20261117_35，7张相关表记录数和SHA256与迁移前完全一致；应用`DatabaseManager.verify_schema()`返回`configured=true, backend=postgresql, status=ok, schema=ready`。

| 表 | 前后记录数 | 原字段规范JSON排序后SHA256（前后相同） |
|---|---:|---|
| project_model_assignments | 6 | b3a9f267cab3cd9d299046b66b6610f99958b76d673aa659fd666e6907121d13 |
| project_scenes | 4 | 39cab0a4cb9a74255df8cc96e112c8ecbe49111dd3cb823afb53dc746b66fa9d |
| project_scene_members | 8 | 17c89fdf1e1761ed36c312e3addb4080c241d554191c6ccfc6368639a0a1da85 |
| project_scene_plans | 2 | db6fd3b4891f2ae85c1e3aa49df3258ee04e54f5b4649e9e441a6243ac48e194 |
| project_scene_plan_members | 4 | d8463e31fcf592c9d6e9c2498a3e2118b4f62bad6e7ff1ae959b2237b781e078 |
| project_scene_installations | 8 | 0178677d8e90920491a4a8f0949bcaac1119de0b4ff674a51e495b62c6de0a08 |
| project_scene_runtime_grants | 16 | 8fc2ea4a4b23c9b2caf6ea5a53998a226771154dea2dc0c5c9da306cf5bd570f |

### 中间问题、未验证与交接

- 初次文件检索触及既有历史证据目录的访问限制；未更改权限或处理这些无关目录。一次只读探测命令因PowerShell引号错误未执行，改为内存here-string后成功；该失败没有运行迁移或改库。实际备份、迁移和提交后检查均一次成功，无数据回滚或重试迁移。
- 后端重启由用户执行；重启后需刷新项目模型列表，再尝试移除已无有效场景引用的模型。本次没有代替用户执行真实模型DELETE，因此运行中后端及浏览器完整链路未验证。
- 迁移脚本不支持直接downgrade。备份恢复属于后续需授权操作，会涉及备份时间点后的业务数据取舍，不得擅自恢复覆盖。真实恢复演练、外部文件备份、手机联调、远程与生产环境均未执行。
- 本次未生成需清理的临时日志目录；逻辑备份必须保留。Harness通过CLI完成M36-T36，随后validate和render均通过，记录为`harness/records/M36/M36-T36.md`；未改变Harness实现，未重跑Harness单元测试或执行大任务验收。

## 2026-11-17 M36-T35 已删除场景历史引用不再阻止项目移除模型

### 范围、根因与实现

- 本任务按服务端任务定义执行L2定向回归，并额外执行SQLite/隔离PostgreSQL结构迁移、约束、权限和事务回滚测试；未改Android代码，不套用Android构建门禁。本节不覆盖报告头部的历史验收结论，不表示当前M36全部范围重新验收或生产已发布。
- 原移除校验直接检查场景成员引用，未区分软删除场景；即使忽略业务校验，成员表的RESTRICT外键仍会阻止删除项目模型。不能通过删除全部历史成员或关闭外键解决。
- 新实现仅在明确移除项目模型且全部相关场景已删除时，在同一事务中将成员原项目模型ID保存在`archived_project_model_id`、解除当前外键，再移除项目分配并记录审计。历史成员、参数快照、方案和原身份保留；重新添加模型生成新身份，不把历史引用接到新分配上。平台模型文件不删除。
- 未删除场景（包括停用或未审批场景）仍阻止移除，中文错误列出最多5个阻塞场景名称。启用服务端流、修订冲突、权限及跨项目边界仍保护；审计失败时整笔事务回滚。内存分支同样区分删除状态，并先成功审计再移除分配。
- 新迁移`20261117_35`基于`20261105_34`：新增归档身份列、当前外键可空、两者必须且只能保留一个的CHECK；保留原RESTRICT。迁移本身不删除或脱钩业务记录，脱钩只发生于用户显式移除项目分配。为保护历史身份，不支持直接downgrade。
- 对本地配置业务库只读核验：Default Project中`uploaded-06b4dd2f10544673ab723226f91c34a7 / 2.0.0`的Android分配仍被已删除的`cj02`、`cj03`、`test01`引用（2026-11-17 10:57:46至10:57:54，Asia/Shanghai）；服务端分配被已删除`test02`引用（2026-11-02 21:26:12）。本轮未迁移、写入或删除业务库数据。

### 版本、环境与实际命令

- 基础提交`4e9faf48dbd4800f7af7d09599337ec2d872840d`，工作树dirty，已有大量变更全部保留；本次未commit/push、未发布、未重启用户服务。Windows/PowerShell、Python 3.13.15；Node v24.19.0仅环境信息，本任务未跑前端构建。
- 工作目录`E:\aiyolo\server-video-service`。测试命令统一为`.venv/Scripts/python.exe -B -m unittest discover -s tests -p <下表文件> -b`。
- PostgreSQL测试显式设置`DATABASE_URL=postgresql+psycopg://aiyolo_app@127.0.0.1:55481/postgres`及`RUN_POSTGRES_TESTS=1`，仅使用本次初始化的`.tmp/m36-t35-postgres-20261117/data`；启动前核对用户名、数据库、端口及data_directory，随机schema逐项创建/回收。未使用业务5432/aiyolo_dev执行测试。数据库基础测试设置DATABASE_URL为空。

| 最终测试文件 | 结果 | 用时 |
|---|---|---|
| `test_project_model_removal_history.py` | 15通过，0跳过 | 14.483秒 |
| `test_project_model_inventory.py` | 20通过，0跳过 | 49.945秒 |
| `test_project_scenes.py` | 21通过，0跳过 | 56.164秒 |
| `test_resource_lifecycle.py` | 28通过，1跳过 | 37.381秒 |
| `test_database.py` | 7通过，0跳过 | 2.273秒 |

- 最终合计91通过、1跳过；跳过为SQLite变体不支持PostgreSQL行锁的并发用例，对应PostgreSQL变体已执行。不重复累计中间复测次数。
- 新增覆盖：内存真实API创建两场景→只删一个仍409→全删可移除；SQLite/PG历史重开持久化、原身份与方案保留、重新添加、部分删除不发生部分脱钩、停用/未审批阻塞、启用流保护、权限/修订/跨项目边界、审计回滚、外键/CHECK约束、Android移除不影响PC分配；迁移前后schema门禁、历史数据保持及拒绝降级。
- 定向`git diff --check`通过，有既存CRLF转换提示。Harness完成校验结果见本节末尾。

### 中间失败与复测事实

- 初次新增套件13项：1错误、6跳过。测试迁移夹具中的JSON字符串`{"revision":3}`被SQLAlchemy text识别成绑定参数；修正测试字面量空格后，非PG复测7通过、6跳过。启用隔离PG后13/13通过（28.621秒）。
- 首次生命周期回归29项：5错误、1跳过（54.900秒）。原持久化夹具未适配平台统一参数发布前置；只为临时合成helmet/ppe发布参数，未发布业务模型参数。最终复测28通过、1跳过。
- 新增Android目标端用例后首次15项：2错误（15.220秒），合成目录未声明Android ready；按既有ModelApiFixture补齐测试夹具标志后最终15/15通过。
- 保留Starlette/httpx及SQLite日期适配的弃用警告事实；未将环境警告、跳过或前次失败改写为通过。复现均使用上述测试命令，前置为对应中间夹具状态。

### 用户追问的代码核验（Android只读）

- 项目“移除模型”只移除本项目精确版本/目标端的分配；其他项目不应阻止该操作。仍被本项目场景引用时应说明阻塞场景，本次已补名称；平台“卸载模型版本”则检查跨项目分配、场景/方案、流及活动槽位，目前`app/model_removal.py`影响接口返回数量，不是项目名称明细列表，本次未新增跨项目依赖面板。
- Android现有`ResourceLifecyclePresentation.kt`显示“云端已移除 · 本地文件保留”；`MainActivity.kt`从可用列表排除被拒绝场景，保留本地资源状态说明，收到失效事实时停止受影响识别。场景目录刷新和生命周期对账是异步链路，离线、后台或同步异常不保证立即看到云端删除。
- `ResourceLifecycleCleanup.kt`只有用户明确确认后才创建清理操作；本地下载管理核对共享引用、实际运行占用和可回收空间。其他场景/账号/项目仍引用的共享文件及历史告警、证据不因云端删除被自动删除。不是简单“过期后仍能继续用”，也不是云端删除即自动清空手机文件。
- 每版本首次资源校验与运行授权是两件事；跳过重复准备弹窗不意味着永久授权。现有场景运行仍需在线核验。Android仅完成源码核验及Harness validate/status；没有改任务状态、构建安装APK或真机测试。M112联合验收仍blocked，M176/M196/M197人工项仍pending，不据源码核验宣称真机闭环通过。

### 发布边界与遗留风险

- 修复目前只在本地源码。业务环境需要先核对现有Alembic版本与备份，批准后执行相应结构迁移，再使用新代码启动/重启后端；仅重启旧代码不能修复，新代码配旧schema会被启动校验拒绝。旧版本跨多次迁移不得未经审查盲目upgrade head（此前历史迁移含旧数据清理）。Docker/K8s同样须按Git优先流程另行授权发布和迁移。
- 未执行真实Default Project的DELETE、线上端到端、Docker/K8s部署或手机场景删除联调；权限/事务/迁移仅在隔离测试验证。平台跨项目引用名称明细及后台新依赖列表未实现，不包含在本修复范围。
- 临时实例核验后已停止：SQL确认data_directory与55481端口一致，无额外测试schema、无其他客户端连接；`pg_ctl -D <本次精确data目录> -m fast -w stop`成功，55481无监听、postmaster.pid不存在。报告已回读；再次核验精确绝对目录及内部路径、无链接、文件数量/大小后，逐项永久删除本次临时数据库及日志，共1012文件、202354664字节，目录已不存在。这些临时诊断材料不能恢复；源码、业务库、既有证据、模型、安装包、签名和发布产物均未清理。
- Harness通过CLI完成M36-T35，记录`harness/records/M36/M36-T35.md`；随后`validate`和`render`均成功。未改Harness实现/测试，因此未重复执行Harness单元测试；未执行大任务验收或将历史报告头部状态作为本轮生产放行。

## 2026-11-17 M36-T34 删除场景入口移至列表

### 范围、版本与环境

- L1，局部前端入口调整：将“删除场景”从详情弹窗移到列表每行操作栏末尾，沿用红色危险操作样式；操作列最小宽度204调整为280，避免新增按钮挤压。详情内不重复保留入口。
- 保留 `project.scenes.manage` 权限、busy/needsReload禁用、影响预览、修订核对、勾选确认和幂等删除流程。未改变后端软删除语义，也未修复“已删除场景历史引用阻止项目移除模型”的独立问题。
- 基础提交 `4e9faf48dbd4800f7af7d09599337ec2d872840d`，工作树已有大量未提交变更，本次保留原有修改，仅追加本任务变更。未commit/push、未部署、未重启用户服务、未删除真实业务场景。
- Windows/PowerShell，Node v24.19.0，Python 3.13.15，Chrome 157.0.8103.52；日期按Asia/Shanghai。采用frontend-design技能维持现有界面与确认交互，不引入整体重设计。

### 实际验证与结果

在 `server-video-service/admin-web` 执行：

- `npm run test -- tests/scenes.test.ts --maxWorkers=2`：30/30通过，4.99秒。覆盖列表入口、详情无重复按钮、无权限隐藏、影响预览后才能确认、精确场景/修订提交与成功刷新；新增请求中禁用和陈旧修订拒绝用例。
- `npm run build`：vue-tsc与正式Vite构建通过，3634模块，Vite 626ms；`npm run build:preview`：vue-tsc与预览构建通过，3634模块，Vite 638ms。分别更新本地 `dist` 和 `dist-preview`。
- 设置 `PLAYWRIGHT_CHROMIUM_EXECUTABLE=C:/Program Files/Google/Chrome/Application/chrome.exe`、`DATABASE_URL`为空、`PYTHONDONTWRITEBYTECODE=1` 后执行 `npm run test:e2e:production -- scene-list.spec.ts --workers 1 --output ../.tmp/m36-t34-scene-list-20261117`：2/2通过，12.4秒。
- 浏览器使用本地4174隔离服务、真实临时账号登录及拦截的场景列表/删除影响响应，无业务数据库连接。1366×768与390×768均能从固定操作栏直接打开删除确认，未勾选禁用/勾选启用/取消不删除；详情中无删除入口；场景业务写请求为0，不据此宣称真实DELETE端到端通过。
- 20条场景每行约58.28px，行高差≤2px；桌面首屏6条完整记录、窄屏5条，操作居中偏差≤2px；页面无横向溢出，固定删除按钮在视口内。桌面和窄屏列表截图已实际查看，长名称详情无横向溢出。
- `git diff --check`（本次产品及测试文件）通过。Harness启动validate/status/next、M36-T34 add/show/start/complete均成功，完成后validate/render通过，记录为 `harness/records/M36/M36-T34.md`。

### 警告、未验证与留存

- 本轮无失败测试。npm已有home/sass配置警告；浏览器结束连接时隔离Python服务输出一次Windows `ConnectionResetError [WinError 10054]`，2项浏览器断言均通过，测试服务已停止且4174无监听。不把该诊断记为真实业务服务故障或隐藏该警告。
- `resource-lifecycle.spec.ts`仅同步列表按钮的精确可访问名称，未执行其真实删除用例；后端、数据库、Android和Docker/K8s部署未验证。本任务不需重启后端；本地静态前端刷新可加载新构建，远程环境仍需另行发布。
- 临时截图/结果仅属于 `.tmp/m36-t34-scene-list-20261117`：4张PNG和1个.last-run.json，共5文件429987字节。测试进程已结束，报告回读后核验绝对路径、文件类型、数量/大小及无链接，已精确永久删除并确认路径不存在；这些临时材料不能恢复。保留本报告、测试源、构建产物及Harness元数据。

## 2026-11-17 M36-T33 项目查看平台参数状态修复

### 任务与范围

- L2，修复项目模型“查看平台参数”把尚未发布与模型不可用统一显示为 `published project parameters not found` 的缺陷，以及清单把未发布显示成 r0 的问题。不调整参数归属、写权限、发布策略或运行门禁。
- 已分配且目标端可用的精确模型版本：无平台发布返回409 / `platform_parameters_unpublished`；其他参数配置异常返回503；未分配、停用、目标端不可用仍按原权限/404边界处理。已发布参数仍只读最新发布快照，不回退草稿或历史项目快照。
- 弹窗复用现有UiStatePanel和样式，显示中文“平台参数尚未发布”、模型版本、Android/服务端及平台发布步骤；允许重新读取。列表依据已有 `parameterPublished` 区分未发布和合法的已发布r0。
- 使用frontend-design技能保持既有视觉体系和可操作的空状态，不重设计页面。修正浏览器隔离夹具为合成资产显式发布参数，仅写其TemporaryDirectory。

### 版本与环境

- 基础提交 `4e9faf48dbd4800f7af7d09599337ec2d872840d`；工作树dirty，保留既有大量未提交/未跟踪文件。本次未commit/push、未部署、未重启用户服务、未读写业务数据库或自动发布业务参数。
- Windows/PowerShell；Python 3.13.15（项目.venv），Node v24.19.0，Chrome 157.0.8103.52；浏览器1440×960与390×960。日期按Asia/Shanghai为2026-11-17。
- 后端测试显式设置DATABASE_URL为空和PYTHONDONTWRITEBYTECODE=1；内存/临时文件/SQLite夹具，无真实PG连接。页面测试使用生产前端构建和拦截的API响应，仅验证UI/请求路径，不替代真实环境端到端验收。

### 实际命令与结果

在server-video-service运行：

- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_platform_model_parameter_api.py -v`：5/5通过，19.911秒。覆盖旧清单无发布、草稿不生效、错误版本发布不串用、发布后恢复、PC/Android目标端、普通成员只读、跨项目/撤权保护、配置异常不冒充未发布；既有运行快照用例保留。
- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_model_parameters_api.py -b`：7/7通过，1.235秒。
- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_platform_model_parameters.py -b`：19项，11通过、8个PG条件跳过，5.162秒。
- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_project_model_inventory.py -b`：20项，12通过、8个PG条件跳过，29.536秒。
- `.venv/Scripts/python.exe -m unittest discover -s harness/tests -p 'test_*.py' -b`：34/34通过，0.116秒。Harness validate、定向git diff --check通过（已有CRLF转换提示）。

在admin-web运行：

- `npm run test -- tests/category-parameters.test.ts tests/assignment-targets.test.ts tests/models.test.ts tests/scenes.test.ts --maxWorkers=2`：4文件55/55通过，7.83秒。覆盖未发布到已发布重读、只读无写请求、网络/权限错误不误判、双端列表未发布与合法r0区分。
- `npm run build`：vue-tsc与Vite生产构建通过，3634模块，Vite 2.17秒。保留npm原有home/sass配置警告。
- 设置PLAYWRIGHT_CHROMIUM_EXECUTABLE为本机Chrome，运行 `npm run test:e2e:production -- platform-parameter-state.spec.ts --workers 1 --output ../.tmp/m36-t33-browser-verified-20261117`：最终2/2通过，7.8秒。1440和390宽度下模型清单→弹窗→未发布提示→重读已发布参数只读；精确版本/Android请求路径正确、零写请求、无页面横向溢出。390截图已实际查看，文案/关闭/重读按钮可见。

### 失败与复现记录

- 初次前端24项通过，但vue-tsc因新增测试使用联合类型的spyOn报TS2769/TS2345；拆分为具体API spy后，最终55项、类型检查、构建通过。
- 曾误以test_project_model_assignments.py夹具模块作为测试目标：0测试、退出5，未记通过；改跑实际test_project_model_inventory.py。
- 首次浏览器启动0项执行：旧共享夹具未发布参数，ModelParameterError阻止分配。补齐临时合成资产发布后再测。
- 随后两轮各2项超时，均停在进入项目之前：测试PROJECT_OWNER数据membershipRevision为null，触发现有项目协议保护；补齐session字段未解决该成员修订问题，最终将membershipRevision设为1后2/2通过。没有修改产品权限校验来放行无效夹具。
- 后端夹具有apk_worker_iteration_failed和合成PT不可加载诊断；测试结果不代表真实模型推理成功。所有执行过的跳过、失败事实保留，不用最终通过覆盖。

### 未验证与交付边界

- 用户截图的实际服务地址、部署版本和该helmet精确版本的平台发布记录未查询，不能仅凭截图断言业务库一定未发布。已确认本地同错误分支并复现其未发布情况。
- 模型文件“已发布”与运行参数“已发布”是两步；平台管理员需在相同modelId/文件版本/Android目标端核对并明确发布。本次不自动提升旧项目参数、不删除数据、不改模型文件。
- PostgreSQL集成、真实业务服务、设备/推理、生产部署未执行；新前端与本次后端需配套。M36整体/Android人工验收不因本次局部修复自动完成。
- 临时浏览器诊断归属仅四个本次目录：`.tmp/m36-t33-browser-20261117`、`.tmp/m36-t33-browser-retry-20261117`、`.tmp/m36-t33-browser-final-20261117`、`.tmp/m36-t33-browser-verified-20261117`。运行已结束、4174无监听且无测试服务Python进程；报告回读后核对绝对路径、无链接和文件类型并精确清理。四目录分别删除1/5/5/3个文件、45/316807/300905/101867字节，总计14文件719624字节；删除后路径均不存在，永久删除不可恢复。保留本报告、测试源、完成元数据及构建产物，不清理未知历史材料。

## 验收结论

**通过**

第一阶段模型端能力与项目场景配置验收通过；19/19子任务完成，真实本机服务单成员运行授权的开始、续期、心跳、令牌轮换、停止撤权、旧令牌重放与跨账号拒绝均通过。多成员推理调度仍不在本阶段验收范围。

## 验收标准

- [x] 模型发布按PC、移动端或双端能力独立标记；目标端产物分别校验，缺少非目标端产物不阻止发布或使用，Android转换不再是模型发布前置条件
- [x] 场景作为项目可管理的业务配置独立于模型分类；有权限的用户可创建和编辑场景及其模型成员关系，服务端强制校验项目和场景能力
- [x] 场景可配置一个或多个已发布模型并声明图片/视频输入适用性；本阶段只交付配置、授权、目录展示与兼容消费，不宣称已支持多模型运行编排
- [x] 既有modelId/version、产物签名/哈希、参数快照、项目隔离和图片/相机既有运行行为保持兼容；服务端、PC管理后台、Android契约测试及Harness门禁通过

## 小任务完成记录

| ID | 小任务 | 状态 | 记录 |
|---|---|---|---|
| M36-T01 | 冻结模型目标端能力与场景配置跨端契约 | completed | [M36-T01.md](../records/M36/M36-T01.md) |
| M36-T02 | 实现按目标端独立校验的模型就绪与发布规则 | completed | [M36-T02.md](../records/M36/M36-T02.md) |
| M36-T03 | 建立项目场景及多模型成员关系 API 与存储 | completed | [M36-T03.md](../records/M36/M36-T03.md) |
| M36-T04 | 实现项目场景授权和目标端可用目录 | completed | [M36-T04.md](../records/M36/M36-T04.md) |
| M36-T05 | 建设PC模型资产与项目场景管理界面 | completed | [M36-T05.md](../records/M36/M36-T05.md) |
| M36-T06 | 完成模型能力与场景配置跨项目自动化验收 | completed | [M36-T06.md](../records/M36/M36-T06.md) |
| M36-T07 | 为已登记 PC 模型补充运行验证与发布入口 | completed | [M36-T07.md](../records/M36/M36-T07.md) |
| M36-T08 | 支持项目模型双端独立分配与按端场景执行判定 | completed | [M36-T08.md](../records/M36/M36-T08.md) |
| M36-T09 | 更新本机8080开发服务并验证双端分配接口 | completed | [M36-T09.md](../records/M36/M36-T09.md) |
| M36-T10 | 补齐项目场景审批参数快照与修订绑定执行契约 | completed | [M36-T10.md](../records/M36/M36-T10.md) |
| M36-T11 | 更新本地场景服务并发布获授权的双测试版本 | completed | [M36-T11.md](../records/M36/M36-T11.md) |
| M36-T12 | 冻结场景套件成员与运行方案v2跨端契约 | completed | [M36-T12.md](../records/M36/M36-T12.md) |
| M36-T13 | 实现套件混合输入成员及运行方案持久化迁移 | completed | [M36-T13.md](../records/M36/M36-T13.md) |
| M36-T14 | 提供套件安装授权与单成员方案修订绑定运行接口 | completed | [M36-T14.md](../records/M36/M36-T14.md) |
| M36-T15 | 扩展管理后台套件成员输入与方案编辑审批 | completed | [M36-T15.md](../records/M36/M36-T15.md) |
| M36-T16 | 完成套件混合输入与单成员方案真实服务联合验收 | completed | [M36-T16.md](../records/M36/M36-T16.md) |
| M36-T17 | 支持多模型方案冻结参数与客户端能力协商授权 | completed | [M36-T17.md](../records/M36/M36-T17.md) |
| M36-T18 | 补齐联合识别方案后台配置与真实授权回归 | completed | [M36-T18.md](../records/M36/M36-T18.md) |
| M36-T19 | 颁发可续期且可撤权的单成员套件运行授权 | completed | [M36-T19.md](../records/M36/M36-T19.md) |

## 测试结果

- Harness单元测试：34项通过
- Harness validate：通过
- Harness render：通过
- M36-T19隔离PostgreSQL回归：记录为90个HTTP请求通过、PostgreSQL回归exit code 0
- 本机127.0.0.1:8080服务链接：14个API请求；单成员运行授权及撤权用例通过

## 验收证据

- harness/records/M36/M36-T19.md
- harness/records/M36/M36-T18.md
- harness/evidence/M36/M36-T16-acceptance.md
- harness/evidence/M36/M36-T18-live-postgres-http.json
- harness/evidence/M36/M36-T19-postgres-regression.json
- harness/evidence/M36/M36-T19-service-links-final-20261021-211259/result.json
- harness/evidence/M36/M36-T19-service-links-final-20261021-211259/api-trace.json

## 遗留风险

- 无；若存在遗留风险，必须在正式通过前改写本节并给出责任人和截止日期。

## 2026-11-16 平台统一模型参数修订（M36-T29～T32）

本节是新增范围的唯一测试报告；上文历史验收不代表本次范围已经通过。

- 范围：平台参数草稿/显式发布；退役项目和场景覆盖；项目授权与场景方案保留；新运行用最新发布，运行中冻结快照。
- 版本：HEAD `4e9faf48dbd4800f7af7d09599337ec2d872840d`，含既有及本次未提交改动；未提交、未部署、未迁移业务库。
- 环境：Windows、项目 Python 3.13、临时文件及 SQLite；PostgreSQL/真实模型/手机端尚未验证。
- M36-T29：新增8项文件/SQLite发布测试通过，原有参数存储6项回归通过。命令：`.venv/Scripts/python.exe -m unittest discover -s tests -p test_platform_model_parameters.py -v`；同命令以`test_model_parameters.py`运行原有回归。
- 首次沙箱运行失败：临时目录创建后访问被拒绝（8项共16个测试/清理错误），未证明业务失败。沙箱外复测上述14项通过。首轮临时目录清理失败，保留该事实，不扫描删除用途未知路径。
- 验证：草稿不生效、首次发布门禁、发布CAS、项目写拒绝、双项目一致、目标端/版本隔离、重置不改发布、存储重开及旧快照不变。
- 遗留：T30～T32及App M196尚未完成；跨端/API/PG及真实设备流程未验证，不作为交付完成。

### M36-T30 运行与更新来源

- 验证级别 L3；本步骤为服务端契约/SQLite回归，PG在T32，Android检查在M196执行。
- 实现：项目与场景写参数接口410；平台发布影响所有引用项目的新运行；授权清单不固定参数修订；场景审批仅控制方案。服务器运行保存启动快照，移动端场景续租保留旧参数摘要；模型、项目、成员、场景撤权仍核验。更新投影按最新平台参数生成摘要，权重哈希保持不变。
- 命令：项目Python运行unittest套件（通过`-c`关闭请求日志，`sys.path.insert(0,'tests')`，TextTestRunner），模块为`test_platform_model_parameters`、`test_project_model_assignment_storage`、`test_scene_execution_parameters`、`test_scene_snapshot_approval`、`test_scene_composite_runtime_grants`、`test_model_update_projection`。174项：121通过、52跳过、1旧续租参数断言失败；该断言已按新设计替换，定向复测通过。跳过项为隔离PG及相关条件检查，不能视为通过。
- 第二套件：`test_platform_model_parameter_api`、`test_project_model_inventory`、`test_stream_model_binding`、`test_model_parameters_api`共31项：22通过、8跳过、1旧继承元数据断言错误；修复后定向复测通过。
- 最终定向套件16项覆盖平台权限/跨项目、清单元数据、服务器配置持久化、参数单独发布更新投影、结构变化撤销续租：15通过，1清理断言错误（DELETE实际204、测试预期200）。改为204后服务器启动快照用例复测1项通过。业务断言均通过，未隐去首轮失败。
- 最初场景21项回归曾因旧来源字段失败1项；替换后相同基础场景测试在后续套件中通过。旧项目/场景快照被保留且不参与当前参数授权；数据库重开验证通过。
- 测试使用临时文件和SQLite并由测试清理，未修改业务数据库；未运行真实模型推理、PG或真实设备验收。后台与Android当前尚未接入，整体不可部署。

### M36-T31 管理后台

- 平台可保存/重置草稿并单独确认发布；未保存编辑时禁用发布，显示当前发布修订。项目和场景参数弹窗强制只读，即使用户有项目管理权限也无写入口。删除场景覆盖保存客户端、参数同步/重新批准入口；项目分配和场景成员请求不再固定参数修订。
- `npm run test -- tests/category-parameters.test.ts tests/scenes.test.ts tests/assignment-targets.test.ts tests/project-business.test.ts --reporter=dot`：最终42/42通过，覆盖草稿保存/显式发布/只读、场景方案和模型清单。
- `npm run build`：vue-tsc类型检查与Vite生产构建通过。构建产物仅用于本地验证，未发布。
- 首轮类型检查发现已删除的memberNeedsRefresh引用和旧测试saveProfile/parameterRevision类型；首轮42项中16失败并报告13个未处理异常。清除残余引用、更新旧流程测试后复测通过；只读文案测试曾误把“平台发布参数”当作发布按钮，已改为验证按钮与实际写调用。
- 沿用现有界面样式；本步骤未执行真实浏览器/设备联调。整体仍待T32及M196验证。

### M36-T32 汇总与边界

- L3服务端验证：隔离PG最终60/60通过（无跳过），涵盖独立发布进程CAS、事务内平台撤权、审计回滚、旧覆盖差异与历史保持、场景事务、运行令牌、设备参数更新。下方三次运行保留首轮fixture重复默认项目/共享参数及第二轮旧空参数断言失败事实，最终复测通过。
- 后台全量`npm run test -- --reporter=dot`：37文件335项通过。代理测试输出预期socket hang up诊断，最终无失败；不代表真实浏览器验收。清理旧参数辅助方法后`test_platform_model_parameters`文件/SQLite复测19项，11通过、8个PG类跳过（PG已另行实测）。
- 差异工具仅SELECT，必须显式提供环境变量名；不会使用.env默认连接、自动发布、清空或改写业务库。当前未对业务库运行。旧PROJECT行、清单/场景历史快照、审计及告警不删除。
- 现行规则写入PRODUCT_REQUIREMENTS、项目清单/场景/授权协议和docs/platform-model-parameters.md。旧覆盖辅助方法、写回调、场景参数写客户端及后台入口已清理；服务端旧写路径保留410退役响应，历史schema保留用于审计。
- 所有本次隔离PG进程均已停止、端口关闭、schema清空；各次临时PG数据和日志在MD写入回读后清理，不能恢复原日志，失败摘要保留。未处理此前用途未知目录。
- 剩余交付条件：Android M196接口适配与L3检查、人工端到端确认；尚未提交/推送/部署、未运行真实模型推理或业务数据迁移。首次上线需管理员核对差异并明确发布每个在用版本/目标端参数。

### M36-T32 隔离PG运行 platform-parameters-pg-kfn_fny8

- 时间：2026-11-16T08:16:56.223644+00:00；版本：{'commit': '4e9faf48dbd4800f7af7d09599337ec2d872840d', 'workingTree': '有未提交/未跟踪变更', 'environment': 'Windows-11-10.0.26200-SP0; Python 3.13.15'}
- 命令：`.venv/Scripts/python.exe tools/accept_platform_model_parameters.py`。仅临时PG实例，无业务数据库连接。
- 范围：['test_platform_model_parameters', 'test_project_model_assignment_storage', 'test_scene_execution_parameters.SceneParameterPostgresTests', 'test_scene_snapshot_approval.SceneSnapshotApprovalPostgresTests', 'test_model_update_projection.UpdateProjectionPostgreSqlTests']
- 结果：passed=False；汇总：{'ran': 58, 'seconds': '97.842', 'terminal': 'FAILED (errors=21)', 'counts': {'failures': 0, 'errors': 21, 'skipped': 0, 'expected failures': 0, 'unexpected successes': 0}, 'failures': ['ERROR: test_assignment_cannot_pin_old_or_forged_parameter_revision (test_project_model_assignment_storage.AssignmentPostgreSqlTests.test_assignment_cannot_pin_old_or_forged_parameter_revision) ', 'ERROR: test_independent_assignment_stores_serialize_first_insert_and_update (test_project_model_assignment_storage.AssignmentPostgreSqlTests.test_independent_assignment_stores_serialize_first_insert_and_update) ', 'ERROR: test_migration_legacy_disabled_and_pinned_data_blocks_downgrade (test_project_model_assignment_storage.AssignmentPostgreSqlTests.test_migration_legacy_disabled_and_pinned_data_blocks_downgrade) ', 'ERROR: test_persisted_snapshots_versions_cas_and_project_isolation (test_project_model_assignment_storage.AssignmentPostgreSqlTests.test_persisted_snapshots_versions_cas_and_project_isolation) ', 'ERROR: test_approval_persists_audit_and_rechecks_membership_inside_transaction (test_scene_execution_parameters.SceneParameterPostgresTests.test_approval_persists_audit_and_rechecks_membership_inside_transaction) ', 'ERROR: test_approved_multimember_plan_parameter_sources_persist_after_reopen (test_scene_execution_parameters.SceneParameterPostgresTests.test_approved_multimember_plan_parameter_sources_persist_after_reopen) ', 'ERROR: test_audit_failure_rolls_back_scene_and_members_and_inactive_guard (test_scene_execution_parameters.SceneParameterPostgresTests.test_audit_failure_rolls_back_scene_and_members_and_inactive_guard) ', 'ERROR: test_concurrent_inherited_platform_edit_does_not_change_inventory_snapshot (test_scene_execution_parameters.SceneParameterPostgresTests.test_concurrent_inherited_platform_edit_does_not_change_inventory_snapshot) ', 'ERROR: test_concurrent_parameter_edit_does_not_change_inventory_snapshot_approval (test_scene_execution_parameters.SceneParameterPostgresTests.test_concurrent_parameter_edit_does_not_change_inventory_snapshot_approval) ', 'ERROR: test_new_scene_audit_failure_leaves_no_partial_data (test_scene_execution_parameters.SceneParameterPostgresTests.test_new_scene_audit_failure_leaves_no_partial_data) ', 'ERROR: test_platform_publication_survives_reopen_without_mutating_scene_history (test_scene_execution_parameters.SceneParameterPostgresTests.test_platform_publication_survives_reopen_without_mutating_scene_history) ', 'ERROR: test_postgres_runtime_grant_cannot_be_consumed_twice_concurrently (test_scene_execution_parameters.SceneParameterPostgresTests.test_postgres_runtime_grant_cannot_be_consumed_twice_concurrently) ', 'ERROR: test_project_parameter_writer_rejected_even_with_internal_context (test_scene_execution_parameters.SceneParameterPostgresTests.test_project_parameter_writer_rejected_even_with_internal_context) ', 'ERROR: test_reopen_order_replace_isolation_and_revision (test_scene_execution_parameters.SceneParameterPostgresTests.test_reopen_order_replace_isolation_and_revision) ', 'ERROR: test_runtime_grant_digest_persists_and_is_atomically_consumed (test_scene_execution_parameters.SceneParameterPostgresTests.test_runtime_grant_digest_persists_and_is_atomically_consumed) ', 'ERROR: test_snapshot_persists_reopens_does_not_drift_and_audit_rollback (test_scene_execution_parameters.SceneParameterPostgresTests.test_snapshot_persists_reopens_does_not_drift_and_audit_rollback) ', 'ERROR: test_approval_persists_audit_and_rechecks_membership_inside_transaction (test_scene_snapshot_approval.SceneSnapshotApprovalPostgresTests.test_approval_persists_audit_and_rechecks_membership_inside_transaction) ', 'ERROR: test_audit_failure_rolls_back_scene_and_members_and_inactive_guard (test_scene_snapshot_approval.SceneSnapshotApprovalPostgresTests.test_audit_failure_rolls_back_scene_and_members_and_inactive_guard) ', 'ERROR: test_database_legacy_snapshot_is_preserved_but_not_executed (test_scene_snapshot_approval.SceneSnapshotApprovalPostgresTests.test_database_legacy_snapshot_is_preserved_but_not_executed) ', 'ERROR: test_new_scene_audit_failure_leaves_no_partial_data (test_scene_snapshot_approval.SceneSnapshotApprovalPostgresTests.test_new_scene_audit_failure_leaves_no_partial_data) ', 'ERROR: test_reopen_order_replace_isolation_and_revision (test_scene_snapshot_approval.SceneSnapshotApprovalPostgresTests.test_reopen_order_replace_isolation_and_revision) '], 'causes': ['sqlalchemy.exc.IntegrityError: (psycopg.errors.UniqueViolation) duplicate key value violates unique constraint "projects_pkey" ', 'sqlalchemy.exc.IntegrityError: (psycopg.errors.UniqueViolation) duplicate key value violates unique constraint "projects_pkey" ', 'sqlalchemy.exc.IntegrityError: (psycopg.errors.UniqueViolation) duplicate key value violates unique constraint "projects_pkey" ', 'sqlalchemy.exc.IntegrityError: (psycopg.errors.UniqueViolation) duplicate key value violates unique constraint "projects_pkey" ', 'sqlalchemy.exc.IntegrityError: (psycopg.errors.UniqueViolation) duplicate key value violates unique constraint "projects_pkey" ', 'sqlalchemy.exc.IntegrityError: (psycopg.errors.UniqueViolation) duplicate key value violates unique constraint "projects_pkey" ', 'sqlalchemy.exc.IntegrityError: (psycopg.errors.UniqueViolation) duplicate key value violates unique constraint "projects_pkey" ', 'sqlalchemy.exc.IntegrityError: (psycopg.errors.UniqueViolation) duplicate key value violates unique constraint "projects_pkey" ', 'sqlalchemy.exc.IntegrityError: (psycopg.errors.UniqueViolation) duplicate key value violates unique constraint "projects_pkey" ', 'sqlalchemy.exc.IntegrityError: (psycopg.errors.UniqueViolation) duplicate key value violates unique constraint "projects_pkey" ', 'sqlalchemy.exc.IntegrityError: (psycopg.errors.UniqueViolation) duplicate key value violates unique constraint "projects_pkey" ', 'FAILED (errors=21) '], 'skipReasons': [], 'sha256': '34b45440c0c0ed03406b356508f8637b2e0e109f3404312b5756afeea860a580', 'size': 147457}
- 资源：E:\aiyolo\server-video-service\.tmp\platform-parameters-pg-kfn_fny8\pg-data；端口=57730；停止=True；端口关闭=True；剩余schema=[]；异常=None
- 未验证：真实模型推理、Android设备及生产迁移。

- 本次临时PG数据与诊断日志已清理；MD保留失败事实及最终结果。

### M36-T51 两个移动端模型共用拍照/视频方案（2026-11-18）

- 范围：创建时保留两个成员和全部所选共同用途；不支持的目标端、数量或输入给出提示。只改管理前端和说明，未改业务 API、数据库或生产部署。服务端仓 `4e9faf4` 加本地未提交改动，Windows、Chrome 157。
- `npm run test -- tests/scenes.test.ts tests/scene-runtime-capabilities.test.ts tests/scene-automatic-plans.test.ts`：首次 90/91，一条旧文案断言失败；更新为检查 PC 和跨端仍不支持后，复测 91/91 通过。含仅图片、图片和视频、视频、无法共同支持的用途、同步和异步、原有方案与顺序。
- `npm run build`：类型检查与生产构建通过。`npm run test:e2e:production -- scene-create-simple.spec.ts --workers=1`：使用隔离内存夹具；第一次因环境变量 SQLite URL 被配置校验拒绝未启动；改用断开连接的 PostgreSQL 测试 URL 后，768/390/320 通过，1440 在 30 秒总时限超时；`--grep 1440 --timeout=60000` 单项复测通过。各视口一次保存一个含两个成员与两种用途的方案，取消不写入，无页面错误。
- 浏览器测试不证明手机模型精度或设备运行性能；App 自动化与人工验收分别由 M199-T01/T02 记录。管理端及 App 均未发布。

### M36-T32 隔离PG运行 platform-parameters-pg-4vpj849i

- 时间：2026-11-16T08:20:51.936103+00:00；版本：{'commit': '4e9faf48dbd4800f7af7d09599337ec2d872840d', 'workingTree': '有未提交/未跟踪变更', 'environment': 'Windows-11-10.0.26200-SP0; Python 3.13.15'}
- 命令：`.venv/Scripts/python.exe tools/accept_platform_model_parameters.py`。仅临时PG实例，无业务数据库连接。
- 范围：['test_platform_model_parameters', 'test_project_model_assignment_storage', 'test_scene_execution_parameters.SceneParameterPostgresTests', 'test_scene_snapshot_approval.SceneSnapshotApprovalPostgresTests', 'test_model_update_projection.UpdateProjectionPostgreSqlTests']
- 结果：passed=False；汇总：{'ran': 60, 'seconds': '71.789', 'terminal': 'FAILED (failures=1)', 'counts': {'failures': 1, 'errors': 0, 'skipped': 0, 'expected failures': 0, 'unexpected successes': 0}, 'failures': ['FAIL: test_concurrent_inherited_platform_edit_does_not_change_inventory_snapshot (test_scene_execution_parameters.SceneParameterPostgresTests.test_concurrent_inherited_platform_edit_does_not_change_inventory_snapshot) '], 'causes': ["AssertionError: {} != {'iouThreshold': 0.45, 'maxDetections': 100, 'confidenceThreshold': 0.35} ", 'FAILED (failures=1) '], 'skipReasons': [], 'sha256': 'f8e6def7d48e484739c961adb73eb92eebc493507ce353b5b9b55ab62bb6ddc2', 'size': 12728}
- 资源：E:\aiyolo\server-video-service\.tmp\platform-parameters-pg-4vpj849i\pg-data；端口=52778；停止=True；端口关闭=True；剩余schema=[]；异常=None
- 未验证：真实模型推理、Android设备及生产迁移。

- 本次临时PG数据与诊断日志已清理；MD保留失败事实及最终结果。

### M36-T32 隔离PG运行 platform-parameters-pg-u9spimq7

- 时间：2026-11-16T08:23:54.869419+00:00；版本：{'commit': '4e9faf48dbd4800f7af7d09599337ec2d872840d', 'workingTree': '有未提交/未跟踪变更', 'environment': 'Windows-11-10.0.26200-SP0; Python 3.13.15'}
- 命令：`.venv/Scripts/python.exe tools/accept_platform_model_parameters.py`。仅临时PG实例，无业务数据库连接。
- 范围：['test_platform_model_parameters', 'test_project_model_assignment_storage', 'test_scene_execution_parameters.SceneParameterPostgresTests', 'test_scene_snapshot_approval.SceneSnapshotApprovalPostgresTests', 'test_model_update_projection.UpdateProjectionPostgreSqlTests']
- 结果：passed=True；汇总：{'ran': 60, 'seconds': '130.124', 'terminal': 'OK', 'counts': {'failures': 0, 'errors': 0, 'skipped': 0, 'expected failures': 0, 'unexpected successes': 0}, 'failures': [], 'causes': [], 'skipReasons': [], 'sha256': '5832d314c5725652ab575ef584aacbaf21dc1dc18c0cd24d02c60d01fc04157d', 'size': 11860}
- 资源：E:\aiyolo\server-video-service\.tmp\platform-parameters-pg-u9spimq7\pg-data；端口=61655；停止=True；端口关闭=True；剩余schema=[]；异常=None
- 未验证：真实模型推理、Android设备及生产迁移。

- 本次临时PG数据与诊断日志已清理；MD保留失败事实及最终结果。
