# M42-T05 发布策略、签名及双来源地址验收

日期：2026-10-29。任务范围：服务端发布/停止、移动检查/地址/安装许可/回执及后台只读 API。

## 实现

- `app/app_updates/service.py`：身份行串行锁、发布/停止 CAS、操作幂等、当前管理员重检、不可变发布来源、签名历史。
- `publisher.py`：独立 Ed25519 元数据签名，冻结域分离和原始 JSON 字节，拒绝复用模型签名密钥。
- `delivery.py`：MinIO 固定 versionId 的 HTTPS 票据；外链直接返回经核验的第三方地址。
- `api.py`：13 个发布/移动/只读接口、有界请求体、统一错误、无缓存、进程限流及并发容量。
- 持久设备状态、历史回执校验、事件/序列去重和尝试绑定；迟到事件不覆盖当前尝试和成功终态。
- `docs/app-update-service.md` 和 `.env.example`：配置、scope、公开 HTTPS 存储网关及验收边界。

## 真实测试

1. 主验收 `T05-20261029T060044Z-result.json`：通过。
   - `test_app_update_*.py` 53 项通过，包括 SQLite、隔离 PostgreSQL、冻结金样与迁移、真实 APK/双来源下载。
   - `test_database.py` 6 项通过。
   - 一次性 PostgreSQL 127.0.0.1:58092，role=aiyolo_app；临时集群路径和 PID 见 JSON，结束 schema 为 []、端口关闭。
2. 最终回归 `T05-final-20261029T060323Z-result.json`：30 项通过。
   - 最后追加 attempt 不能更换 release/artifact/from/target 的约束、域名不匹配拒绝、停止/票据并发、配额、错误和权限。
   - 隔离 PostgreSQL 127.0.0.1:63443，结束 schema 为 []、端口关闭。
3. 真实双来源证据 `T05-20261029T060044Z-raw/delivery-integration.json`：
   - 一次性测试签名 APK 经 aapt2/apksigner 和真实持久队列核验；首版本 1、后版本 2。
   - 外链受控 TLS 完整核验、新来源修订 2、签名票据验签、直接读取 TLS 文件并核对大小/SHA-256、安装许可验签。
   - 独立随机 MinIO 桶启用 versioning；内部来源修订 1、签名票据、同 key 后续写入不改变所取版本、下载精确摘要及安装许可。
   - 随机桶只包含本测试数据，finally 删除全部测试版本和桶，证据 testBucketRemoved=true。
4. `app.main` 的 TestClient 路由冒烟：check 请求返回约定 422 ErrorBody，未触发 lifespan、未连接或迁移开发库。
5. Harness 单元测试 34 项通过；编译检查和本次跟踪文件 diff 空白检查通过。

## 失败及修复留存

- 沙箱临时目录拒绝访问，失败结果 `T05-20261029T055458Z-result.json` 保留；按权限要求升级执行后恢复。
- 初轮发现 PostgreSQL 时区序列化与首次响应不一致，统一 UTC 后重复响应一致。
- 现有 MinIO 地址为 HTTP，直接签发被服务主动拒绝；新增独立公开 HTTPS S3 endpoint 配置。
- 直接将公网 MinIO HTTP 请求的 Host 改成 fixture 域名被上游网关拒绝；测试改用可控 TLS 网关验证 SigV4，再通过实际 MinIO SDK 读取固定版本。失败日志/JSON `055542Z`、`055742Z` 保留。
- SQLite 游标比较默认时间和带小数秒绑定时间会重复，改为数据库内时间锚点比较，稳定分页用例通过。

## 边界与剩余条件

- 测试 TLS 网关独立于业务 API，但它是受控测试设施；它验证 SigV4 并通过 MinIO SDK 读取真实对象，不是已部署的正式公网 S3 反代。
- TLS 源连接仅在测试工厂把已检查公网 fixture IP 映射至回环；生产代码没有关闭 SSRF/TLS 的配置。
- 生产功能默认关闭，仍需真实生产签名证书、独立 App 元数据密钥、身份引用、scope 白名单、可信 CI 兼容声明及公开 HTTPS 文件服务。
- 外链既有完整核验证据在 check/地址许可时复用，不重新下载文件；托管端换字节由 Android 摘要/证书校验拒绝。
- 当前限流为单进程，需要边缘/跨实例治理；设备和每实例回执有持久配额，满额不会静默删除历史。
- 公共回执是客户端自报；installer_opened 不等于成功，已交接安装无法通过撤回来追回。
- 后台界面 T06、快速回退 T07、安全及压力 T08、联合验收 T09/T10、Android M118 尚未完成；没有宣称生产上线或设备升级通过。
- 未操作开发 PostgreSQL，未修改 Android 产品文件，未提交或推送 Git。
