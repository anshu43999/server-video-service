# M42-T09 双来源服务端与管理后台真实验收

## 验收边界

本记录覆盖本地服务、后台生产构建、隔离 PostgreSQL、真实 MinIO 和受控 HTTPS 源。正式 Android App、生产签名、真实公网域名及厂商设备安装不在本次通过范围；M118 和 M42-T10 继续负责。

## 真实联合结果

最终联合运行：`T09-live-20261029T070606Z-result.json`，passed=true。随机端口 51991，remainingTestSchemas=[]，portClosed=true。外层集成用例 1 项通过（122.387 秒），内含无 API 拦截的 Playwright 3 项通过。未读取或修改 5432 开发业务数据库。

证据根目录：`T09-20261029T070606Z-live/`。

| 场景 | 实际执行与断言 | 证据 |
|---|---|---|
| 自有托管 | 后台上传真实 APK→完整 SDK 核验→真实版本化 MinIO；固定 versionId/SigV4 下载，核对 SHA-256 和大小 | browser.log、database.json、gateway.json |
| 第三方托管 | 后台登记 HTTPS 直链与允许域名、302 重定向、同包镜像完整下载核验 | browser.json、origin.json、database.json |
| 普通升级 | 100 稳定发布后客户端取真实 MinIO 字节；两管理员竞争发布 101 后客户端取真实外链字节，并取得已验签安装许可；停止 101 后 100 设备无升级 | service.json、http.json |
| 双来源恢复 | 两范围各完成 100→101→无恢复包止损→102 恢复；102 分别绑定内部与外部来源，客户端直连取字节并核对下载授权和安装许可签名 | service.json.network、database.json、gateway.json、origin.json |
| 策略与设备区分 | 当前 100 继续稳定；当前 101 得到 102 recovery，停止版本地址返回 410；没有启动/健康回执不统计 healthy | service.json、http.json |
| 带宽路径 | 外链 APK GET 前后业务 HTTP 数量及 MinIO 网关访问数量不变，只有第三方源新增请求；第三方未收到业务 Cookie/Authorization | service.json、http.json、gateway.json、origin.json |
| 真实账号权限 | 两 PLATFORM_ADMIN 可操作；真实项目负责人和项目用户无管理入口、API 返回 403；管理员会话建立后降权再写也返回 403 | browser.log、http.json、service.json |
| 并发与幂等 | 两管理员同修订发布同一草稿仅一个 200、一个 policy_revision_conflict 409；数据库仅一次成功发布和修订 2→3；发布/停止/回退同请求重放不新增操作 | service.json、database.json、http.json |
| 来源故障 | 403、404、429、503、HTML、错包名均失败；原 101 地址替换为 102 字节，拒绝 external_file_changed；失败作业清理完成 | service.json、database.json |
| 重启 | 停 worker 后登记作业，关闭数据库连接池并重建 HTTP/worker，队列任务恢复完成，随后 check 正常 | service.json、http.json、database.json |
| 浏览器布局 | 1440/390px 操作结果截图；390px 文档无水平溢出 | recovery-minio-1440.png、recovery-minio-390.png、recovery-external-1440.png、recovery-external-390.png |
| 清理 | 全部临时 APK 作业清理；随机 MinIO 桶及其全部 versions 删除，随机 schema 删除，PG 监听端口关闭 | bucket-cleanup.json、运行 result.json |

## 回归门禁

- 前端类型检查和生产构建：通过，`T09-build.log`。
- 前端单元测试：22 个文件、142 项通过，`T09-frontend-tests.log`。
- 生产构建交互回归：9 项通过，`T09-browser-regression.log`。这些用例使用确定性接口 fixtures，仅作为交互回归；真实联合证据为上表的独立运行。
- Harness：34 项通过，`T09-harness-tests.log`；收尾复核 34 项通过，`T09-harness-final.log`。
- 本次新增入口、真实联合测试辅助代码及修改的核验器测试已通过 Python compileall。
- 后端完整升级/APK/迁移回归：`T09-final-20261029T072026Z-result.json`，passed=true。随机端口 50920，remainingTestSchemas=[]，portClosed=true；三批进程退出码均为 0，共 176 项，174 通过、2 项条件跳过。
  - `test_app_update_*.py`：105 项，104 通过、1 项条件跳过（265.946 秒）。跳过的是独立 live browser 用例，该用例已在 `T09-live-20261029T070606Z-result.json` 真实通过。
  - `test_apk*.py`：65 项，64 通过、1 项条件跳过（149.848 秒）。SDK、真实 MinIO 和受控 TLS 条件全部开启；未提供现有产品 Debug APK，故对应证书拒绝用例跳过，不据此宣称现有产品包已验收。其余真实 SDK 签名、篡改、错包名、未签名及版本拒绝用例通过。
  - `test_database.py`：6 项通过（2.330 秒）。升级表迁移、重跑和拒绝不安全降级同时由前两批的 SQLite/PostgreSQL 用例覆盖。
  - 该批真实双来源下载证据 `T09-final-20261029T072026Z-raw/delivery-integration.json` 证明两来源均通过签名下载授权、实际字节摘要及安装许可验证，专用测试桶已删除。
  - `T09-final-20261029T072026Z-raw/minio-integration.json` 证明真实上传、固定对象版本与重复工件复用，专用桶已删除；`external-tls-integration.json` 证明真实 302/TLS 下载、同地址替换拒绝及不保留常驻副本。

## 保留的失败和修复

1. `T09-live-20261029T065842Z-result.json`：沙箱临时目录权限错误，数据库未启动；经正常提权运行。
2. `T09-live-20261029T065858Z-result.json`：本机未安装 Playwright 默认期望的 Chromium 1248。入口改为显式提供已安装 Chromium 1234 路径；未安装新依赖。
3. `T09-live-20261029T065956Z-result.json`：早期联合运行通过，但未补足两管理员真实并发和 MinIO 恢复包供应，不能单独作为 T09 完整通过依据。
4. `T09-live-20261029T070330Z-result.json`：补足内部恢复包后，MinIO 来源检查一度返回 source_unavailable（503），浏览器 5 秒结果等待先到期。保留失败 trace 和审计；新增仅记录固定异常类型的测试诊断并将真实测试结果等待设为 30 秒，后续相同 MinIO 恢复链完整通过。未捕获该次 SDK 根因，不宣称修复了生产存储故障，也不添加隐式业务代理或换源。
5. `T09-regression-20261029T070411Z-result.json`：自定义回归任务未设置 SDK 证据目录导致 3 个 KeyError；另正常退出 Python 子进程在负载下超过 0.3 秒，被误当超时。runner 为所有任务设置默认独立证据目录，短超时仅用于实际 sleep 场景，退出码/超量输出场景允许 5 秒；生产核验时限未修改。原失败证据保留。
6. `T09-regression-fixed-20261029T071204Z-test_app_update_all.py.log`：105 项中有 1 项错误、1 项条件跳过；真实 MinIO 创建专用测试桶时出现 `RemoteDisconnected`。同一真实双来源用例单独复核 `T09-delivery-recheck-20261029T071644Z-result.json` 已通过，schema 清空、临时端口 61201 关闭。该批 APK 日志停在首项 SQLite 上传用例且没有最终汇总或 result.json，只能视为中断，不能据此认定整批通过。原 PostgreSQL PID 已不存在，精确 data directory 的 pg_ctl status 确认无服务运行；陈旧 PID 文件及失败日志保留。随后启动独立临时集群的完整最终回归，未添加生产自动重试或隐式切源来掩盖存储异常。

## 限制及后续责任

- 测试 APK 由 aapt2/apksigner 和一次性证书生成，是资源型测试包；恢复兼容证据为明确的 test-only fixture。尚未证明正式 App 数据保留、数据库迁移兼容或安装后恢复业务行为，由 M118/M42-T10 验证。
- 受控 TLS 测试地址通过测试连接工厂映射到回环；真实 MinIO 为当前配置的 HTTP endpoint，独立 TLS 测试网关验 SigV4 后用 SDK 取固定 versionId。生产 HTTPS S3 网关、第三方托管商及公网 DNS 尚待配置和验收。
- 重启为进程内 HTTP/worker/数据库连接池重建；主机断电、跨主机迁移及存储 SLA 未覆盖。
- 网络证据是服务路由记录、源站 GET 和存储读取的数量/身份断言，不是生产公网链路的流量抓包，也不替代 Android 下载器验证。
- 一次来源不可用已保留，正式运行仍可能出现外部存储故障；当前行为为失败关闭及用户重试，第一阶段没有自动故障切源。
- 无生产部署、Git 提交或推送。
