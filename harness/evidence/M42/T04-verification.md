# M42-T04 外链 APK 核验验证

## 范围

实现两个冻结管理接口：external-artifacts、artifact download-sources；先认证再读取有界JSON，当前启用PLATFORM_ADMIN，完整异步HTTPS抓取，统一aapt2/apksigner核验，来源修订/幂等/队列租约，失败和崩溃清理。外链不进入MinIO，没有业务下载代理路由；不改变Android。

网络代码逐跳限制HTTPS443、允许域名、DNS全部结果和连接IP固定，TLS/SNI校验、禁止环境代理及业务认证头，整体/空闲期限、有界响应与HTML/截断拒绝。Range缺失记录为false，仍支持全量。迁移20261029_29在既有队列表增加外链类型与必要元数据，无新增Python依赖。

## 测试

主命令：`.venv/Scripts/python.exe tools/accept_m42_external.py --build-tools D:/Users/45393/Android/sdk/build-tools/36.0.0 --java C:/Users/45393/.jdks/jbr-21.0.11/bin/java.exe --android-jar D:/Users/45393/Android/sdk/platforms/android-36/android.jar`。

- 最终整合运行：`T04-20261029T054328Z-result.json`，外链21项（包含真实TLS/API/SDK/PG两项）、上传16项、统一核验worker12项、迁移18项、数据库6项、契约6项。每项日志同时间戳保存。
- 实际TLS核验另有独立通过记录 `T04-real-final-20261029T054251Z-result.json`，原始证据 `T04-real-final-raw/external-tls-integration.json`，真实v2签名测试APK 24796字节，经302→200完整抓取和正式核验；Cookie/Bearer未外发，换文件拒绝，无暂存APK残留。
- 最终增加外链历史降级拒绝测试，结果在 `T04-migration-final-*-result.json`；该轮其余外链单元和SQLite/隔离PG持久化用例同时运行。
- Harness34项通过，日志 `T04-harness-tests.log`；compileall、相关diff空白校验通过。

数据库均为runner单独initdb集群，显式角色aiyolo_app、随机非5432端口、postgres库；运行前校验data_directory/角色/端口，测试后检查schema清理，停止专用集群并验证端口关闭；不访问aiyolo_dev。

## 修复轨迹

- `T04-20261029T053837Z-result.json`：沙箱新建临时目录不可写；审批后在沙箱外重跑。
- `T04-20261029T053848Z-result.json`：真实TLS用例暴露Content-Length读完后socket已关闭，下一次设置超时导致WinError10038；修复为只在仍需网络读取时设置超时，保留整体定时中断。
- `T04-20261029T054152Z-result.json`：产品核验成功，测试临时APK构建目录与外链暂存目录同名造成清理断言包含fixture；改名后独立真实测试和最终整合通过。历史失败记录保留。

## 证据限制与后续

真实HTTPS为测试期间生成CA/证书的可控源，测试工厂将已检查公网fixture IP映射到本机监听；生产代码无私网/跳过TLS配置开关，另有连接IP固定与SNI单元测试。没有声称公网第三方实际域名或Android下载安装已经验收。

未配置正式证书、未启用服务、未部署/提交Git；测试证书仅限随机隔离数据库。实际第三方域名、正式包签名、后台页面、发布/停止/下载票据/回执与Android覆盖安装由现有M42-T05～T10和M118承接。第三方文件核验后仍可能替换，最终下载必须按冻结SHA-256及APK签名再验证。

URL仅保存为必要来源元数据，审计/异常不回显URL；公开URL参数不应携带秘密。私有持久暂存卷及清理权限由部署配置保障。后续管理接口须投影稳定错误码与rangeAdvertised，不能把它解释为已实测Range。
