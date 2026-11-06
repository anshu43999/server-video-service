# ADR-004：管理后台前端工程化与渐进迁移

状态：accepted（M32-T01 架构冻结；M32-T10 已实现默认 Vue 切换，验收见任务证据）  
日期：2026-10-08  
适用任务：M32-T01 至 M32-T10  
配套证据：[功能对等与接口清单](admin-frontend-parity.md)

2026-10-09 T11 退役补充：用户授权后，旧静态目录、托管兼容文件与相关测试/文档已保存为本地版本档案并验证恢复，随后删除旧产品静态目录、legacy 托管分支及专属源码测试。现版仅支持 vue，旧版必须恢复归档代码才能启动。详见 [发布与回退](admin-frontend-release.md) 和 [T11 证据](../evidence/M32/M32-T11-legacy-retirement.md)。下文原始基线与 T10 决策保留作历史，不代表现版配置。

2026-10-09 T10 切换补充（历史）：默认值改为 `vue`；当时冻结的 `app/static/` 仍由显式 `legacy` 模式引用，暂留在发布包内，并另存独立可解压验证的静态回退 ZIP。仅删除无引用工程占位页、迁移兼容页、专属样式和旧版优先入口；不在同一轮删除回退依赖。这是下文原始清理计划的实施边界调整，详见 [T10 验收](../evidence/M32/M32-T10-cutover-acceptance.md)。

## 背景与代码基线

管理后台不是 Vue 工程。`app/main.py` 通过 `StaticFiles(directory=STATIC_DIR, html=True)` 在 `/admin` 挂载 `app/static`；根路径直接返回遗留 `index.html`。页面行为由 `app.js`、`conversion.js` 和 HTML 中的内联脚本共同实现，样式为 `styles.css`、`conversion.css`。

维护成本主要来自全局 `state`、`window.fetch` 覆写、大量 `innerHTML`、按 DOM ID 绑定事件，以及转换模块覆写 `refreshLiveModels`、`bindStreamModel` 和表单处理器。脚本顺序决定实际行为；单看 `app.js` 会漏掉 Manifest 登记等已经由转换脚本接通的操作。

本次以当前工作区文件为真实基线，保留现有未提交的告警中心和模型资产调整；不以 Git HEAD 覆盖它们。现有全部 9 个菜单与 8 个原生 dialog 在配套清单中逐项登记。

## 决策：独立工程、同源部署

采用 Vue 3、TypeScript、Vite、Vue Router、Pinia；新源码固定在 `server-video-service/admin-web/`。FastAPI 继续提供业务服务、鉴权及静态构建托管。Node 仅用于开发与构建，生产 Python 容器不运行 Node 服务。

```text
浏览器
  ├─ /admin/                 稳定管理入口（迁移期：遗留；最终：Vue）
  ├─ /admin-next/            迁移期 Vue 预览入口
  ├─ /aiyoloapi/...          HTTP API 与 WebSocket
  └─ /healthz               健康状态
            ↓
        FastAPI
  ├─ legacy: app/static/
  ├─ vue:    admin-web/dist/ 或 dist-preview/
  └─ 原有业务、数据库、推理与媒体服务
```

API 前缀固定为 `/aiyoloapi`，不得按历史任务文案中的 `/api` 实现新的请求路径。MediaMTX 返回的媒体地址保持原协议和主机语义，不经 Vite 静态服务器改写。

## 源码和状态边界

```text
admin-web/
  src/
    app/          启动、路由和权限守卫
    api/          HTTP 封装、DTO、各领域 API、WebSocket
    stores/       会话、共享流/模型摘要
    layouts/      管理外壳
    components/   表单、表格、对话框、状态与反馈
    features/     overview、dashboard、streams、alerts、push、rules、models、diagnostics、verification
    styles/       设计令牌与基础样式
  tests/          单元与组件行为验证
  e2e/            关键浏览器流程
  package.json
  package-lock.json
```

局部表单、选中项、分页和临时反馈保留在页面或 composable。只有会话及跨页面共享摘要进入 Pinia。WebSocket、播放器、上传对象、计时器和 AbortController 由 composable 生命周期管理，不持久化到 store、localStorage 或数据库。业务事实以 API 返回为准，不通过修改页面 store 模拟保存成功。

使用原生 HTML 和轻量通用组件先保持现有视觉与交互，不在本次引入整套 UI 库或重做品牌。颜色、字体、间距、严重度样式转为设计令牌；基础字体使用本地系统回退，核心界面不依赖 Google Fonts 可达性。复杂组件库若有需要，另行记录具体收益和依赖成本。

## 路由、构建和托管

- 使用 Vue Router history 模式，9 个页面路径与清单一致，根路径跳转 `overview`；模型子页签用查询参数表示。
- Vite `base` 支持构建参数，正式构建为 `/admin/`，预览构建为 `/admin-next/`，分别输出 `dist/`、`dist-preview/`；不得混用不同 base 的产物。
- FastAPI 对所选 Vue 目录提供静态资源；仅对 GET/HEAD 的页面导航做 SPA index 回退。缺失的 `assets/`、图片和其他静态文件返回 404，绝不返回 HTML；不能吞掉 `/aiyoloapi` 或 `/healthz`。
- 设计 `ADMIN_FRONTEND_MODE=legacy|vue` 作为后续托管选择配置，默认 `legacy`。显式选择 `vue` 而产物缺失时启动失败并报告原因，不静默回退。此配置将在 M32-T02 实现，本 ADR 未新增任何运行配置。
- 迁移期 `/admin/` 使用遗留目录，`/admin-next/` 使用预览目录；各页面完成后通过预览入口验收，不在同一个 DOM 中混装两套实现。
- Vite 开发服务器代理 `/aiyoloapi`（包括 WebSocket）和 `/healthz` 到可配置 FastAPI 地址；原路径透传，不 rewrite。登录、图片和 WS 通过开发同源代理访问，避免依赖浏览器跨域 Cookie。
- Docker 采用 Node 构建阶段和现有 Python 运行阶段，复制 Vue 产物及迁移期遗留资源；更新 `.dockerignore` 排除 `node_modules` 和本地构建目录。本地启动文档明确先构建或使用 Vite 代理。
- `index.html` 不缓存，带内容哈希的构建资源可长期缓存；回退和部署必须原子替换整套资源，不能逐文件覆盖混用版本。

## 鉴权与权限

继续使用服务端 `aiyolo_session` HttpOnly Cookie。`auth/status` 负责首次 setup 判定，`auth/me` 恢复当前身份，登录/setup 成功后再加载业务；退出必须等待服务端撤销响应，失败时报告“退出未确认”，本地停止业务订阅。账号密码、`accessToken`、Cookie 和远端密钥不写入前端持久存储或日志。

管理后台面向 admin。operator 可按现有 API 读取模型、流、告警等，但当前统计、规则、转换和告警管理 WS 均要求 admin；operator 登录新管理后台显示权限说明及退出入口，不默认开放一个未经定义的完整操作员后台。后续验收需验证 operator 被限制，而不是假定双角色拥有相同菜单。前端守卫只改善交互，服务端仍是权限裁决点。

现有 `require_admin` 也会把角色不足表示为 401；处置接口则为 403。客户端不能自行把所有 401 定义为会话过期：业务 401 时只并发去重检查一次 `auth/me`，若会话有效显示权限不足，若失效进入登录。403 保留身份并显示操作拒绝。

## API Client 与类型策略

统一 JSON、文本、Blob、204 空响应、原始二进制上传和 AbortSignal 的处理；不全局覆写 `window.fetch`。类型在 `src/api` 显式定义，保留线上 camelCase/snake_case 字段，领域视图需要转换时使用独立 adapter，禁止在网络层全局重命名。

M32-T02/T03 在隔离测试环境导出当前 OpenAPI 快照，以接口与 DTO 对照验证变化。生成类型仅作辅助；JSON 包装（`events`、`models`、`jobs`）、运行时动态字典、WS 信封和错误响应仍需显式解析与测试。不得直接从生产服务导出含环境数据的快照。

默认 GET 可取消、可按上限重试临时网络故障。所有 POST/PUT/PATCH/DELETE、上传、复核、测试投递和转换重试禁止盲目自动重放；响应超时时先刷新事实状态，避免重复任务或审计。409、422、429、503 等保持接口原意，具体错误约定见配套清单。

模型与校准集上传是 `application/octet-stream` 原始文件体加查询参数，**不是 Multipart**。使用 XHR 保留真实字节进度、Cookie、取消和超时；该异常通过统一 API 模块封装。无法计算的转换进度显示不确定状态，不制造百分比。

## 实时与媒体

管理告警 WS 继续使用 `/aiyoloapi/alerts/ws`，消息为 `{type:"alert", event:...}`；检测旁路继续使用流的 `/detections`。使用同源 Cookie；浏览器无法按普通 fetch 方法设置 WS Authorization，不把 token 放进查询参数。

重连采用有上限的指数退避与抖动，退出、离开相关页面、切流时主动关闭并取消重连；4401 停止自动重连并检查身份，4404 刷新流列表，4429 显示订阅上限。重连完成后重新读取业务事实，不能把收到一条事件当成完整数据库列表。

MJPEG 仍是管理诊断预览，保持 `contain` 完整画面及每次重新启用新建请求；生产播放继续遵循 ADR-002 的 WHEP 主路径、LL-HLS 回退、RTSP 诊断边界。页面切换释放图像连接、播放器和检测订阅。诊断 JPEG WS `/streams/{stream_id}/ws` 当前没有调用会话鉴权，不作为新前端默认通道，不在此次迁移中暗中改造其后端。

## 对等范围与现有缺口

功能对等的目标是保持已实现行为，并用已有 API 接通清单明确列出的前端缺口；不存在的后端功能显示不可用及原因。推送目标 CRUD、复核供应商 endpoint/key/timeout 保存及连通性探测、多模型推理编排都缺少可用契约，不能用空接口、Demo 数据或成功提示代替实现。此类扩展必须先构建专门后端任务；不会因为 M32 页面迁移而获得实现依据。

规则已有 CRUD、绑定校验、审计 API，可在 M32-T08 接通；`RELATION`、`METRIC_THRESHOLD`、`COMPOSITE` 当前绑定返回 `OPERATOR_NOT_IMPLEMENTED`。每路 StreamSession 当前绑定单个模型。配置多条规则、独立多路视频与告警后复核，不等于同一路多模型并行识别或跨模型融合。

Demo 只允许显式进入并标记，不触发真实写入；模型资产和真实告警不使用 Mock 回退。现有问题不作为必须复制的行为，例如取消触发保存、配置失败仍报告成功、用静态项目名冒充实时状态。

## 灰度切换、回退与清理

1. T02–T04 搭建预览与公共层，`/admin/` 继续遗留。
2. T05–T09 逐页验证；任何未迁移页面在预览中标记状态并提供遗留入口，不假装可用。
3. T10 按全部清单验收 admin 与 operator 权限、桌面/窄屏、真实 RTSP、上传转换和重启；记录构建哈希、服务版本与未提交基线来源。
4. 保存含遗留静态目录的完整可回退部署包，验证 `ADMIN_FRONTEND_MODE=legacy` 重启恢复 `/admin/`；切换前实际演练，不仅写命令。
5. 将默认配置改为 vue，检查路由直达、资源缓存、会话和实时连接。出现关键功能失败则恢复上一完整部署包和 legacy 配置。
6. 只有回退包独立可用且无运行时引用后，才删除源码中的遗留静态实现。清理后回退依靠已验证部署包，不依赖已删除目录。

本地不提交、不推送、不部署生产。最终 `accept-major M32` 仍需真实验收，不由架构文档替代。

## 验证与影响

本任务只新增文档和 Harness 记录，不改变产品代码。验证包括源码路由/菜单/弹窗覆盖核对、现有管理页回归和 Harness 门禁；这些检查证明迁移计划有代码依据，不证明 Vue 页面已经可用。逐页实施时建立行为测试替代原有针对静态源码字符串的测试，后端 API 回归持续保留。
