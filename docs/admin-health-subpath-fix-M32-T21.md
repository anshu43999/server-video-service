# M32-T21 — 健康请求子路径修复（本地完成，未发布）

日期：2026-11-09。本地源码基线：`0a061fbccab4ec5fde670872e71e39e3b501010b`（已部署 r5 来源）。

## 问题与边界

用户在菜单切换时看到多条红色网络请求。后续截图明确显示 3 条 `/healthz` HTTP 404；此前只读公网检查确认根 `/healthz` 为 404、`/video/healthz` 为 200。r5 页面 history base 已修复，但 ApiClient 对健康接口仍直接使用域名根路径。

截图中的 `models`、`knowledge-entries`、`versions` 无状态码请求不能全部归为这一个问题。代码确有页面卸载/上下文切换取消旧请求的行为；本次本地浏览器复现取消为 ERR_ABORTED 且无未处理页面异常，不据此断言用户所有红色请求均正常。`me`/`projects` 的权限校验、频率和作用域隔离未改变。

## 产品变更

仅修改两处产品文件：

- `admin-web/src/app/deploymentPaths.ts`：增加 `adminHealthPath`，复用已有明确挂载边界匹配。`/video/admin`、`/video/admin/...`、`/video/admin-next/...` 选择 `/video/healthz`；根部署及无匹配路径保持 `/healthz`。不从查询参数、任意 origin 或不完整相似前缀推导地址。
- `admin-web/src/api/client.ts`：只对逻辑端点 `/healthz` 调用该函数；`/aiyoloapi/...`、项目路径、同源 Cookie、请求取消/超时/错误处理保持原样。

没有关闭请求取消、吞掉 404/503、增加跨路径重试，或把所有 API 加上 `/video`。没有修改后端健康路由、数据库、Nginx、Ingress、K8s 探针/资源/卷、App 升级开关、转换器。

## 测试证据

1. 先新增回归测试运行旧代码：15 项中 6 失败、9 通过，失败断言均显示应为 `/video/healthz` 而实际为 `/healthz`。证据 `evidence/M32-T21-before-fix.log`。
2. 修复后针对性测试：4 文件 56 项通过。覆盖根/子路径/preview、相似路径边界、业务 API/项目隔离不变、404/503 不伪装成功、调用方取消/超时/网络失败区分。证据 `evidence/M32-T21-targeted.log`。
3. 完整前端：28 文件 220 项通过。既有代理故障测试有 socket hang up 输出但最终全通过；npm 有既有配置警告。证据 `evidence/M32-T21-full-tests.log`。
4. `npm run build` 与 `npm run build:preview` 均完成类型检查和构建；产物分别为 `index-DLDhJJvT.js`、`index-C2iqO0_X.js`。证据 `evidence/M32-T21-build.log`、`evidence/M32-T21-build-preview.log`。产物仅用于本地验收，不传服务器代替 Git 构建。
5. 托管回归：8 项通过。证据 `evidence/M32-T21-hosting.log`。
6. Chromium 隔离浏览器：7 项通过、3 项明确跳过。命令使用现有 Chromium 1234，Playwright 子路径配置及独立输出 `test-results-health-subpath-r2`。证据 `evidence/M32-T21-browser-r2.log`。
7. Harness 单元测试 34 项通过；validate 及 scoped git diff --check 通过。证据 `evidence/M32-T21-harness-tests.log`。

浏览器范围：直接 `/admin`、直接 `/admin-next`、代理 `/video/admin`，真实内存 Cookie 登录；由本地代理剥离前缀并转发合成健康/指标，不访问真实数据库或主业务生命周期。健康成功阶段不拦截响应，经过实际本地 HTTP 服务；反复点击诊断/平台菜单、刷新/重进，验证健康路径与独立 metrics 路径；测试专门挂起一次健康读请求后切换菜单，确认 ERR_ABORTED 且无 pageerror；注入 503 验证界面显示失败，再恢复真实本地响应并刷新成功。保留已有登录/导航/前进后退/退出/其他项目隔离回归。

3 个跳过项：direct 项目不执行代理专属断言（1 项）；生产提供的代理只重写 stable 资源，不支持 `/video/admin-next` 资源，两个 preview 代理流程明确跳过。单元测试覆盖其健康地址计算，不宣称生产 preview 可用。未执行完整业务浏览器验收、生产登录或真实 OTA 安装。

## 测试过程中处理的问题

首次浏览器运行 3 失败、4 通过、3 跳过：新测试的取消拦截清理后再次安装故障拦截未生效，预期 503 却实际收到本地真实 200，错误提示断言失败。保留 `evidence/M32-T21-browser.log` 和 `test-results-health-subpath/` 的首次证据。改为单个稳定拦截器的 live/held/failure 模式，并断言注入确实执行；仅修复测试，不改变业务错误处理。复测所有适用用例通过。

## 发布状态与遗留

2026-11-09 后续授权：用户已明确批准仅提交、推送本次健康路径修复及对应测试、记录。范围为两处产品文件、三处测试文件、本文和 M32-T21 完成记录，以及任务状态/任务板中的 M32-T21 部分；不包含其他任务、模型数据、日志、构建产物或凭据。实际提交及远端核对结果另存工作区发布回执，不把 Git 推送等同于镜像构建或生产发布。以下保留任务完成时的历史状态。

本地修复和验收完成，尚未 commit/push、连接开发构建服务器、生成新 Docker 镜像或变更生产。生产仍为 r5，其健康地址 404 不会因本地改动自动消失。

下一步需用户批准明确范围 Git 提交/推送，再按 Git 优先流程从完整已推送 SHA 构建新视频镜像，登记各类摘要后交付用户部署。转换器无需重建。保留已上线 HTTP 探针、App 升级启用配置、外部数据库/外部 APK 存储与现有模型卷。

生产此前一次启动数据库连接异常的底层根因仍未确定，与这次前端路径修复分开跟踪。未承诺根除所有网络错误或取消记录。工作区既有其他修改保持原样，未自动提交。
