# App 升级生产准备（M42-T14）

本次发布必须启用 App 升级及“新建版本”HTTPS 外链核验。此目录是适配旧 StatefulSet/Deployment 的审阅材料，不是可直接 apply 的部署包，不加入 production/kustomization.yaml。

## 镜像与开关

Dockerfile 完整构建及 Dockerfile.app-updates 叠加构建加入固定 Android Build Tools 36.0.0 的 aapt2、apksigner.jar、libc++、NOTICE 和 Debian OpenJDK 17 JRE。仅支持 linux/amd64。安装器核对官方工具包大小与固定 SHA-256，只提取指定文件。工具在非 root 用户下自检；镜像不包含私钥、生产 .env 或 APK 签名材料。

生产明确设置 APP_UPDATES_ENABLED=true、APP_APK_EXTERNAL_ENABLED=true。APP_APK_WORKER_ENABLED 单独控制浏览器直接上传 MinIO，不是升级总开关；当前填写 HTTPS 地址的主流程不依赖此入口。运行时才开启功能，不能在通用镜像里隐式打开其他环境。

## 必须提供的生产资源

| 资源 | 核对要求 |
|---|---|
| 既有工作负载 | 实际 owner、容器名、Service、端口、selector；不得混用旧 StatefulSet 与新 Deployment |
| aiyolo-app-update-signing Secret | 已批准的独立 Ed25519 元数据私钥，键 app-update-ed25519.pem；不复用模型密钥，不挂载 APK 签名私钥 |
| aiyolo-app-update-runtime ConfigMap | APP_UPDATE_KEY_ID 与已批准客户端/数据库身份一致，不凭示例另造 keyId |
| aiyolo-app-update-files ConfigMap/受控挂载 | scopes.json、真实 compatibility.json；不生成虚假占位兼容证据 |
| 持久化目录/PVC | 核验证据与外链任务文件；容量、UID 10001、权限和调度策略需验证 |
| 临时卷 | /tmp 核验 staging；挂载后需准备子目录，镜像内 mkdir 不能替代挂载后初始化 |
| 外部 PostgreSQL | 正确迁移、AppIdentity、批准证书、版本水位；不能开发数据覆盖生产 |
| HTTPS 来源与客户端信任 | 真实 APK 下载源、后台域名、元数据公钥、发布范围、手机当前安装身份 |

已有同用途资源优先复用，示例名称不要求重建。所有 CHANGE_ME 必须替换，保留原数据库/MinIO/模型配置、探针和数据卷；temp 不得重复。空 emptyDir 不代表容量无限，应按 APK 大小、并发及核验副本评估峰值与上限。默认 8 GiB APK 上限不能直接视作已满足容量。

## 脱敏预检

容器内运行 python /app/tools/check_app_update_runtime.py --tools-only 检查工具；注入批准配置后运行 python /app/tools/check_app_update_runtime.py 检查配置。

预检不读取 .env、不连接数据库、不启动 worker、不修改密钥/目录、不发布版本。检查项包含强制开关、工具、签名格式/与已配置模型密钥隔离、scope/compatibility 结构及目录权限估计。输出不包含密钥、路径、工具原文或异常信息，production_ready 永远为 false。

预检不验证兼容证据真实性、数据库身份、实际卷写入/容量、APK 来源、客户端信任、真实安装；这些须单独验收。结构合法的兼容 JSON 不等于真实兼容证明。

## 发布顺序

1. 获取脱敏 owner/Service/PVC/StorageClass/Ingress，整理最小变更，不先 apply 片段。
2. 核对数据库版本、备份与恢复，按批准流程迁移；RUN_DATABASE_MIGRATIONS=false。
3. 安全准备既有签名身份、scope/compatibility 文件，不在聊天/日志复制秘密。
4. 核对候选摘要、架构、工具版本/许可证和容量，再按批准方式推送内部仓库。
5. 核对配置预检，再经授权切换并验证健康、登录、模型转换和告警不回归。
6. 受控验证新建版本、HTTPS 核验、草稿、单独发布、手机发现更新、验签、下载、安装、数据保留及回执。启用功能不授权自动向生产用户发布版本。

本任务不替代 M42-T10/Android 联合验收，不绕过部署门禁，不操作手机或生产数据库。缺生产入口和验收时只交付候选镜像与准备材料，不能声称线上已开启。
