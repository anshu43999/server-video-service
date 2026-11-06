# M42-T06 平台管理员 App 版本管理后台验证

日期：2026-10-29。范围：FR-12 / M42-T06；本次不修改 Android 产品工程。

## 交付

- 后台「平台管理 → App 版本管理」新增发布版本、安装包与来源、操作审计三个台账，复用现有 PLATFORM_ADMIN 会话和导航权限。
- 接入真实版本管理 API：MinIO APK 上传、第三方公开 HTTPS 直链登记、为已核验工件新增外链来源、核验状态及最近 10 个作业、草稿、发布、停止分发和游标分页。
- 展示实际 APK 版本、大小、SHA-256、签名证书摘要、SDK/ABI 和兼容信息；支持普通、重要推荐及配置允许的在线兼容门禁。
- 配置扩展 GET /aiyoloapi/admin/app-updates/configuration 返回允许的 scope、门禁能力、大小限制和功能开关；逐次检查当前启用平台管理员、限流、no-store，不接受查询字段。
- 保留同表单幂等重试，CAS 冲突后锁定提交并要求刷新；上传进度达到 100% 仍等待响应，支持中断。详情轮询在关闭、离开或失权时停止，旧请求不能覆盖当前内容。
- 管理响应不包含原始下载 URL、查询参数、存储凭据、私钥和本机文件路径；更新说明按纯文本展示。
- 操作说明见 docs/app-update-service.md。

## 测试与证据

| 验证 | 结果 | 证据 |
|---|---|---|
| SQLite / 隔离 PostgreSQL 服务测试 | 32 项通过，覆盖配置、权限即时撤回、作业脱敏及现有发布/停止/签名/回执回归 | T06-20261029T061226Z-test_app_update_service.py.log |
| PostgreSQL 资源清理 | 随机端口 53902；专用临时集群，测试 schema 已清理、端口已关闭，未使用开发数据库 5432 | T06-20261029T061226Z-result.json |
| 前端 Vitest 全部测试 | 22 个文件、141 项通过，其中版本管理新增 7 项 | T06-vitest.log |
| 类型检查及生产构建 | vue-tsc 和 vite production build 通过 | T06-build.log |
| 生产资产 Playwright | 6 项通过，1440px / 390px 布局及无横向溢出、长说明纯文本、双来源、门禁发布、停止/审计、空态/失败重试/409、上传进度与取消、键盘和权限拒绝 | T06-playwright.log |
| Harness 单元测试 | 34 项通过 | T06-harness.log |

上述日志和截图均位于本文件所在目录。截图：T06-ledger-1440.png、T06-ledger-390.png、T06-detail-1440.png、T06-detail-390.png。

可重复命令：

```powershell
# server-video-service 工作目录；runner 自动创建和清理隔离 PostgreSQL
.venv/Scripts/python.exe -c "from tools.accept_m42_contract import main; raise SystemExit(main(task='T06', patterns=['test_app_update_service.py']))"

# admin-web 工作目录
npm run test -- --run
npm run build
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE='C:\Users\45393\AppData\Local\ms-playwright\chromium-1234\chrome-win64\chrome.exe'
npm run test:e2e:production -- app-updates.spec.ts --workers=1
```

## 环境失败与重试

- 首次服务 runner 在沙箱内创建临时目录遇到 Windows 权限错误；按权限流程重跑后通过。保留 T06-20261029T061212Z-result.json，不覆盖失败证据。
- 默认 Playwright Chromium 1248 未安装；使用本机已安装 Chromium 1234，未新增依赖或下载浏览器。首次通过日志 T06-playwright-attempt1.log 保留，最终重新构建后结果见 T06-playwright.log。
- npm 存在用户级 home / sass 配置告警，未导致类型检查、测试或构建失败。

## 验证边界与后续

- 浏览器使用真实生产构建和确定性 App 版本 API fixtures；上传进度使用模拟传输事件。它验证界面接线和交互，不能替代真实后台到 MinIO / 外部托管文件源的联合验收，后者属于 M42-T09。
- 本次未部署生产；升级默认关闭。正式证书批准、独立元数据密钥、scope 配置及公开 HTTPS 下载入口仍需上线配置。
- 停止分发只停止新下载地址与安装许可签发，公开链接和已交接系统安装器的操作无法追回。
- 快速回退的影响预览、原子停止与高版本恢复属于 M42-T07；安全专项属于 T08；Android 覆盖安装与历史数据保护属于 M118 / M42-T10，均未在本次计为完成。
- 沿用 T05 的 MinIO 验证边界：本机 HTTP 存储通过测试 TLS 网关验证；正式公网 S3 HTTPS 网关尚未验收。
- 未新增依赖，未提交或推送 Git；没有阻断 T06 完成的已知问题。
