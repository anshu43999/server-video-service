# M32-T18 — 后台 /video 子路径修复（本地完成，未部署）

日期：2026-11-09。基线提交：ea23723213a7a28b75f099f670e524189d272d7e。

## 实测问题

- 用户报告：从 /video/admin 进入后台后地址变成 /admin/…，刷新进入同域名其他项目。
- 本轮只读公网 GET /video/admin 返回 307，Location 为 http://saas.link-work.com.cn/admin/（同时丢失前缀与 HTTPS）。
- GET /video/admin/ 返回 HTML，资源地址已经被既有 Nginx 替换为 /video/admin/assets/…；这不代表 JavaScript 路由 base 同样正确。
- 本地与部署提交一致：build-settings.ts 正式 base 固定 /admin/；router.ts 原来直接使用 import.meta.env.BASE_URL。
- 这是与此前 readiness/DNS 引起的 502 不同的问题。这里只修复页面导航，不变更数据库或鉴权策略。

## 产品变更

1. deploymentPaths.ts 从浏览器实际 pathname 的明确挂载边界选择 /admin/、/admin-next/、/video/admin/ 或 /video/admin-next/；其他地址回退构建 base，不接受任意外部 origin 或查询参数作为 base。
2. Vue Router 使用该运行时 base；登录、菜单、前进后退、深链接、刷新、退出均通过同一路由器保留前缀。
3. 后端 /admin 与 /admin-next 的 GET/HEAD 补斜杠重定向使用相对 Location，保留外部 origin、HTTPS、剥离前的代理前缀及查询字符串，不信任转发头来构造地址。
4. preview 的“打开正式后台”链接跟随实际挂载前缀。

没有修改 Nginx、Ingress、运行时 Secret/ConfigMap、模型 PVC、转换器、数据库、APK 发布或鉴权业务。既有 /aiyoloapi 独立入口及 API/WS 地址保持原样；不把本次当成所有 API/下载链接的全站路径重构。裸 /video 的根入口跳转不在本次 /video/admin 入口修复范围内。

## 真实验证

- npm run test：28 个测试文件、209 项通过；过程中有既有代理测试的 socket hang up 输出，但最终无失败。
- npm run build、npm run build:preview：类型检查与两个构建均通过。正式产物 index-C0ezwVMd.js，预览产物 index-DAYa2oz0.js；产物只用于本地验收，不作为绕过 Git 的发布输入。
- test_admin_frontend_hosting.py：8 项通过，新构建后重新运行同样通过。覆盖 GET/HEAD 相对补斜杠、HTTPS/前缀/查询、深链接回退、缺失资源 404、缓存策略、直连与预览资源。
- npx playwright test --config playwright.subpath.config.ts：4 项通过、2 项明确跳过。三套真实浏览器登录流程为代理 /video/admin、本地 /admin、本地 /admin-next；另有代理重定向/错误根项目隔离断言。
- 浏览器使用本机现有 Chromium：C:/Users/45393/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe，通过 PLAYWRIGHT_CHROMIUM_EXECUTABLE 显式指定；并非 Playwright 默认期待但未安装的 1248。
- 浏览器覆盖：真实内存 Cookie 登录、菜单链接、深链接刷新、查询参数与 hash、前进后退、退出、匿名深链接登录后返回，页面无 JS 异常、无跨出挂载边界的页面请求。无浏览器生产登录或生产写入。
- 代理夹具剥离 /video 并仅对 HTML 的 /admin/ 资源作与提供配置一致的替换；根 /admin/ 返回模拟其他项目的 401。使用独立真实 auth/project handlers 和内存数据，不启动 app.main、转换服务或生产数据库。
- 两个跳过项：direct 项目不执行代理专属断言；代理 preview 未在提供的 Nginx 配置中支持资源替换，未宣称其在线可用。
- Harness 单元测试 34 项通过；validate 通过。

## 测试过程中的已处理阻碍

- 初始新增 TypeScript 正则通过工具传输后丢失转义，已改用 RegExp 字符串并通过全套单测与构建。
- 沙箱限制导致临时目录和浏览器启动失败；获准后执行隔离测试通过。
- 既有完整浏览器业务夹具报模型 helmet 初始化失败；新路径专项测试改用独立 auth/project 夹具，未修改模型业务来绕过错误。全量业务浏览器验收未执行，不宣称通过。
- 默认 Playwright Chromium 1248 未安装；使用已安装的 1234 通过，不安装或下载浏览器。

## 发布状态与范围

本地源码和任务/验证记录已完成。2026-11-09 用户已批准仅提交、推送本次路径修复及相关测试记录；本记录更新时尚待执行并核对远端提交，实际提交 SHA 以 Git 和后续发布回执为准。未连接构建机、未重建 Docker 镜像、未部署生产。线上仍是旧代码，用户症状不会因本地修改或 Git 推送而自动消失。

产品文件：app/admin_frontend.py、admin-web/src/app/deploymentPaths.ts、admin-web/src/app/router.ts、admin-web/src/layouts/AdminLayout.vue。
测试文件：tests/test_admin_frontend_hosting.py、tests/admin_subpath_server.py、admin-web/tests/deployment-paths.test.ts、admin-web/tests-e2e/subpath.spec.ts、admin-web/playwright.subpath.config.ts。

Git 优先后续：用户批准本次明确范围 commit/push → 构建机同步已推送的精确 SHA → 仓库 Dockerfile 构建新标签 → 记录镜像、tar 和仓库摘要 → 用户单独批准生产切换 → 公网真实登录、菜单、刷新验收。不覆盖旧镜像标签，不直接改开发服务器或容器。转换器无需因这次后台路径修改而重建。

工作区存在本轮之前的 Harness、tests 和模型运行数据修改；均未回滚或顺带提交。后续提交必须单独审阅任务状态文件中的混合变更，不 git add 整个工作区。
