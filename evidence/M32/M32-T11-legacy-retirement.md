# M32-T11 旧管理前端本地归档与退役证据

日期：2026-10-09  
结论：本机归档、恢复演练与旧代码清理完成；当前产品仅托管 Vue 管理前端。

## 归档

- 目录：`E:\aiyolo\archives\server-admin-legacy\20261009-M32-T11`
- 文件：50 个；ZIP：21,616,802 bytes
- ZIP SHA256：`a849d825e4b5f367a8c062c510243bc6ddc90efe6fc99647baeb8a08cae7a254`
- 内容：`app/static/` 全部页面、脚本、样式和图片；legacy 托管/配置兼容快照；15 个旧页面专属测试；受影响的浏览器配置与发布文档。
- 排除：`.env`、证书/密钥、数据库、模型、日志、缓存、node_modules 和不相关产品文件。

`manifest.json` 记录每个文件的路径、字节数、SHA256、工作区 Git HEAD 参考和归档说明；`FILES.md` 便于人工浏览。`archive.py list --path` 可查询文件历史，`verify` 校验 ZIP 和逐文件摘要。归档保存的是包含未提交修改的工作区快照，Git HEAD 只用于定位基线。

## 恢复演练

`M32-T11-verify-archive.py` 完成以下隔离验证，未改动当前产品：

1. 校验 ZIP SHA256、成员列表和 50 个逐文件 SHA256。
2. 解压至独立目录并逐字节比较。
3. 使用归档的旧托管实现加载旧页面：9 个菜单，HTML/JS/CSS/证据图片均为 200 且 no-cache。
4. 使用真实内存账号路由验证 Cookie 登录、`auth/me` 和退出，Vue `/admin-next/` 独立可用。
5. 验证 restore 默认仅预览；`--apply` 自动保存现版文件，再完整恢复旧快照；随后用生成的备份撤销恢复，并确认现版文件恢复、旧文件安全删除。

使用与限制见 `E:\aiyolo\archives\server-admin-legacy\README.md`。恢复工具只处理清单内文件，覆盖前自动创建另一个带哈希的档案。对于归档后发生变化的后端兼容文件，应先在完整工程副本中比较合并。此档案不是数据库备份或生产不可变镜像，需要另行备份到可靠介质。

## 产品清理

- 删除 `app/static/` 13 个文件（含 8 张图片）。
- 删除 LegacyAdmin 与 legacy 挂载分支；配置只接受 `ADMIN_FRONTEND_MODE=vue`，遗留 legacy 覆盖会明确启动失败。
- 删除 15 个仅断言旧 HTML/JS 的测试；从混合模型转换测试移除旧 UI 字符串断言。
- API 前缀扫描改为 Vue API 客户端；图片浏览器夹具迁至 `admin-web/tests-e2e/fixtures/`。
- 浏览器生产夹具不再启动旧服务；改为验证旧资源 404、正式/预览 Vue base 和缓存。
- 更新本地、Docker、Compose 和 K8s 运维说明；归档在仓库和 Docker context 外。

业务 API、Cookie 权限、Vue 功能测试和部署契约保留。历史 ADR/功能对等清单保留并明确标记为迁移基线，未改写既有 T01–T10 验收事实。

## 测试

- 归档：50 文件哈希、独立托管/真实 Cookie、恢复预览/备份/撤销通过。
- Vue：Vitest 60/60；`npm run build`、`npm run build:preview` 通过。
- 正式构建 Playwright：43/43，通过桌面/窄屏九菜单、权限和退役资源 404。
- 后端定向回归：35/35，通过静态托管、API 前缀、流/API、管理操作、模型 manifest、Docker 14 项及 K8s 6 项契约。
- Harness 单元测试：30/30；最终 validate/render 见任务记录。
- `git diff --check` 仅报告 Harness 自动生成 Markdown 的有意 Markdown 换行空格；未发现产品文件空白错误。

## 边界与风险

- 本轮不提交、不推送，不构建 Docker 镜像，不执行生产部署。
- 本地档案如果与磁盘同时损坏便不可恢复；需要运维另存副本。当前还保留早期 T10 静态 ZIP作为历史证据，但完整回退以 T11 版本档案为准。
- 生产回退优先使用上一完整不可变镜像；代码档案回退需重新构建和发布，不可在现版只改 `ADMIN_FRONTEND_MODE=legacy`。
- 整个后端其他既有未完成任务、生产媒体/模型转换和安全边界不因本次前端退役而视为完成。
