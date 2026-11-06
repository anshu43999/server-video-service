# APK 统一核验器（M42-T02）

## 实现范围

`app/app_updates/apk_verifier.py` 供自有上传和外链核验共用；输入为有界读取的字节流，输出经过核验的不可变元数据。核验器不请求 URL、不持有对象存储凭据、不发布版本。`verification_jobs.py` 提供内部数据库 worker，后续 T03/T04/T05 接入存储和 HTTP 层。

流程：

```text
pending/failed → CAS claim verifying → 隔离文件快照 → 流式大小/摘要
→ ZIP 完整性/展开限制 → aapt2 包身份/版本/SDK/ABI
→ apksigner 真验签/批准证书 → 原始证据落盘
→ 身份行锁+高水位CAS+工件字段+审计 同事务提交 verified
失败 → failed+稳定错误码+证据引用+审计，不占用正式版本码
```

核验完成只表示字节和 APK 身份已确认；来源可达性、MinIO 提升、正式发布和安装许可仍需后续门禁。

## 工具与配置

服务配置新增：

| 配置项 | 要求 |
|---|---|
| APP_APK_AAPT2_PATH | 已安装 Android Build Tools 的 aapt2 绝对路径 |
| APP_APK_JAVA_PATH | 受控 Java 可执行文件绝对路径 |
| APP_APK_APKSIGNER_JAR_PATH | 同一受控 Build Tools 的 lib/apksigner.jar 绝对路径 |
| APP_APK_EVIDENCE_ROOT | 持久化、访问受限的核验证据目录 |
| APP_APK_STAGING_ROOT | 独立暂存目录，不与告警/模型目录共用 |
| APP_APK_MAX_BYTES | ≤8GiB，部署可降低 |
| APP_APK_TOOL_TIMEOUT_SECONDS | 单个工具超时，默认60秒，上限300秒 |

缺少任一工具禁止核验通过，不从 PATH 自动搜索。程序用参数数组直接调用工具，不调用 shell，不把业务环境令牌传入子进程。工具的版本、文件 SHA-256、stdout/stderr、退出码和耗时逐次留证。工具由运维安装、只读挂载并进行版本固定；API 输入不能指定命令或路径。当前部署镜像未自动添加 SDK，容器工具安装/许可证/挂载由后续部署门禁处理。

原生核验工具处理不可信输入，生产 worker 应在非特权隔离环境内运行，并设置 CPU/内存/磁盘配额。代码限制工具时间/输出、APK 总字节、ZIP 条目数（100000）及展开总量（16GiB）；网络 read 的阻塞必须由 T03/T04 的上传/HTTP 读取超时约束，本同步函数不能中断一个永久不返回的 stream.read。

## 校验规则

- 从实际完整流计算精确 sizeBytes 与 SHA-256；期望值存在时逐一比较。先生成核验器私有快照，避免管理员改动原始路径影响正在运行的工具。
- ZIP 不解压到目录，逐条流式读取验证 CRC；拒绝重复条目、加密、路径穿越、坏/截断 ZIP、非 APK/HTML、超量展开和未知 native ABI。
- `aapt2 dump badging` 和 `dump xmltree` 解析实际 binary manifest，读取 packageName/versionCode/versionName/minSdk/native ABI。无 native 库表示 ABI 无关，映射为 v1 全部四种 ABI。
- v1 完整包拒绝 split、uses-split、共享 UID、需要 split 的安装形态、versionCodeMajor 非零，以及未建模的 maxSdk 上限。无 classes.dex 时必须显式 hasCode=false，允许合法资源 APK；不接受 AAB/缺主 Manifest 的压缩包。
- 固定正式 packageName=com.aiyolo.inspection；首次正式核验码1，后续包级全渠道高水位递增。数据库在核验后重新锁定身份并 CAS，核验期间证书被撤销/替换会失败。相同已验证版本与字节返回原 artifactId；同版本不同字节拒绝。
- `apksigner verify --verbose --print-certs --min-sdk-version <实际minSdk>` 执行真实密码学验签，必须成功退出，且只有一个批准的证书；v1 要求 API27 可验证的 v2 签名，拒绝 v1-only、多签名和 Android Debug 证书。签名证书必须由运维先批准；无批准指纹不会自动建立信任。
- minSdk≥27，版本范围遵守 v1；可信 CI 的数据 schema/服务协议兼容证据由 `BuildCompatibility` 单独输入并验证，不能声称这些字段由 APK 自动证明。来源身份和 CI 证明的授权在后续管理 API 层处理。
- 工件 verified 后不可通过本 worker 重写，任何错误不会把未验证工件置为可发布；DB 不可用时事务回滚、不能返回成功。

调用方必须将**同一已核验字节**提升到不可变存储：依据返回 size/hash 再确认待提升对象，不能核验 A 后改路径分发 B。外链登记核验的临时 APK 删除后不保存常驻副本，设备仍会自行核对签名绑定的摘要；T04 实现该生命周期。

## 证据与日志

每次随机隔离目录保存 report.json 和各工具输出。report 包含字节身份、实际元数据、工具版本/摘要、开始/结束和状态；不包含第三方 URL、业务 Cookie/Bearer、签名私钥或密码。

内部 AppAudit 保存操作者、资源、任务随机幂等键、请求摘要、结果、错误码和证据引用。原始工具输出仅用于受限诊断，不能直接作为 API message 或 HTML 渲染；可能包含不可信包内容。后台未来只返回受控证据 ID/摘要，不能公开本机路径或任意文件读取。

私有核验快照无论成功失败均通过上下文清理，失败清理不会返回 verified。进程硬崩溃可能留下 verifying 和临时目录；T03/T04 持久队列负责租约重试/有界清理，不能盲目将 verifying 改为成功。

## 可重复验证

运行 `tools/accept_m42_apk.py --build-tools <BuildTools绝对目录> --java <Java绝对路径> --android-jar <android.jar绝对路径> [--product-debug <已有debug.apk>]`。

脚本复用 M42 隔离 PostgreSQL runner，专用临时端口和集群，不连接开发数据库。测试使用临时 keytool 密钥和 aapt2 生成合法 binary manifest APK，apksigner 实际签名。测试结束删除私钥和 APK，保留只含报告/工具输出的原始证据。测试证书绝不写入开发/生产身份登记。

覆盖实际签名通过、后续版本、未签名、篡改、错包名/证书/大小/哈希、HTML、截断、版本倒退、major code、产品 debug 证书拒绝；单元补充工具缺失/超时/错误退出/输出限制、ZIP/ABI和SDK边界；SQLite/PostgreSQL验证状态、重复工件、并发版本、证书撤销、失败审计与真实签名包持久化。

此验收不安装 App，不证明 CI 构建功能、业务逻辑正确或历史数据迁移安全；对应 Android M118 和 M42 联合验收继续保留。
