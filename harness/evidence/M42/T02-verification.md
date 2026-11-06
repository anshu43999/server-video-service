# M42-T02 APK核验器验证

日期：2026-10-29；任务范围为统一字节核验器和内部持久 worker。

## 结果

- 真实 SDK/签名及核验器：11项通过，无跳过；`T02-20261029T045030Z-test_apk_verifierall.py.log`。
- SQLite/隔离 PostgreSQL worker：12项通过，无跳过；`T02-20261029T045030Z-test_apk_verification_jobs.py.log`。包含真实签名 APK 持久化、同版本并发只保留一个 verified 工件、证书撤销、重复字节、首包版本、失败重试和异常审计。
- 既有升级契约：6项通过；数据库/health回归：6项通过。对应同时间戳日志。
- 最终相对暂存目录修复后的核验单元复验：8项通过；`T02-unit-final.log`，确认传给工具的快照路径始终绝对。
- 服务端 Harness：34项通过；`T02-harness.log`。compileall 与改动空白检查通过。

隔离实例结果：`T02-20261029T045030Z-result.json`，专用端口63371，data directory `.tmp/m42-contract-socsk3nf/pg-data`，aiyolo_app/postgres。已核对实例身份，测试 schema已清理、实例停止、端口关闭。没有连接/修改5432开发库。

## 真实工件与工具

测试通过 aapt2 link 生成 binary AndroidManifest，keytool 临时生成独立测试证书，apksigner实际 v2签名；临时证书没有写入开发/生产配置。测试包包括版本1/2、错包名、非零major、未签名、篡改、截断和HTML。已有产品debug APK只读用于确认 Android Debug证书被拒绝，没有重新构建或安装产品App。

Android Build Tools36.0.0：aapt2 2.20-13193326，apksigner0.9，Java21.0.11。工具摘要和每次完整stdout/stderr/退出码/时长存于 `T02-20261029T045030Z-raw/`。该目录只保留核验输出；检查没有p12私钥，临时key和APK由测试上下文清理。

## 修复轨迹

- 沙箱临时目录拒绝访问，按工具审批移到沙箱外执行。
- 单元发现split属性匹配需要允许零缩进，已修复。
- 首次真实测试发现aapt2 version写stderr，报告缺版本，已同时读取stdout/stderr；首轮失败日志保留于 `T02-real-first.log`。
- 最终检查发现默认相对staging目录在工具cwd改变后会解析错误；改为绝对快照路径并增加回归，8项通过。

## 后续边界

- 未新增网络登记/上传/发布路由，MinIO提升与第三方直链登记由T03/T04接入同一核验器；管理员鉴权和发布由T05/T08处理。
- 容器需提供受控SDK工具和证据持久卷。配置缺失、无批准生产证书时不能核验通过；此次未登记正式签名身份。
- BuildCompatibility为可信CI声明，不由APK自动证明，后续API必须校验其授权/来源。已验证字节提升到存储前还需核对同一hash，不能换文件。
- 硬崩溃verifying任务租约与暂存清理由T03/T04负责；当前异常失败已落failed与审计，DB不可用则回滚不返回成功。
- 尚未进行MinIO/外部HTTPS发布、Android覆盖安装或历史数据迁移验收，不以测试签名包替代正式放行。
