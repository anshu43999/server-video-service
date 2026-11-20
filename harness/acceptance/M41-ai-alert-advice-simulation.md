---
major_task_id: M41
result: passed
owner: codex
accepted_at: 2026-11-16T15:25:41+08:00
---

# M41 管理后台 AI 告警处置建议模拟闭环测试验收报告

## 验收结论

**通过**

M41-T13本地清理验收通过：系统草稿与只读项目查询彻底分开，旧项目资料写仓储与运行时旧表依赖已移除；旧数据/迁移/历史来源和410兼容保留。未部署或变更业务数据库。

## 验收标准

- [x] 服务端集中管理按告警类型与识别分类精确匹配的模拟知识资料，支持版本、启停、权限和审计，不以模型名称或相似类别兜底
- [x] 告警详情由用户主动触发模拟建议，结构化区分处置步骤、可能相关制度原文、匹配说明和模拟来源，覆盖成功、无匹配、部分成功、失败与重试
- [x] 生成记录保存知识版本及引用快照；建议不自动认定违规、不改变告警处置、不额外上传媒体、不调用真实外部知识库或大模型
- [x] 管理页面、服务接口、项目隔离、角色权限、审计、数据库迁移及自动化浏览器回归通过，并为后续真实检索器和生成器保留可替换边界

## 小任务完成记录

| ID | 小任务 | 状态 | 记录 |
|---|---|---|---|
| M41-T01 | 冻结 AI 处置建议领域模型与接口契约 | completed | [M41-T01.md](../records/M41/M41-T01.md) |
| M41-T02 | 建立模拟知识资料持久化与版本审计 | completed | [M41-T02.md](../records/M41/M41-T02.md) |
| M41-T03 | 实现模拟知识资料管理 API | completed | [M41-T03.md](../records/M41/M41-T03.md) |
| M41-T04 | 实现可替换的模拟检索与建议生成服务 | completed | [M41-T04.md](../records/M41/M41-T04.md) |
| M41-T05 | 实现告警建议生成 API 与历史结果快照 | completed | [M41-T05.md](../records/M41/M41-T05.md) |
| M41-T06 | 开发管理后台模拟知识资料管理页面 | completed | [M41-T06.md](../records/M41/M41-T06.md) |
| M41-T07 | 在后台告警详情接入 AI 处置建议交互 | completed | [M41-T07.md](../records/M41/M41-T07.md) |
| M41-T08 | 加固项目权限、审计与安全边界 | completed | [M41-T08.md](../records/M41/M41-T08.md) |
| M41-T09 | 完成管理后台模拟闭环浏览器与服务验收 | completed | [M41-T09.md](../records/M41/M41-T09.md) |
| M41-T10 | 冻结移动端后续服务化接入方案 | completed | [M41-T10.md](../records/M41/M41-T10.md) |
| M41-T11 | 系统AI资料版本发布与项目继承覆盖 | completed | [M41-T11.md](../records/M41/M41-T11.md) |
| M41-T12 | 统一系统知识资料并移除项目维护与继承关系 | completed | [M41-T12.md](../records/M41/M41-T12.md) |
| M41-T13 | 清理项目知识旧仓储并解除历史表运行依赖 | completed | [M41-T13.md](../records/M41/M41-T13.md) |

## 测试结果

- 服务端L3范围回归及真实隔离PostgreSQL两种场景通过：历史保留、无旧表也能运行
- 前端14项定向测试、类型检查和生产构建通过；本轮浏览器、Android和生产联调未执行

## 验收证据

- harness/records/M41/M41-T13.md
- docs/ai-alert-advice-api-v1.md

## 遗留风险

- 未部署，真实业务库及生产联调未验证；历史兼容层按明确范围保留，Android视觉仍由M195另行确认。


## 2026-11-16 M41-T13 旧逻辑清理验证

### 范围与版本

- 验证级别L3（服务端存储与启动依赖），任务M41-T13。系统草稿独立为SystemKnowledgeDraft，项目读取器必须显式绑定系统库，不再包含数据库访问、项目CRUD、local_list、ensure_mock_seed或隐式本地回退。
- 删除废弃项目维护权限常量及导入、前端baseRevision/INHERIT；前端读API和写API分开创建，项目客户端不再创建写方法。旧模拟种子仅测试使用，已移入tests/knowledge_support.py。
- 旧项目资料表、修订表、版本绑定表退出数据库启动必需表清单。ORM映射与所有已执行迁移保留；未新增删表迁移，未连接或删除业务库中的任何资料。旧写接口410、GET base兼容元数据、历史PROJECT/PROJECT_OVERRIDE来源及既有建议快照保留。
- Git HEAD：4e9faf48dbd4800f7af7d09599337ec2d872840d，工作区含前次及既有未提交/未跟踪变更；未commit/push。Windows，Python3.13.15，Node24.22.1，隔离PostgreSQL17.11。实际执行日期2026-11-16。
- 本次不修改Android、UI布局或业务接口形状，不安装设备、不部署、不更改.env或开发数据库。

### 实际验证与结果

普通后端命令在server-video-service设置DATABASE_URL为空、PYTHONDONTWRITEBYTECODE=1，使用`.venv/Scripts/python.exe -m unittest discover -s tests -p <pattern> -b`。
- `test_alert_advice*.py`：最终28项，27通过、1隔离PG跳过。覆盖系统草稿校验、唯一键、CAS、快照深拷贝、只读API、权限/撤权、旧写410、检索生成与幂等历史。测试夹具移动后已完整复测。
- `test_system_alert_knowledge.py`：5项通过，最终夹具调整后复测通过。
- `test_database.py`：7项通过，新增“不存在旧项目知识三表仍schema ready，缺少系统目录仍unavailable”验证。
- `test_project_authorization.py`：11项通过；`test_ai_alert_advice_contract.py`：8项通过。
- `test_alert_advice_api.py`：补充平台审计断言后单独5项通过，再包含于最终28项回归中；系统创建、编辑、发布、启停各写一条平台审计，过期CAS不产生额外记录。
- admin-web使用显式bundled Node运行`node_modules/vue-tsc/bin/vue-tsc.js --noEmit`：通过；`node_modules/vitest/vitest.mjs run tests/advice-knowledge.test.ts tests/knowledge-view.test.ts tests/alert-advice-dialog.test.ts --maxWorkers=2`：3文件14项通过；`node_modules/vite/bin/vite.js build --mode production`：通过，3634模块。
- 隔离PG命令`.venv/Scripts/python.exe .tmp/m41-t13-pg-check.py`：两轮各2项通过，0跳过。最后一轮在种子函数/历史测试夹具移动后重跑，`test_system_alert_knowledge_postgresql.py`用时1.423秒，`test_alert_advice_knowledge_postgresql.py`用时1.213秒。
- PG覆盖：保留旧pin、停用私有资料及修订快照时仍查询最新系统发布；并发发布一次成功一次CAS冲突；新项目不建pin；重新创建仓储后历史发布及已保存建议保持原样。另在全新随机测试schema内移除旧项目三表，验证健康检查、草稿新增/编辑/启停、修订历史、CAS、发布和双项目查询均正常；这些测试删表只发生在一次性测试库。
- 隔离身份核验：目录分别为`.tmp/m41-t13-pg-6_xpydau/pg-data`（端口62205）与`.tmp/m41-t13-pg-tmghpyng/pg-data`（端口56279），角色aiyolo_app、数据库postgres、回环地址127.0.0.1，均核对SHOW data_directory及current_user。两轮剩余测试schema为空、停止退出0、端口关闭、PID文件移除。
- PG复现：用D:/PostgreSQL/bin/initdb.exe在新的.tmp专属目录初始化，显式`-U aiyolo_app --auth-local=trust --auth-host=trust --encoding=UTF8 --locale=C`；以新的空闲回环端口通过pg_ctl启动，核验身份后覆盖DATABASE_URL为该临时端口的postgres库、RUN_POSTGRES_TESTS=1，分别运行上述两个unittest模式。最后核验随机schema清理并停止这个精确实例。Windows启动输出写临时文件，避免继承输出管道。临时runner不是永久交付文件。
- 定向代码检索确认：产品中对旧项目三表的引用只剩database.py历史映射/外键定义；旧仓储方法、权限常量及前端废弃类型无运行代码残留。git diff确认alembic目录无改动；diff --check与Harness validate通过。

### 失败、跳过及未验证

本轮无测试失败。非PG回归的1项跳过是未启用隔离PG环境的预期行为，随后两项真实PG测试均执行通过。FastAPI测试仍提示httpx弃用警告，不影响结果，未为此扩大依赖修改。
未执行全量后端/前端回归、浏览器端到端、Android测试或真实业务库升级；本次无UI/Android变化，未将前次333项或浏览器结果冒充本轮执行。当前服务未部署，旧版本服务行为不会自动改变。仍保留明确的历史兼容层，不能描述为删除了所有旧表、历史来源或旧接口地址。

### 临时材料

同份M41报告保留前次与本次结论。报告已回读，确认两轮临时实例已停止、端口关闭、PID移除后，已精确删除m41-t13-pg-6_xpydau、m41-t13-pg-tmghpyng两个本轮PG目录及临时runner。原始临时诊断材料不可恢复，测试结论保留；普通源码、历史证据、业务数据、模型及发布产物未清理。


## 2026-11-16 M41-T12 最终回归记录

### 范围、版本与环境

- M41-T12：只维护系统草稿及不可变发布版本，项目全角色只读使用最新发布；项目写接口410、角色不授予知识维护能力、新项目不建立知识版本绑定。旧项目资料/修订/绑定仅保留历史，不自动并入系统资料；既有建议快照不变。
- 验证级别：L3（服务端接口、权限和持久化范围），并不等于Android L3或生产交付。
- 服务端Git HEAD：4e9faf48dbd4800f7af7d09599337ec2d872840d；工作区原有且仍有未提交/未跟踪变更，本次未commit/push。所有结果基于当前工作区。
- Windows，Python 3.13.15（.venv），Node 24.22.1（Codex bundled runtime），PostgreSQL 17.11，Chrome 157.0.8103.52。运行时间2026-11-16。
- 未连接开发数据库，未修改.env，未重启已有服务，未部署。前端浏览器用生产dist+本地4174测试服务及模拟API；API权限另由真实FastAPI TestClient覆盖。

### 实际命令与结果

工作目录为server-video-service；普通后端测试显式设置DATABASE_URL为空及PYTHONDONTWRITEBYTECODE=1。
- `.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_alert_advice*.py' -b`：27项，26通过、1隔离PG跳过；后续新增知识撤权/登出测试后，`test_alert_advice_api.py`单独复测5项通过。覆盖全项目角色只读、旧写接口无知识/审计副作用、平台维护、CAS、发布、停用、鉴权、跨项目隔离、生命周期、历史/幂等。
- 同样命令分别指定`test_system_alert_knowledge.py`（5通过）、`test_project_authorization.py`（11通过）、`test_project_management_api.py`（8通过）、`test_ai_alert_advice_contract.py`（8通过；契约文档及JSON修改后再次8通过）。
- 隔离PG临时runner：`.venv/Scripts/python.exe .tmp/m41-t12-pg-runner.py`。最终2项通过、0跳过：`test_system_alert_knowledge_postgresql.py`与`test_alert_advice_knowledge_postgresql.py`。两项目共享发布、旧pin/私有停用不遮蔽、新项目无pin、并发发布一次成功一次CAS冲突、启停后发布生效、重开仓储可读、V1及旧建议数据库快照不变。
- PG复现方式：在新的专属.tmp目录使用`D:/PostgreSQL/bin/initdb.exe -D <目录>/pg-data -U aiyolo_app --auth-local=trust --auth-host=trust --encoding=UTF8 --locale=C`，以新空闲回环端口通过pg_ctl启动；核对SHOW data_directory及current_user；显式覆盖DATABASE_URL为该端口的postgres库、RUN_POSTGRES_TESTS=1，再分别运行上述两个unittest模式。输出重定向临时日志文件，避免Windows子进程继承管道。最后核验随机schema清空、停止精确实例并核验端口关闭。
- 最终PG实例目录`.tmp/m41-t12-pg-vx9m31ks/pg-data`、端口49186：身份核验通过，剩余测试schema为空，stop退出0、端口已关闭、PID文件已移除。
- admin-web中使用bundled Node：`npm run test -- --maxWorkers=2`，37文件/333项通过；仅来源冲突提示文案改动后定向`vitest run tests/advice-knowledge.test.ts tests/knowledge-view.test.ts --maxWorkers=2`再次8项通过。测试过程中出现两条socket hang up诊断，所有测试仍通过。
- `npm run typecheck`及`npm run build`通过。最终提示文案修改后直接使用bundled Node运行`vue-tsc --noEmit`和`vite build --mode production`再次通过（3634模块）。
- `node node_modules/@playwright/test/cli.js test --config playwright.production.config.ts alert-advice.spec.ts --grep 'production knowledge' --output ../.tmp/m41-t12-browser-retry --workers 1`，PLAYWRIGHT_CHROMIUM_EXECUTABLE指向本机Chrome：3项通过（1440px、390px项目只读，以及系统编辑/停用/草稿隔离/发布后项目更新），11.4秒，无横向溢出。项目写请求计数均为0。与知识无关的告警订阅401/WS4401属未模拟的测试服务请求，不据此宣称告警端到端验收。
- Harness validate通过；完成时再次validate/render。未修改Harness代码，未额外执行其单元测试。

### 初次失败与处理

- 默认Node过旧，Vitest因node:util缺少styleText启动失败；改用已安装Node24.22.1，未修改依赖版本。
- 首轮后端27项中2失败：TestClient保留登录cookie导致“匿名”请求实际已登录；旧generation fixture未配置system导致预期200实际503。清理cookie/改系统fixture并更新退役写接口断言后通过。
- PostgreSQL首次沙箱initdb失败（restricted token/目录拒绝），没有执行测试。授权后第二次启动遭遇pg_ctl输出管道超时；已停止精确临时实例64943，端口关闭。改临时输出到文件后运行正常。
- 第三次PG运行2项通过，但一个不存在的generation测试文件模式导致0测试/退出5，整轮未记通过。将真实PG快照断言补入system测试，修正列表后最终2项均通过。
- Playwright首次缺少对应版本headless shell，3项均未启动浏览器；使用已安装Chrome重跑3项通过，未下载/更改依赖。
- 最后一次复测shell找不到npm（该步未构建）；改显式Node可执行文件调用vue-tsc和vite后通过。

### 未验证与风险

- 未执行生产/开发实例升级、真实线上联调、实际业务数据迁移或部署。切换后项目私有资料不再用于新检索，保留行可供审计，不自动合并公开。
- 仍为模拟知识资料/模拟生成，无真实大模型或文档上传。
- 系统发布对后续服务端请求生效；Android原120秒成功/无匹配缓存不变，离线不会即时更新。
- 旧客户端项目写请求会收到明确410；应随本次后台版本交付。旧建议仍可能保留PROJECT/PROJECT_OVERRIDE来源，属历史事实。
- Android视觉本报告未验证；移动端来源文案另由其独立任务记录。

### 临时材料留存

本报告为M41范围唯一最终MD，保留历史与失败事实；stdout/stderr未复制为附件。报告已回读、4次临时PG均无PID且端口关闭，浏览器服务4174已关闭；本轮4个PG目录（3j652qgf、htws6m9e、rpumxdai、vx9m31ks）、2个浏览器目录（m41-t12-browser及m41-t12-browser-retry）和临时runner已精确删除，原始诊断材料不可恢复，结论/失败事实保留在本报告。已有源码、业务数据、模型、APK、历史证据与r2候选均未清理。


## 2026-11-05历史验收原文（保留，不代表当前继承规则）

以下历史内容保留原结果与当时范围；M41-T12现行要求及风险以上述本次记录为准。

# M41 管理后台 AI 告警处置建议模拟闭环测试验收报告

## 验收结论

**通过**

系统 AI 知识资料版本发布与项目继承实现通过：系统初始 V1 和不可变发布快照、平台权限与审计、项目创建固定最新版本、旧项目仅主动升级、项目覆盖/停用优先且不回退、建议历史快照保持不变；已对本机开发实例完成数据库迁移和 API 重启，存量资料与建议历史数量保持原值。

## 验收标准

- [x] 服务端集中管理按告警类型与识别分类精确匹配的模拟知识资料，支持版本、启停、权限和审计，不以模型名称或相似类别兜底
- [x] 告警详情由用户主动触发模拟建议，结构化区分处置步骤、可能相关制度原文、匹配说明和模拟来源，覆盖成功、无匹配、部分成功、失败与重试
- [x] 生成记录保存知识版本及引用快照；建议不自动认定违规、不改变告警处置、不额外上传媒体、不调用真实外部知识库或大模型
- [x] 管理页面、服务接口、项目隔离、角色权限、审计、数据库迁移及自动化浏览器回归通过，并为后续真实检索器和生成器保留可替换边界
- [x] 系统基础资料初始 V1 和后续发布快照不可变；既有项目固定版本、新项目固定最新版本，系统发布不静默升级项目
- [x] 项目资料可新增、覆盖、停用并精确匹配；停用覆盖屏蔽系统项；项目隔离及历史建议快照不变

## 小任务完成记录

| ID | 小任务 | 状态 | 记录 |
|---|---|---|---|
| M41-T01 | 冻结 AI 处置建议领域模型与接口契约 | completed | [M41-T01.md](../records/M41/M41-T01.md) |
| M41-T02 | 建立模拟知识资料持久化与版本审计 | completed | [M41-T02.md](../records/M41/M41-T02.md) |
| M41-T03 | 实现模拟知识资料管理 API | completed | [M41-T03.md](../records/M41/M41-T03.md) |
| M41-T04 | 实现可替换的模拟检索与建议生成服务 | completed | [M41-T04.md](../records/M41/M41-T04.md) |
| M41-T05 | 实现告警建议生成 API 与历史结果快照 | completed | [M41-T05.md](../records/M41/M41-T05.md) |
| M41-T06 | 开发管理后台模拟知识资料管理页面 | completed | [M41-T06.md](../records/M41/M41-T06.md) |
| M41-T07 | 在后台告警详情接入 AI 处置建议交互 | completed | [M41-T07.md](../records/M41/M41-T07.md) |
| M41-T08 | 加固项目权限、审计与安全边界 | completed | [M41-T08.md](../records/M41/M41-T08.md) |
| M41-T09 | 完成管理后台模拟闭环浏览器与服务验收 | completed | [M41-T09.md](../records/M41/M41-T09.md) |
| M41-T10 | 冻结移动端后续服务化接入方案 | completed | [M41-T10.md](../records/M41/M41-T10.md) |
| M41-T11 | 系统AI资料版本发布与项目继承覆盖 | completed | [M41-T11.md](../records/M41/M41-T11.md) |

## 测试结果

- 后端告警建议回归 26 项通过；系统知识 API/权限/持久化/ID 边界单测 7 项通过；隔离 PostgreSQL 17：系统及项目版本、升级、覆盖、停用遮蔽、新项目默认最新版本通过，临时 Schema/实例清理成功。
- Admin Web Vitest 27 文件/195 项通过；vue-tsc 类型检查与生产构建通过。
- Harness 单元测试 34 项通过；task validate 与 render 通过。
- 本机 PostgreSQL Alembic 33→34；本机版本 V1/5 项资料可读、Default Project 绑定 V1，既有 5 项项目资料和 10 条建议历史保留，历史查询 HTTP 200。

## 验收证据

- harness/records/M41/M41-T11.md
- harness/evidence/M41/M41-T11-live-check.md
- docs/ai-alert-advice-api-v1.md
- [后端测试报告](../evidence/M111/T02/TEST_REPORT.md)中的`m111-updates-j5r86gn2`运行；2026-11-12仅迁移原始输出留存形式，原验收结论不变。

## 遗留风险

- 无；若存在遗留风险，必须在正式通过前改写本节并给出责任人和截止日期。
