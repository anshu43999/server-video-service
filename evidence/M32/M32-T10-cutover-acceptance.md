# M32-T10 默认入口切换与功能对等验收

日期：2026-10-09；工程：`E:\aiyolo\server-video-service`。以当前工作区的未提交迁移成果为基线，没有恢复 HEAD、提交、推送或发布到生产。验收结论只针对本机前端工程化交付与以下实测，不代表后端全部生产能力已验收。

## 交付和清理边界

- Settings、Docker 镜像、Compose 缺省、`.env.example`、K8s 配置示例统一为 `ADMIN_FRONTEND_MODE=vue`。`/` 统一跳转 `/admin/`；Vue 正式构建使用 `/admin/`，preview 使用 `/admin-next/`。既有 `.env`/ConfigMap 的显式 legacy 选择不会被自动覆盖，运维需按发布文档切换并重启。
- Vue 不加载旧全局 JS/CSS，不使用 `innerHTML`/`v-html`、全局 fetch 覆写或账号持久存储。九个菜单替代全部迁移占位。
- 删除无运行时引用的 `FoundationPage.vue`、`MigrationPage.vue`、专属 CSS、迁移任务 meta、旧版优先入口和相应两个占位测试；未知页面使用正常 NotFoundView。`/engineering` 保留早期书签重定向，登录默认回总览。
- `app/static/` 的五个旧文件和 evidence 图片仍被显式 legacy 模式引用，保留为冻结回退版本；原始清理计划的这一边界已在 ADR-004 补充说明。没有删除仍被引用的回退资产，也没有删除保护它们的历史源码契约测试。
- 保存自包含回退包 `M32-T10-legacy-static.zip`。隔离 legacy 服务从该 ZIP 解压到临时目录运行，而非读取源目录；实际验证根跳转、登录、九个旧菜单、五个静态文件和 preview 独立性。ZIP 与 HTML/JS/CSS 哈希如下。
- Docker/部署/缓存/运维说明更新到 `docs/admin-frontend-release.md`。新测试结果目录排除于 Git 和 Docker context。

## 功能对等矩阵

稳定编号来自 `docs/admin-frontend-parity.md`。以下页面行为在正式构建 `/admin` 执行，另在开发 preview 复验。大多数业务 API 使用确定性契约夹具；真实账号和真实 RTSP 链路单列，不把夹具误称生产实测。

| 编号 | 验证结果与定位证据 |
|---|---|
| F01 / A01 / A01b | 实际 auth router + 内存隔离账号，匿名深链跳登录、admin Cookie 登录/刷新/退出，HttpOnly，无浏览器密码/token 存储；operator 九个路由均被限制且未读业务；服务端 account_auth 4 项、session 单测覆盖 setup/过期/退出失败 |
| F02 / C01 | 九个菜单、正式深链刷新、未知路由和返回总览；1440/390 px 逐页无横向溢出，移动抽屉键盘/Escape；cutover.spec.ts、shell.spec.ts |
| F03 F04 / Q02 / A02 | 真实字段统计、0/不可用分离、7d/30d 快速竞态、事件跳转、GPU 缺失、四路视频墙/大屏/Escape/轮询；dashboard.spec.ts 7 项，dashboard_stats 3 项 |
| F05 / D01 / A03 A04 / W02 M01 | 创建/配置/启停/删除/绑定/参数、失败回滚、延迟响应归属、同源 MJPEG、检测 WS、轮询和卸载释放；streams.spec.ts 7 项、服务端 stream 32 项；正式构建真实 RTSP 实测见下文 |
| F06 / D06 / Q01 / A05 A06 W01 | 真实 eventId 契约、筛选/空/错、详情证据缺失、取消/确认/误报、并发处置、复核结果与原始事实分离；alerts.spec.ts 5 项、alert API 6 项；WS 状态/4401/重连释放有公共单测 |
| F07 / D08 / A08 | 实际通道/回执投影，显式测试入队不冒充投递完成，取消无写入、离页停止轮询；operations.spec.ts。后端无推送目标 CRUD，页面明确说明，不伪保存 |
| F08 / D07 / A07 | 完整规则 JSON 字段、创建编辑删除、版本变化保护、能力拒绝、先校验后绑定、审计；operations.spec.ts、admin_operations_api 3 项。单流单模型/未实现组合算子边界明确 |
| F09 / D02 D04 D05 / Q03 / A09 A09b A11 | 真实可绑定投影、去重、搜索/场景/页签、Manifest 登记、版本详情、下载、激活/卸载确认与占用保护；models.spec.ts，uninstall 9 项、lifecycle 14 项 |
| F10 / U02 / A13 | ZIP 原始体、真实字节进度 UI 契约、内容哈希、内置/引用保护、成功清理与失败保留；models.spec.ts、conversion API 和后台校准契约 |
| F11 / U01 U03 U04 U05 / A12 A14 | PT 原始体、成功清理/失败保留/超限拒绝、local/WSL/remote 配置、冻结校准、排队/中断/不确定进度、日志脱敏、重试和离页取消；models.spec.ts 10 项、conversion 25 项通过/1 项可选 PostgreSQL 跳过、remote 4 项 |
| D03 / A10 | 双平台参数、类别字段、阈值、revision 409 不覆盖、恢复默认确认、审计；models.spec.ts、参数 API/store 13 项。历史版本参数写入无现有接口，明确限制 |
| U06 | 证据/产物/误报 JSON/任务日志下载契约和 Blob 释放有页面/client 单测；服务端下载既有门禁未改变 |
| F12 / A02 | healthz 503 不报成功，缺少数据库/GPU 有明确反馈；operations.spec.ts |
| F13 / V01 / A06 | 配置读取/写入/失败保留、图像出站确认、额度、只显示供应商标记，无 endpoint/key/timeout 伪保存/回显或伪探测；operations.spec.ts |
| F14 | Vue 正式后台不迁入旧 Demo 模式，只显示实际 API 事实，失败不进入 Demo。旧演示模式保留在 legacy 回退包；这是已说明的演示能力取舍，真实业务不降级 |
| C02 C03 C04 | 类型/client 契约、204/文本/Blob/上传、401/403/409/422/503、匿名/operator/admin 权限分离，以及各页失败/空/冲突覆盖；保留历史后台契约与相关 API 回归 |
| C05 C06 | 正式页面桌面/窄屏截图、焦点/对话框/资源释放；两套 base、GET/HEAD 深链、缺失静态 404、API 不吞掉、缓存、构建缺失 fail-fast、独立 ZIP 回退 |
| W03 W04 | 移动端采集和通知契约未改；新前端不使用无鉴权 JPEG WS。其既有缺口 G08 保留为服务端安全边界，不能宣称全服务安全无缺口 |

G01/G03/G05/G06/G07 已按迁移方案处理；G02/G04/G08 为已声明后端边界：推送目标管理、供应商探测/密钥配置、多模型并行协同、诊断 JPEG WS 安全整改不由本次前端改造新增。

## 实测与自动化结果

| 门禁 | 本轮结果 |
|---|---|
| `npm run test` | 12 文件、60 项通过；比 T09 少的 2 项是已删除无引用占位页面专用测试 |
| `npm run build` / `build:preview` | 类型检查与正式/preview 构建通过 |
| `npm run test:e2e:production` | 43/43；全部页面行为在 FastAPI 托管的正式 `/admin` 构建执行 |
| 独立 ZIP 回退复验 | cutover 4/4，补验真实旧版登录；从 ZIP 解压运行，不依赖原静态目录 |
| `npm run test:e2e` | preview 39/39；4 个仅正式构建用例按条件跳过 |
| 后台 `test_admin_*.py` | 77/77（含真实构建托管和隔离规则 API） |
| API / 统计 / 会话 / 前缀 | 2 + 3 + 4 + 2 项通过 |
| Docker / K8s 契约 | 14 + 6 项通过 |
| 转换 / 远程转换 | 26 项中 25 通过、1 可选 PostgreSQL 跳过；远程 4/4 |
| 告警 API / 流 / 参数 / 卸载 / 生命周期 | 6 + 32 + 13 + 9 + 14 项通过 |
| Harness | 30/30、validate、render 通过；完成记录由 CLI 生成 |
| 差异检查 | 本轮相关 Git diff --check 通过；既有其他工作区变更保留 |

Playwright 使用已安装的 Chromium 1234：`PLAYWRIGHT_CHROMIUM_EXECUTABLE=C:\Users\45393\AppData\Local\ms-playwright\chromium-1234\chrome-win64\chrome.exe`；未下载额外浏览器。最初默认浏览器版本缺失和校准页测试标题定位错误均已修正并复验。

部署种子测试修正为同一 HEAD 中的注册表与产物比较，避免将本机运行时上传当作已提交发布资产；API 基础测试增加隔离内存账号/流配置，避免启动本机历史 RTSP 与匿名写入。没有改业务鉴权以迁就测试。

## 正式构建真实 RTSP

本机视频 `sucai1.mp4` → FFmpeg H.264 → MediaMTX `127.0.0.1:18556/probe` → 隔离真实 FastAPI `127.0.0.1:18086` → `/admin/streams`。不使用项目数据库/持久流配置，空临时模型目录，随机密码未记录。结果：

- 首帧 1920×1080；3 次停用/启用均恢复，新预览连接，取样帧数 23、35、22。
- confidence=0.41、max_fps=12 与后端读取值一致。
- 离页 active_subscribers=0；临时流经真实删除 API 清除；pageerror=0。
- 结果：`M32-T10-real-rtsp.json`；截图：`M32-T10-real-rtsp-desktop.png`。验收进程、FFmpeg 与 MediaMTX 已停止。

复现：T06 probe server + MediaMTX 配置，设置 `M32_PROBE_BASE=/admin`、`M32_PROBE_TASK=M32-T10` 后执行 `admin-web/scripts/probe-real-stream.mjs`。这里只验证原始帧诊断链路，不宣称实测 YOLO/WHEP/LL-HLS 性能。

## 构建与回退身份

| 文件 | SHA-256 |
|---|---|
| dist/index.html | 11789C6115C9D31AD77501CC8DB40D6B99A8FA8FAE3C2B07E37352C3FFFEB8B3 |
| dist/assets/index-GqPyEX-h.js | F0958314139409D7C3843C2B77CF9AA0069BBEBED62A7AB6A2C8FE878B31BABB |
| dist/assets/index-DjAf5DzZ.css | 3205B93FF3FDA30CAC017C2F9419041DBED828F1A79D1C43B3C03D3DA6EDE69A |
| dist-preview/index.html | DB44D55CCC77D7C2ABFB4D16B80C5F4160B6F01357E98B275AB42DE730F5AAFF |
| M32-T10-legacy-static.zip | B786DADE32CDE064C9EE5EF965710F2A2676B76678C404066FF4D4B54E2FBAA7 |
| legacy index.html | 020CD89316E667AAF66599A21E2F658DE50096258EA1AE1C67EC440EE9FBEE31 |
| legacy app.js | 1A2F4A8BA0B7D936088729B37A57E7D6D5F0A1B493A8B082C7F074117DFD3E94 |
| legacy conversion.js | BA853373A32484CF629792AA442EF58FC273C95100EC24532F0AB4EE65E5C105 |
| legacy styles.css | A20159E5AE490B131353AC23060D99313EEB2951BBB9CAF6696EC689A327999C |
| legacy conversion.css | 685863AF9E4865C2F48C6A7AA6E2F31BCFA4AEE357EF1E7A4F9D005F95D452A5 |

带哈希资源一年 immutable，HTML 与 legacy 资源 no-cache。Vue 缺失产物拒绝启动，静态 404 不回 HTML；切换需要进程重启/容器重建，恢复旧 HTML 和资源均验证 200。生产发布需整体不可变镜像，禁止混合复制 assets。

## 可视验收与遗留边界

已实际查看本轮截图：正式总览 1440 px、模型与复核 390 px、真实 RTSP 桌面、legacy 登录；无页面遮挡、横向溢出或退回占位页。更多截图 `M32-T10-{overview,models,verification}-{1440,390}.png`；既有详细页面/大屏截图由本轮浏览器用例再次生成。样式沿用 frontend-design 指导下既有工业运维设计令牌，没有另起视觉体系。

本机没有可用 Docker 命令，因此未构建或启动容器/集群；只验证 Dockerfile/Compose/K8s 契约及同一构建的 FastAPI 托管。真实业务 PT→TFLite、生产 PostgreSQL/MinIO、目标服务器重启、WHEP/NAT/容量与实际供应商复核未在本轮重测。这些是部署/后端能力验收边界，不作虚假通过记录；由发布运维负责人在下次生产发布前完成冒烟与业务验收。显式 legacy 覆盖需同步更新；旧页面开着升级可能需要整页刷新。

保留 legacy 会带来临时双版本存储维护成本；此版本作为冻结回退，不继续向旧版新增功能。彻底移除旧目录和 legacy 模式应在不可变回退镜像归档并验证后另行执行。现有 JPEG WS 权限缺口由后端安全维护负责人在对外开放该诊断接口前处理；本轮新页面没有使用该通道。
