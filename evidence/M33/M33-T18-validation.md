# M33-T18 本地联合验收进展（未完成）

日期：2026-10-13。依赖决策见 docs/m33-local-acceptance-sequence.md。T18 原全流程标准不变，容器部署不再是本地验收前置。

## 已执行

工程根目录执行：

- ./.venv/Scripts/python.exe tools/accept_local_project_baseline.py --postgres-bin D:/PostgreSQL/bin --chrome "C:/Program Files/Google/Chrome/Application/chrome.exe"
- ./.venv/Scripts/python.exe -m unittest discover -s tests -p test_local_project_baseline.py -v
- python -m unittest discover -s harness/tests -p 'test_*.py'
- python harness/harness.py validate / render

原生临时 PostgreSQL，空库运行 Alembic 全迁移；完整 app.main:app 副本在独立回环端口启动，无路由替身、无授权 mock、无浏览器接口拦截。独立副本不包含 .env、真实模型注册表/模型文件或线上数据；环境变量白名单不继承数据库、对象存储和外部服务凭据。生产鉴权模式、动态 Session；临时 PostgreSQL trust 只监听本机回环，不用于正式部署。

通过真实 HTTP 创建平台管理员、两个负责人、两个用户、双项目和成员关系；核对 /auth/me 身份契约、项目目录过滤、项目与流/告警/模型/规则/统计跨项目 404、平台账号和成员/流写操作 403。

真实 Chrome 加载现有 production 构建：平台可见双项目；负责人读取成员；项目用户只读页面和直接写入拒绝；刷新和 390px 无横向溢出。首次截图捕获了缩窄窗口时侧栏 180ms 过渡过程，已补充侧栏边界等待及禁用截图动画，并重新完整执行通过；没有以裁切截图作为视觉通过证据。

后端进程与 PostgreSQL 实际停止重启后，原 Session 与项目关系仍可用；移除成员后原 Session 立即 404、项目目录为空；归档后平台管理员也不能写流。两次原生实测均 exit 0，最终机器报告为 M33-T18-local-baseline.json，明确 passed-partial。临时进程停止、临时合成数据删除，未改变线上数据库或 MinIO。

新增安全/依赖回归 2/2 通过。Harness 30/30 通过（首次沙箱临时目录权限导致 4 errors，经审批在沙箱外重跑通过）。

截图：M33-T18-local-platform.png、M33-T18-local-owner.png、M33-T18-local-user-390.png。

## 不得计为通过的范围

本次模型目录、流与事件列表为空，只证明真实存储/鉴权基线，不证明有数据业务、同 ID 隔离、模型分配/下载/撤回、实际推理、告警上传/处置/证据、MinIO 对象读写、WHEP/LL-HLS/WebSocket、历史升级兼容或长时稳定性。

Android 只读预检：Harness validate 通过，M100 仅 T01 完成，T02–T14 共 13 项 pending；代码 AuthUser/AuthSession 仍是旧身份结构。固定 SDK adb 的设备列表为空。不能拿旧 APK 或模拟客户端签署联合通过。

T18 等待 M100 实现及现场证据，不能执行 complete；下一工作项为 Android M100-T02。T17 仍保留部署验收，且须在 T18 通过后执行。历史数据 167 条孤立回执正式处置、在线对象存储修复、容器安装和正式切换均未执行。
