# M32-T02 前端工程与托管验证

日期：2026-10-08；执行目录：`E:\aiyolo\server-video-service`。

## 交付范围

- `admin-web/`：Vue 3、TypeScript、Vite、Vue Router、Pinia、Vitest 及锁文件。
- `/admin-next/`：迁移预览；默认 `/admin/` 继续托管遗留页面。
- `ADMIN_FRONTEND_MODE=legacy|vue`：显式切换，Vue 正式产物缺失时拒绝启动。
- SPA 回退仅用于 GET/HEAD HTML 页面导航；缺失 asset、API 和 health 路径保持 404。
- Docker Node 构建阶段生成 `/admin/` 和 `/admin-next/` 两套产物，Python 运行层不携带 Node。

## 自动检查

| 检查 | 结果 |
|---|---|
| `npm ci` | 通过，锁文件安装 76 个 package |
| `npm run typecheck` | 通过 |
| `npm run test` | 2 files / 5 tests 通过；包含 API/health/WS 开发代理 |
| `npm run build` | 通过；`dist/` base 为 `/admin/` |
| `npm run build:preview` | 通过；`dist-preview/` base 为 `/admin-next/` |
| `test_admin_frontend_hosting.py` | 7/7 通过；包含真实两套产物与哈希资源请求 |
| `test_admin_*.py` | 74/74 通过 |
| Docker 前端阶段契约测试 | 2/2 通过；锁文件、`npm ci`、双构建复制和非 root 运行层 |
| Vue 模式真实 FastAPI 路由探针 | `/` 307 到 `/admin/`；深链 200；缺失 asset 404；HTML `no-cache` |
| Python 编译 | `app/admin_frontend.py`、`config.py`、`main.py` 通过 |

## 浏览器检查

- Vite 开发入口：`http://127.0.0.1:5173/admin-next/engineering`。
- 1440 x 900：`scrollWidth=clientWidth=1440`，页面和关键文案正常渲染。
- 390 x 844：`scrollWidth=clientWidth=390`，标题、动作、页脚均在视口内且无重叠。
- `/admin-next/streams/example` 深链进入“这个页面尚未开放”，不渲染 form/button/input 等伪业务控件。
- 浏览器控制台 error 数为 0。

## 环境限制与既有失败

本机 Windows、Ubuntu WSL 均没有 Docker/Podman/Buildah/nerdctl，因此未实际执行 `docker build`。已核对 Docker Hub 上 `node:22.22.0-bookworm-slim` 标签存在，并用静态部署契约测试验证 Dockerfile；实际镜像构建仍是部署环境的剩余验证项。

完整 `test_docker_deployment.py` 有 9 项既有错误：当前工作区 `models/registry.json` 指向未提交的 `models/local-conversion/...` 产物，测试执行 `git show HEAD:<artifact>` 时失败。其余 12 项通过；本任务没有修改或回退这些模型资产。`test_auth.py` 另因已有开发服务占用转换 worker 锁而无法启动测试 lifespan，不是前端托管断言失败。
