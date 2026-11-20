# M34-T05 无预览消费者告警持久化与独立通知验收

日期：2026-10-15（Asia/Shanghai）。范围：服务端与 PC 管理后台。仅本地隔离测试，不部署容器，不修改 Android 产品工程。

## 结论与边界

本小任务的服务端/PC 自动化验收通过：没有 PC 预览或通知订阅者，规则仍可生成并持久化正式告警与 JPEG 证据；PC/移动告警接口独立于视频；PC 全局提示支持补取、事件去重、项目清空和撤权。

这不是 M34 整体或真实三端验收通过。推理输入是受控结果，浏览器正式事件由仅测试服务中的夹具登记。真实本地视频源、YOLO 模型、PostgreSQL、API27 产品消费及持续运行由 M34-T06 联合 Android M101 验收。

## 实施内容

- `app/alerts/runtime.py`：恢复活动告警时不再把人工 ACK 当作检测结束；结束事件成功提交后才释放活动状态、进入冷却。失败可继续重试，避免重启或结束写库失败产生重复告警。
- `app/alerts/delivery.py`：通知发送和投递回执写库分别重试；回执库失败不重复发送已成功通知。写库耗尽保留实际发送状态及 `receipt_persistence_failure`，恢复后按项目显示进程内诊断；策略读取失败安全结束投递。
- `app/main.py` / `app/project_auth.py`：PC/移动告警 WS 每次发送前及空闲每秒复验会话、成员和项目状态；撤权/停用后关闭，不等待下一条事件。断开时取消等待任务并退订，重复复验不反复写进入审计。
- PC 全局 `AlertSync` / `AlertNotifications`：首次历史基线、连接恢复补取、5 秒 REST 兜底；新正式事件按项目/eventId 去重；慢列表不得擦掉期间收到的事件，旧 OPEN 重放不得覆盖人工处置。提示只提供告警处置语义，不提供移动直播入口。
- 切换项目/失效时清空通知与事件并释放连接和计时器；整机断网恢复仍需重新验证并选择项目，不放宽原有安全门禁。
- 按 frontend-design 技能检查实际布局，沿用现有 Element Plus 管理后台样式；通知占用正常布局空间，避免固定顶层通知遮挡标题。
- 文档契约：`docs/independent-alert-notifications.md`，并由 ADR-003 和视频协议交叉引用。

## 最终测试结果

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 后端 16 模块广回归 | 114/114，通过，95.788 秒 | `M34-T05-backend-final.log` |
| PC 单元测试 | 18 文件、141/141，通过 | `M34-T05-frontend-final.log` |
| 正式构建和类型检查 | 通过 | `M34-T05-build-final.log` |
| 预览构建和类型检查 | 通过 | `M34-T05-build-preview-final.log` |
| 正式构建浏览器回归 | 40/40，通过，约 1.2 分钟 | `M34-T05-browser-final.log` |
| 完成前 Harness 单元测试 | 30/30，通过 | `M34-T05-harness-tests.log` |
| 完成后 Harness 门禁 | 30/30、validate/render 通过；show 为 completed；next 包含 T06 | `M34-T05-harness-final.log` |
| 定向 `git diff --check` / Harness validate | 通过；仅换行符提示 | 本轮命令输出 |

新增后端 15 项用例：`tests/test_analysis_alert_closure.py`（9）和 `tests/test_alert_notifications_closure_api.py`（6）。新增 PC 同步单测 8 项及旧 socket 迟到回调竞态单测 1 项。浏览器新增 2 项真实本地 API/WS 用例，分别为 1440px 和 390px；其余 38 项覆盖告警、项目权限/切换、配置业务、外壳、预览和看板。

### 覆盖矩阵

| 场景 | 验证事实 |
| --- | --- |
| 无预览/无订阅者 | 正式事件唯一；JPEG 可读取；新连接从 REST 查到同一事件 |
| 检测与告警区分 | 未满足连续帧规则不入库；仅满足规则后的正式事件进入两条告警通知通道 |
| 预览开关 | 打开 PC 鉴权预览前后事件和通知数量不重复；分析不靠消费者触发 |
| 持久化与恢复 | 确认写库、证据写入失败不提前通知；结束写库失败可重试；ACK 重启、冷却重启不重复 |
| 通知失败 | App 通道重试耗尽不回滚事件；管理通道独立；回执写库失败不重发已成功通知 |
| 通知重连 | REST 补取丢失事件，WS 重放/轮询不重复提示 |
| 整机离线 | 清空旧项目可见内容；重新验证后加载历史，不逐条弹旧通知；后续新事件可提示 |
| 项目安全 | 切换清空、旧请求/旧 socket 不污染新项目；成员撤权和停用关闭连接；跨项目读取拒绝 |
| 媒体隔离 | 保留 streamId；移动 Bearer 不能获取 PC 预览；旧播放/检测订阅继续拒绝；新增提示流程不请求视频 |

### 可复现命令

从 `E:\aiyolo\server-video-service` 执行，测试显式清空 `DATABASE_URL`、`MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`，不连接业务数据库：

```powershell
$env:DATABASE_URL=''
$env:MINIO_ENDPOINT=''
$env:MINIO_ACCESS_KEY=''
$env:MINIO_SECRET_KEY=''
$env:PYTHONPATH='tests'
./.venv/Scripts/python.exe -m unittest test_analysis_alert_closure test_alert_notifications_closure_api test_server_alert_runtime test_analysis_only test_alert_delivery test_alert_delivery_api test_alert_disposition test_alert_disposition_api test_alert_evidence test_alert_persistence test_project_alert_isolation test_project_authorization test_project_business_configuration test_admin_preview test_stream_restart_recovery test_project_isolation_matrix -v
```

从 `E:\aiyolo\server-video-service\admin-web` 执行（同样隔离数据库和对象存储环境变量）：

```powershell
npm run test
npm run build
npm run build:preview
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE='C:/Program Files/Google/Chrome/Application/chrome.exe'
npm run test:e2e:production -- alert-notifications.spec.ts alerts.spec.ts projects.spec.ts project-business.spec.ts shell.spec.ts streams.spec.ts dashboard.spec.ts --workers=2 --output=test-results-m34-t05-closure
```

## 失败记录与修复

保留失败日志，不以最后一轮成功覆盖问题轨迹：

1. `M34-T05-initial.log`：复现 ACK 重启重复、结束入库失败丢失活动状态、回执失败重复发送三项产品缺陷；已修复并纳入最终后端回归。
2. `M34-T05-notification-api.log`：初轮删除成员夹具漏传 revision，以及 ASGI 取消期间退订清理被打断；分别补齐真实 API 参数、保护 finally 清理，最终全部通过。
3. `M34-T05-browser-initial.log`：整机离线恢复测试错误假设自动恢复项目；列表错误夹具只失败一次，被合法自动补取恢复。测试改为明确重新验证和可控故障窗口，不削弱产品安全门禁。
4. `M34-T05-browser-verified.log`：文件名不代表成功，该轮为 **31 通过、9 失败**。7 项源于旧项目告警夹具缺少 `projectId`，2 项外壳测试未模拟新全局 WS、误连真实鉴权端点。补齐夹具真实契约与 WS 路由模拟后，最终 `M34-T05-browser-final.log` 为 **40/40**。
5. 窄屏截图发现固定顶部通知遮挡标题，改为内联布局；新增通知底部不超出主体顶部、无横向溢出的浏览器断言。

最终截图已人工查看：`M34-T05-notices-1440.png`、`M34-T05-notices-390.png`。标题、项目切换、通知关闭和告警列表均未被通知覆盖；390px 无页面横向溢出。截图事件属于测试数据，不是摄像头识别结果。

## 未完成项与运行限制

- Android 产品入口退役、告警消费与设备验收仍归 M101，本轮未修改 Android，也未宣称设备端已完成。
- M34-T06 未执行：真实源/YOLO/PostgreSQL/API27、重启/断流恢复及持续运行仍需本地联合验收，不能以这些隔离自动化替代。
- WS 为非持久加速通道，无订阅者时不会排队等候手机客户端。移动 App 关闭后的 OS 推送未接入；现有邮件/短信/IM 本地适配器不等于真实供应商通道。
- 没有持久 outbox 或分布式恰好一次投递保证；进程崩溃后的外部通知补发仍有限制。回执持久化失败诊断只保留在进程内；证据成功而事件失败可能遗留孤立证据，本轮不清理业务文件。
- 未重启用户现有服务、未迁移或清理业务数据库、未部署容器、未提交/推送 Git。沿用先本地验收、后容器部署顺序。
- 依赖日志中既有 npm 配置提示、NO_COLOR/FORCE_COLOR 提示及 Starlette/httpx 弃用提示，不影响本次通过结果；本轮不扩大为依赖升级任务。
