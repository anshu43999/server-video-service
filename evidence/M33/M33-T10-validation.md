# M33-T10 管理后台项目上下文与安全切换验收

- 日期：2026-10-12
- 工程：`E:/aiyolo/server-video-service`
- 任务：M33-T10；本记录不关闭整个 M33，也不启动 M33-T11。
- 实现说明：`docs/admin-project-context.md`。

## 已交付

1. 基于平台账号身份与 `m33-v1` 可访问项目接口建立项目选择状态机；成员单项目自动进入、多项目显式选择。平台管理员按冻结契约始终显式进入，并走服务端项目入口审计。
2. 当前项目、项目角色、项目代码固定展示；平台全局模型与诊断区使用独立上下文。沿用既有绿色工业后台样式，修复项目导航在桌面的竖排问题。
3. 切换同步清空上下文与缓存，取消 REST/XHR/WebSocket/媒体，再卸载旧页面清理轮询、弹窗和证据 URL，最后核验并加载新项目。generation 阻止迟到的响应或消息污染新项目。
4. 项目路径 fail closed；协议不兼容、无成员关系、不可见项目、非法深链、失权、停用/归档和网络异常有明确状态，不回退全局业务数据。
5. 标签页保持独立项目选择；共享 Cookie 会话改变时用无敏感内容的通知 nonce 触发清空与复核；退出后迟到的身份响应不会恢复本地会话。
6. 服务端可访问项目列表对平台管理员同样按生命周期裁剪有效能力，并补充对应后端断言。

## 实测结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 前端 Vitest 全量 | 13 个文件，83 项通过 | `T10-unit.log` |
| 正式构建与类型检查 | 通过 | `T10-build.log` |
| 预览构建与类型检查 | 通过 | `T10-preview-build.log` |
| 正式构建浏览器回归 | 54 项通过，包含 11 项项目外壳专项 | `T10-browser-regression.log` |
| 后端 unittest 全量 | 548 项：520 通过、28 条件跳过，0 失败/错误 | `T10-backend-regression.log` |
| Harness 单元测试 | 30 项通过 | `T10-harness.log` |
| Harness 状态/记录 | 通过 CLI complete，随后 validate/render 复核 | `../../harness/records/M33/M33-T10.md` |

浏览器使用本机 Chrome：`C:/Program Files/Google/Chrome/Application/chrome.exe`。Playwright 启动隔离的本地 FastAPI 测试服务，没有复用或修改生产服务/数据库。

最终浏览器回归包含身份 generation 修正、严格项目 DTO 校验以及导航布局修正。后端全量回归在最后的纯前端修正之前执行，之后没有修改后端产品逻辑。28 项跳过不是通过，不能据此宣称所有外部依赖或生产环境均已验证。

## 验收覆盖

| 场景 | 覆盖位置 |
| --- | --- |
| 单项目自动进入、管理员显式进入、多项目选择、空项目 | `tests/projects.test.ts`、`tests-e2e/projects.spec.ts` |
| 切换旧数据消失、同名资源不串项目、迟到响应 | 同上；包含忽略 abort 的响应 body 用例 |
| WebSocket 关闭、排队消息/重连阻断、MJPEG 清理、上传取消 | `tests/projects.test.ts`；浏览器项目切换用例 |
| Pinia 缓存清理、轮询停止、页面卸载 | 项目专项与既有 alerts/dashboard/streams 浏览器用例 |
| 成员移除、角色变更、停用后的权限复核 | 项目单元和浏览器用例 |
| 深链、刷新、错误项目 ID/重复 query、协议版本不兼容 | 项目单元和浏览器用例 |
| 两标签页独立项目及退出传播 | 项目浏览器用例；storage 单元用例 |
| 退出过程中迟到身份检查 | `tests/session.test.ts` |
| 真实 Cookie 登录、身份/项目列表与进入、项目审计 | `tests-e2e/cutover.spec.ts`、`tests/admin_frontend_server.py` |
| 平台生命周期有效能力 | `tests/test_project_management_api.py` |

上表未带目录前缀的前端测试均位于 `admin-web/` 下。浏览器业务场景大量使用可控 fixture，WebSocket 关闭测试含模拟连接；它们验证客户端状态隔离，不替代真实跨端、媒体、代理及生产联调。

## 视觉与可访问性

- `M33-T10-project-1440.png`：桌面项目栏、项目名/角色和导航清晰；已修复并增加项目空间导航高度断言。
- `M33-T10-project-390.png`：窄屏保持项目信息与切换入口，无横向溢出。
- 两张最终截图均人工查看；项目选择支持键盘 Enter；既有窄屏导航/弹窗/大屏用例随 54 项回归通过。

## 复现命令

在 `admin-web/` 中：

```powershell
npm run test -- --reporter=dot
npm run build
npm run build:preview
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE='C:/Program Files/Google/Chrome/Application/chrome.exe'
npm run test:e2e:production -- --workers=2
```

在服务工程根目录中：

```powershell
$env:DATABASE_URL=''
$env:TEMP=(Resolve-Path -LiteralPath '.test-db').Path
$env:TMP=$env:TEMP
& './.venv/Scripts/python.exe' -m unittest discover -s tests -p 'test_*.py' -q
python -m unittest discover -s harness/tests -p 'test_*.py'
python harness/harness.py validate
python harness/harness.py render
```

## 遗留边界与风险

- T11：项目、账号、成员、移交与生命周期操作管理界面尚未实现。T12：完整业务按钮能力矩阵、项目模型维护、停用/归档历史只读界面尚待后续；本次保守暂停旧业务页，不能当作这些能力已完成。
- 客户端每 15 秒核验加事件触发不能保证服务端变更后零延迟清屏；后端请求级实时授权是最终边界。离线/后台/验证失败会清空上下文。
- 取消请求不能回滚已提交的服务端写入；不自动重试结果不明的写操作，重新进入后核验真实状态。
- 未执行生产数据库迁移、部署、真实媒体全链路或 Android 验收；M33-T15/T16/T17/T18 及 Android 后续任务不因本记录而完成。
- 构建有既有 npm 用户配置警告，但命令成功。全仓 `git diff --check` 仍报告 Harness 自动生成任务板的 Markdown 双空格换行；未手改生成器输出，也未宣称全仓 diff 检查无警告。
- 保留工作区原有未提交改动，未提交或推送 Git，未读取/修改本地凭据与签名材料。
