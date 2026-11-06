# 第三方公开 HTTPS APK 登记（M42-T04）

需求：PRODUCT_REQUIREMENTS.md FR-12；使用既有 app-update/v1 契约和统一核验器。APK 由第三方保管，服务端只在核验期间暂存完整文件，结束即删除，不上传 MinIO、不提供 APK 代理下载。

## 接口

仅当前启用的 PLATFORM_ADMIN 账号会话可访问，legacy token 不可用。先认证后读取 JSON，16 KiB 上限、30秒接收期限；错误体不回显输入 URL 或凭据。

- `POST /aiyoloapi/admin/app-updates/external-artifacts`：ExternalArtifactRequest，返回202 ResourceResult。
- `POST /aiyoloapi/admin/app-updates/artifacts/{artifactId}/download-sources`：SourceRequest，补充同一工件的第三方来源，必须给出 expectedArtifactSha256。

```json
{"packageName":"com.aiyolo.inspection","downloadUrl":"https://apk.example.com/app-2.apk","allowedDownloadHosts":["apk.example.com"],"idempotencyKey":"release-2-external","reason":"登记第三方托管APK"}
```

来源仍是草稿/核验过程，202不代表可发布。写入前、核验提交前和来源登记前重新读取账号角色及签名批准状态。幂等键在两种来源间共用管理员命名空间，同键不同请求409；同字节复用原工件，不复用版本号对应的新字节。同一地址不同允许域名集合形成新的来源修订，不能放宽已记录的来源。

## 网络限制

仅 HTTPS、端口443、无userinfo、无fragment、无控制字符或反斜杠；使用小写完整ASCII域名，不支持通配符、IP字面量或Unicode域名（可使用punycode）。每跳域名必须在明确列表中；最多3次重定向，禁止降级HTTP。允许列表限制实际请求地址，而非给内网目标豁免。

每次连接前重新解析并检查全部DNS响应，任一私网、环回、链路本地、组播、保留/共享地址或IPv6映射、隧道、已知NAT64地址均拒绝。直接连接已检查的IP，保留原域名作为TLS SNI、证书校验和Host，防止检查后再次DNS解析。系统CA验证始终启用，不接受API指定CA/代理。DNS线程最多4个并独立超时；卡住解析不会无限创建线程。默认连接/读取超时不超过30秒，整体抓取300秒并使用定时器中断超时socket，最大1200秒且小于任务租约。

使用新建HTTP连接，仅发送固定Accept/identity编码/User-Agent/Connection；不继承业务Bearer、Cookie、管理密钥、环境代理或重定向cookie。仅接受完整200响应，不发送Range、不解压Content-Encoding；拒绝HTML/JSON响应、冲突长度、超限、截断。未知长度按实际字节上限读取。记录每跳域名/解析地址/HTTP状态、URL摘要、Content-Length和Range声明，不保存响应Cookie/Location或完整URL到证据日志。

最终实际字节计算大小/SHA-256，并由aapt2和apksigner验证包名、版本、SDK/ABI、正式批准证书及v2签名。Content-Length、文件名和第三方自报SHA不是信任依据。无Accept-Ranges仍可全量核验，fetch_evidence.rangeAdvertised=false；该值只是声明，不证明断点续传可用，未来客户端下载仍须处理200/206并校验最终完整文件。

## 持久化、错误和恢复

迁移 `20261029_29` 复用 app_apk_uploads，增加kind、外链URL/允许域名、抓取证据和可选目标工件。URL是必要的服务端来源元数据，按非秘密公开URL管理，不得提交带凭据的链接；审计仅记录ID/摘要/错误。不改变冻结schema/金样。

与自有上传共用活动任务容量（默认4），任务token/CAS防重复领取和旧worker写入。每次处理独立UUID-token文件，过期处理回到retryable，重启清除遗留临时文件；删除失败保留cleanup_pending并重试、占用容量避免磁盘无限增长。临时根需私有持久卷和权限保护；没有业务文件长期副本。

错误码包括 external_http_403/404/429/5xx、external_not_apk、external_timeout、external_dns_failed/timeout/busy、external_address_forbidden、external_url_not_allowed、external_tls_failed、external_truncated、external_too_large、external_file_changed；网络/核验失败保持failed且无verified来源，管理员修复后使用新幂等键重试。worker意外终止由租约恢复。

同一已知工件补来源必须匹配已登记大小/摘要，再按统一核验器验证。第三方核验后仍可能替换文件：本任务保证核验时的字节，发布/下载地址检查及Android最终SHA/签名验证由M42-T05/T08、M118承接，不能把首次外链核验当作永久可信。

## 配置与验收边界

`APP_APK_EXTERNAL_ENABLED=false` 默认关闭。启用时独立创建外链worker，不要求MinIO凭据；使用已有批准正式证书、APP_APK_* SDK路径与可信构建兼容JSON。新增 `APP_APK_EXTERNAL_ROOT` 和 `APP_APK_EXTERNAL_SECONDS`。构建兼容证据须匹配待核验构建，不从表单推断。

`tools/accept_m42_external.py` 使用专用临时PostgreSQL、SDK临时签名APK和可控TLS源验证实际HTTP/API/核验/清理，测试连接工厂将已校验测试公网IP映射到本地TLS监听；生产私网限制和CA验证没有配置开关。测试包含TLS失败、HTTP降级、403/404/429/503、截断、超时、替换、无Range、DNS重绑定、幂等/并发/撤权、重启与删除失败。公网第三方实际域名和Android直连覆盖安装仍由后续联合验收完成。
