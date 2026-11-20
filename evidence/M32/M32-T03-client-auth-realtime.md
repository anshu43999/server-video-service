# M32-T03 鉴权、API Client 与实时基础层验证

日期：2026-10-08；执行目录：`E:\aiyolo\server-video-service`。

## 实现边界

- 会话由服务端 `aiyolo_session` HttpOnly Cookie 维持；登录/setup 响应中的兼容 access token 不进入 Pinia、localStorage 或 sessionStorage。
- 启动顺序为 `auth/status` 后在已认证状态读取 `auth/me`，业务路由在会话恢复完成前不加载。
- admin 进入后台；operator 进入权限边界页；匿名访问受保护深链转到登录并保留安全的相对 redirect。
- 业务 401 合并执行一次 `auth/me`：会话仍有效则映射为权限不足，失效则关闭实时订阅并转匿名状态，网络不确定时不武断退出。
- API Client 支持同源查询参数、JSON、FormData、Blob、文本、204、octet-stream、超时、调用方取消和 AbortSignal；写入不自动重放。
- 错误兼容 detail 字符串、Pydantic 数组、detail/error 对象、missing 字段和 Retry-After，不记录请求体、Cookie、Header 或完整外部凭据。
- WebSocket 使用同源 ws/wss Cookie，提供有限次数且有最大延迟的指数退避、抖动、在线/离线恢复、组件卸载释放和全局退出释放。4401、4404、4429 为终止状态。

## 自动检查

| 检查 | 结果 |
|---|---|
| `npm run typecheck` | 通过 |
| `npm run test` | 5 files / 20 tests 通过 |
| `npm run build` | 通过；47 modules |
| `npm run build:preview` | 通过；47 modules |
| `test_admin_*.py` | 74/74 通过 |
| `git diff --check`（本任务文件，生成任务板除外） | 通过 |

测试覆盖 JSON/FormData/Blob/204、同源保护、Pydantic 错误、敏感信息脱敏、取消/超时/网络异常、401 三态、Cookie 会话恢复、首管理员 setup、不持久化 token/password、并发身份检查去重、退出失败释放、会话失效释放、WebSocket 消息、退避、离线、组件卸载及 4401/4404/4429。

## 浏览器检查

- 使用本地匿名响应代理验证从 `/admin-next/engineering` 自动进入 `/admin-next/login`，没有操作或清除现有真实会话。
- 1440 x 900：登录页无横向溢出，账号和密码字段、按钮可见；密码字段为 `type=password`。
- 390 x 844：表单宽度 375px、按钮宽度 327px，无横向溢出或控件重叠，初始焦点在账号字段。
- 浏览器存储未发现 `accessToken`；最终重新打开真实预览入口，当前页面控制台 error 为 0。
- 未提交真实账号密码，也未执行登录、退出或 setup 写入。
