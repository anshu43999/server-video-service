# 管理前端发布、缓存和回退

> 2026-10-15 / M34-T04 视频范围修订：本文旧直播分发/移动远程播放条款由 [ADR-003](adr-003-analysis-alerts-only.md) 取代。保留PC同源预览、输入分析、项目隔离、正式告警和证据；回退须符合 [分发退役升级手册](media-retirement-upgrade.md)，不能恢复旧发布器/移动直播。本文其他账号、项目、迁移、恢复、安全与审计门禁仍有效；先本地真实验收，再部署。

源码：`admin-web/src/`；正式入口：`/admin/`；根 URL：307 跳转 `/admin/`。默认 `ADMIN_FRONTEND_MODE=vue`，FastAPI 托管完整 `admin-web/dist/`。开发服务器与生产 Python 服务独立，生产无需 Node。`/admin-next/` 使用独立 `dist-preview/`，仍接同一业务 API，不是隔离数据库或沙箱。

## 构建与本机验收

在 `admin-web/` 执行：

```powershell
npm ci
npm run test
npm run build
npm run build:preview
npm run test:e2e
npm run test:e2e:production
```

两次 build 均包含类型检查。正式浏览器测试启动隔离的 FastAPI 静态托管服务，覆盖真实构建和 `/admin` 九个菜单；业务响应采用确定性夹具，Cookie 登录另有真实服务验收。测试不修改开发数据库。首个管理员初始化、真实 RTSP/WHEP、业务模型转换和 MinIO 仍需在目标部署验收。

本机先构建再运行 `start-server.ps1`；缺失 `dist/index.html` 时直接停止。当前仅支持 `ADMIN_FRONTEND_MODE=vue`；旧部署 `.env` 或环境变量中的 `legacy` 必须更新为 `vue`，否则配置校验失败。旧页面需要先恢复本地档案中的代码和托管兼容文件，不能只修改环境变量。

## Docker 与 Kubernetes

Docker 镜像在 Node 阶段 `npm ci`、单元测试、构建两套 base；Python 阶段复制 Vue 产物，旧静态目录已删除。本地档案位于仓库外，不进入构建上下文。Compose 默认 Vue；K8s `config.env.example` 设置 Vue，由 `aiyolo-runtime-config` 注入。更新时应发布不可变镜像，整体替换 HTML/assets，不能逐文件覆盖在线目录；已有标签禁止重用。

Compose 修改 `.env` 为 `ADMIN_FRONTEND_MODE=vue` 后执行：

```bash
bash deploy/deploy.sh config
bash deploy/deploy.sh up
```

K8s 在服务器私有 `config.env` 中设置该值，按生产 README 更新 ConfigMap 后执行 `kubectl rollout restart deployment/aiyolo-video-service -n saas-prod`，等待 rollout 完成。若变更镜像则按 kustomization 发布。不要用 `kubectl set env` 留下高于 ConfigMap 的长期覆盖。

## 缓存与深链

| 路径 | 行为 |
|---|---|
| `/`、`/admin` | 跳转规范入口 `/admin/` |
| `/admin/`、`/admin/overview` 等 HTML | `Cache-Control: no-cache`，允许保存但每次重新验证 |
| `/admin/assets/*-内容哈希.js/css` | `public, max-age=31536000, immutable` |
| 缺失 assets、图片、`.env`、嵌入的 API 路径 | 真实 404，绝不回退 HTML |
| `/aiyoloapi/*`、`/healthz` | 保持后端响应和状态，禁止网关缓存账号、业务和健康请求 |
| 旧 `app.js/styles.css/conversion.js/conversion.css/evidence/*` | 当前发布包返回 404 |

仅 GET/HEAD、Accept 含 `text/html`、无文件后缀的页面导航可回退 SPA index。未知页面进入“页面不存在”；`/engineering` 是早期预览书签的兼容重定向到总览。网关不能额外使用覆盖所有路径的 `try_files ... /index.html`，也不能覆盖服务返回的 Cache-Control。

升级后的验证：访问根 URL、九个菜单深链和刷新；登录/退出；检查 HTML 和资源缓存头、缺失资源 404；观察权限/会话失效及实时资源释放。浏览器已打开的旧版本应刷新；新镜像不会继续提供上一构建的哈希资源，旧页面延迟加载资源如失效需整页刷新。

## 本地历史档案与回退边界

M32-T11 已归档并删除 `app/static/`、legacy 托管分支和 15 个仅检查旧 HTML/JS 的测试。归档包含删除前的全部静态资源、兼容托管/配置、相关测试及发布文档，共 50 个文件；SHA256 清单与 ZIP 位于 `E:\aiyolo\archives\server-admin-legacy\20261009-M32-T11`。旧 T10 静态 ZIP 和已验收证据保留作历史记录。Vue 浏览器测试需要的图片移至 `admin-web/tests-e2e/fixtures/`，不作为业务 Mock 数据。混合转换测试仅退役旧 UI 字符串断言，真实业务/API 测试保留。

历史查询、解压、预览恢复、自动备份和撤销恢复的完整命令见 [本地档案说明](../../archives/server-admin-legacy/README.md)。恢复演练已逐文件核对哈希，独立托管旧页面及静态资源，并验证真实 Cookie 登录/退出；隔离目录完成恢复与撤销。当前工作工程未执行旧版回退。

回退前停止服务，先预览将覆盖的文件，特别是 `app/main.py` 和 `app/config.py`，归档后的业务改动需在独立完整工程副本中比较合并。恢复兼容代码后才能选择 `legacy` 并重启；Docker/K8s 需从恢复代码重新构建并发布，或恢复上一已保存的完整不可变镜像。本地档案没有数据库、凭据和模型，也不是不可变生产镜像。数据库回退继续遵循 Docker 部署文档。本轮未执行生产部署或容器构建。
