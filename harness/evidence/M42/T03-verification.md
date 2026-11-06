# M42-T03 验证证据

## 实现范围

- 平台管理员会话认证先于读取上传流，旧 token 拒绝，接收后与落库前重检当前权限。
- 有界 multipart 单 APK 流式暂存；大小、总超时、空闲接收超时、容量、字段及头限制；幂等、同版本冲突与失败审计。
- 持久队列领取 CAS、token fencing、过期任务恢复、存储重试、删除失败恢复；默认关闭 worker。
- 专用 MinIO 版本桶，摘要对象键，保存 versionId/ETag/sourceRevision，全量 GET 核对大小/SHA-256，复用统一真实 APK 核验器。
- 迁移 20261029_28，新表 app_apk_uploads；不改开发数据库。

## 验证命令及结果

验收命令：`.venv/Scripts/python.exe tools/accept_m42_uploads.py --build-tools D:/Users/45393/Android/sdk/build-tools/36.0.0 --java C:/Users/45393/.jdks/jbr-21.0.11/bin/java.exe --android-jar D:/Users/45393/Android/sdk/platforms/android-36/android.jar`。

主要证据：`T03-20261029T053010Z-result.json` 和同时间戳的六份测试日志：上传14项、存储2项、核验worker12项、迁移18项、数据库6项、契约6项。测试使用隔离 PostgreSQL，进程内验证 data_directory、端口与角色，结束检查 schema 清理与端口关闭。

补充最终权限先行/legacy拒绝/断线测试：`T03-final-upload-unit.log`，10项 SQLite/API 实际执行通过，6项 PG 不在该单独调用中运行（此前隔离 PG 已通过）。

真实端到端：`T03-20261029T053010Z-raw/minio-integration.json`。真实账号会话 multipart 返回202；临时正式形态 v2 签名测试 APK 24796 字节，受控 SDK 校验；真实 MinIO 未启用 versioning 时保持 retryable，启用测试桶 versioning 后恢复成功；同 key 后续写入不改变已固定旧版本的回读字节；重复包复用 artifact。随机测试桶及全部对象版本已经清理。原始 apksigner/aapt2 输出位于同目录 verification-*，未使用产品生产证书。

Harness 34项通过；compileall 与相关文件 git diff --check 通过。

## 修复轨迹

- 首轮 Windows 沙箱拒绝新临时目录访问，审批后在沙箱外执行；无业务库回退。
- 首轮补充测试发现短会话 token、SQLite aware/naive ORM同步、路由测试枚举适配问题，均修复。
- `T03-20261029T051723Z-result.json` 保留首轮失败记录：仅存储单元 fixture 的 S3Error 构造参数错位；真实 MinIO 测试已成功。修正 fixture 后第二轮真实存储与全部回归通过。失败证据不删除。

## 运行边界

- 未部署或启用生产服务，未修改正式签名批准列表，未提交/推送 Git。
- 生产必须配置批准证书、受控 SDK、可信构建兼容声明、私有持久暂存/证据卷、启用 versioning 的 APK 专桶及秘密注入。应用无删除对象能力，运维仍需保留和备份策略；versioning 不等同 WORM。
- 存储权限/限额/断连用可重复故障注入覆盖；真实存储覆盖 versioning错误恢复与完整回读，不声称已进行云厂商限额或断网压测。
- 后续下载票据必须携带固定 versionId；第三方公开 HTTPS 登记 M42-T04、管理/发布 API 与前端以及 Android M118 尚未完成。
