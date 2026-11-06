# 自有 APK 上传与版本固定存储（M42-T03）

需求归属：PRODUCT_REQUIREMENTS.md FR-12。契约沿用 app-update-v1.md；本页说明实现与运维，不新增产品范围。

## 上传接口

`POST /aiyoloapi/admin/app-updates/artifacts/upload`，账号会话认证；仅当前启用的 `PLATFORM_ADMIN` 可用，开发 legacy token 不可用。认证在读取请求体前执行；入队、核验落库与来源登记再次读取账号权限。

multipart 恰好包含 `apk`（单个文件）、`idempotencyKey`（1–128 个 ASCII 字母数字或 `._:-`）、`reason`（1–1000 字符）。文件名不参与定位。成功返回 HTTP 202 和冻结的 ResourceResult：`resourceId/state/revision`。202 表示已受理，不代表已验签或可发布；管理详情查询由 T05 承接。无下载代理端点。

上传流分块直接写入 UUID 暂存文件并计算大小和 SHA-256，不预先解析整个表单。APK 上限 `APP_APK_MAX_BYTES`（默认 8 GiB），multipart 额外开销最多 16 KiB；字段、头部、分段数量均有界。总接收默认 300 秒，单次接收最多等待 30 秒。断线、畸形表单、空文件、超限、超时失败并清理；删除失败持久登记后重试。

同一管理员与幂等键绑定字节摘要、大小、操作原因和可信构建声明；完全一致返回原资源，不一致 409。不同幂等键、相同正式包版本和字节复用原 artifact；同版本不同字节失败，不覆盖原包。同名文件按独立 UUID 接收。

## 核验及存储

统一核验器解析真实 manifest、包名、全局 versionCode、minSdk、ABI，运行 apksigner 验证批准的正式证书与 v2 签名；不信任扩展名、请求声明或 ETag。兼容性声明来自运维或 CI 提供的 `APP_APK_COMPATIBILITY_PATH`，JSON 键为：

```json
{"server_contract_min":1,"server_contract_max":1,"data_schema_version":19,"readable_schema_min":18,"readable_schema_max":19,"evidence_ref":"ci/releases/build/compatibility.json"}
```

声明须针对当前上传构建受控更新，不能根据 APK 自动证明；未配置批准证书、工具、可信声明或存储时拒绝启用。

MinIO 使用独立 APK bucket（默认 `aiyolo-app-apks`），必须事先启用 bucket versioning；服务不修改既有业务桶策略。对象键 `app-apks/<artifactId>/<sha256>.apk`，原始名不进入对象键。上传后按返回的 versionId 全量 GET，核对字节数和 SHA-256。已有对象也必须读回核对。

来源登记固定 bucket、key、versionId、ETag、摘要、大小、核验凭据引用和递增 sourceRevision。ETag 仅作存储元数据。应用服务不覆写、不删除已登记对象；并发写入可能产生内容相同的不同对象版本，各来源固定到核验过的版本。后续下载票据必须指定 versionId；仅使用裸 key 会破坏保证。Versioning 不等同 WORM：运维权限仍可永久删除旧版本，生产 IAM 应禁止应用删除版本，备份/保留由运维保障。

MinIO 访问密钥仅复用服务端秘密配置；API 和审计不输出 URL、凭据、原文件名、SDK 异常文本。App 获取公开地址或短期下载票据的能力由后续任务实现。

## 持久队列与恢复

新增 `app_apk_uploads`，总计 11 张升级表；Alembic head `20261029_28`。`receiving → queued → processing → succeeded/failed/retryable`。全局默认最多 4 个活动上传/排队任务，共用身份行锁实施容量门禁；领取用条件更新防止重复。30 秒后重试存储暂时故障、权限/限额错误、缺桶或未启用版本控制；保留原始暂存并重用核验结果。

租约默认 1800 秒。过期接收标失败；过期处理清除 token 并恢复可重试，核验提交及来源提交都在事务中核对 token，旧 worker 不能写入当前任务结果或清理新 worker 文件。重启后自动扫描。文件暂存和核验凭据必须放在持久私有卷；多个服务实例需共享同一暂存根。默认 `.tmp` 仅适合本机开发，容器临时层不保证重启恢复。

`APP_APK_WORKER_ENABLED=false` 默认关闭；启用时启动失败会拒绝服务启动，避免静默接收无人处理任务。关闭服务时等待当前 worker 完成后关闭数据库。部署的终止宽限期应覆盖核验与 MinIO 传输时间；强制终止由租约回收。接收时限必须小于租约。网络传输有连接和读超时；代理另行设置请求体和连接限额，不能无限缓冲请求体。

迁移降级遇到上传历史或固定对象元数据即拒绝；不以删除升级历史恢复旧数据库。第三方 HTTPS 直链由 M42-T04 实现，发布/下载票据/停止与恢复由后续任务承接。

## 验证

`tools/accept_m42_uploads.py` 启动隔离 PostgreSQL（不使用应用库），执行 SQLite/PG 生命周期、权限、并发、超时、损坏与存储错误用例。真实测试用 SDK 生成临时证书签名包、真实验签并写入随机独立 MinIO 测试桶，回读后证明同 key 新版本不影响旧版字节，最终只清理测试桶及其对象版本。测试证书不会进入生产批准列表。
