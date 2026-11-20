# M42-T13 当前环境升级服务启用

日期：2026-11-06（Asia/Shanghai）。用户明确要求启用现有后端，不新建环境，不自动创建或发布版本。

## 范围与需求

依据 PRODUCT_REQUIREMENTS.md FR-12，开启管理员手工托管APK、填写外链、完整核验、创建草稿与独立发布路径。M42-T12仅完成禁用态准备，M164已交付同正式签名v1/v2，M165已安装真机v1；本任务不重开既有任务，也不关闭M42-T10/Android M118联合验收。

仅修改环境中三个键：APP_UPDATES_ENABLED=true、APP_APK_EXTERNAL_ENABLED=true、APP_APK_COMPATIBILITY_PATH指向工作区公开兼容声明。APP_APK_WORKER_ENABLED=false保持不变，它是MinIO上传专用worker开关，不是外链worker；外链worker由APP_APK_EXTERNAL_ENABLED在服务lifespan单独启动。因此不要求MinIO凭据，也未把其他上传功能显示为已配置。

兼容声明路径：E:/aiyolo/config/app-updates/compatibility-http-trial.json。依据和限制详见M42-T13-compatibility.md；仅声明当前已核对v1/v2的serverContract=1和schema=20到20，没有声称覆盖安装、旧schema迁移或恢复已验收。

## 执行与回退

- 原.env备份在backups/M42-T13-enablement-20261106/environment-before.env，关闭继承并限制为当前用户/SYSTEM/管理员可读写，摘要匹配。备份含敏感配置，不公开内容。
- 重启前健康检查status=ok，streams=0；精确核对0.0.0.0:8080监听PID34060、父进程22220及完整uvicorn命令。
- 同一工作目录/虚拟环境/host/port重启成功：新启动器8348，服务监听14808；没有操作PostgreSQL、前端5173、手机或其他服务。
- 启动日志确认Application startup complete；live health仍status=ok，PostgreSQL schema ready，streams=0。受限备份目录保存stdout/stderr；保留原环境可回退。
- 脚本工具：tools/restart_app_update_trial.ps1（精确进程身份和健康/空闲门禁）、tools/check_app_update_enablement.py（只读快照、真实签验与接口检查）。

## 验证

1. 两份M164原始APK的大小/哈希和v2签名复查成功；升级签名器与手机预置独立公钥匹配，内存非安装授权自检消息签验通过；configured_updates与configured_external构造成功。
2. 真实后台8080管理员configuration返回200，externalEnabled=true、uploadEnabled=false，scope为aiyolo/com.aiyolo.inspection/enterprise-stable/primary；artifacts/releases均200。
3. 真实前端5173代理同样返回上述200及开关；页面代码“新建版本”的禁用条件为!config.externalEnabled或busy，因此刷新完成后配置阻塞解除。未声称做了浏览器可视点击测试。
4. 未登录configuration仍401；已登录空外链请求被422拒绝，没有新建工件。检查仅使用文档化本地管理员会话，结束后退出；不输出或保存Token/密码。
5. 六个受保护业务表与11个升级表的行数及规范化摘要前后一致，版本水位未变化、APK工件和发布仍未创建；会话登录/退出是明确的验证副作用。
6. 除上述三个APP键之外，.env内容按行对比保持不变。
7. test_apk_external.py：13通过、8跳过；test_app_update_service.py：17通过、15跳过；test_app_update_contract.py：6通过。合计36通过、23个独立PostgreSQL测试跳过；临时测试库未使用真实业务数据库。Harness34通过。

原始公开证据：M42-T13/preflight.json、M42-T13/live.json、M42-T13/frontend-proxy.json。首次live检查早于服务启动就绪，返回ConnectError；服务就绪后重试成功。一次临时命令行代理检查因PowerShell转义导致测试凭据解析失败，未输出实际密码/令牌；改用文件中的正确解析后，完整live代理检查通过。

## 未完成与用户下一步

- 没有上传/托管APK或登记v1/v2，也没有自动发布、提高兼容门槛或修改版本水位。刷新后台后先登记核验v1，再创建v2草稿及按需发布。
- APK外链仍由用户逐版提供公开HTTPS文件直链，保留现有SSRF/地址/签名校验；业务与升级API继续当前HTTP。
- 尚未有实际文件URL，因此外链实际下载/第三方可达性、v1到v2手机在线覆盖安装、数据保留、双来源与高版本恢复未验证。
- 未来不同APK构建需重新评审兼容证据，不应无条件沿用当前声明。
- M42整体和生产发布门禁未通过；未提交或推送Git。
