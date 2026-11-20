# M42-T14：App 升级容器工具与生产准备

日期：2026-11-06（Asia/Shanghai）。本任务仅为开发构建与交付准备，不代表生产已开启或通过验收。

## 范围

用户要求生产必须开启 App 升级，不能关闭功能交付。当前主流程为管理员填写 APK HTTPS 地址，完整核验后建草稿并单独发布；目标 APP_UPDATES_ENABLED=true、APP_APK_EXTERNAL_ENABLED=true。直接上传 MinIO 是独立入口，不在本次主流程前置中。

本轮没有连接生产集群/数据库/MinIO，没有读取或转移真实私钥，没有重启业务服务、修改手机、创建 App 发布或下载镜像归档到本地。已有脏模型文件保持原样。未提交或推送 Git。

## 实现

- Dockerfile 增加 APK 工具构建阶段与 Java 运行依赖；Dockerfile.app-updates 在原已核验镜像之上添加同样工具，保留应用字节、CPU 栈、entrypoint 和健康检查。
- tools/install_android_verifier.py 固定官方 Linux Build Tools 36.0.0；核验大小和 SHA-256，限定提取 aapt2、apksigner.jar、libc++、NOTICE/source.properties，不提取任意路径。
- tools/check_app_update_runtime.py 提供无数据库/网络的脱敏预检：工具、强制功能开关、签名格式及配置了模型密钥时的独立性、JSON 结构、目录权限估计；不加载 .env、不写目录/密钥、不启动 worker。production_ready=false，明确后续数据库/真实兼容性/客户端/下载/安装未验证。
- deploy/k8s/app-updates 提供目标配置和非 standalone 的 Pod template 审阅片段，未加入生产 kustomization；保留 controller/container/PVC 占位符，不凭空创建生产资源。
- deploy/validate-app-update-candidate.sh 用无网络、只读、非 root、drop ALL、no-new-privileges 临时容器验证，然后在独立目录导出并校验归档。

## 官方工具来源与校验

- 官方索引：https://dl.google.com/android/repository/repository2-3.xml
- 下载：https://dl.google.com/android/repository/build-tools_r36_linux.zip
- 官方索引长度：63737259 bytes；SHA-1：b0b6376977657e8ad9b969bacf4093601da2c6fb。
- 本轮实际下载 SHA-1 与官方相同，SHA-256：5d9ac77fb6ff43d9da518a337b4fcf8f9097113df531d99ccefe80ef7ce8250b。
- aapt2：2.20-13193326；apksigner：0.9；OpenJDK：17.0.21+9-1-deb12u1-Debian。Java 来自签名 Debian bookworm 软件源，实际版本记录在构建日志；它不是跨时间固定的 apt 包版本。交付运行版本由镜像摘要锁定。
- 工具 NOTICE 随镜像保留；发布前仍需按公司流程审阅完整许可证/SBOM，不能把此记录当成法律审批。

## 实际开发服务器候选

- 构建机：用户授权的开发服务器，非生产集群。
- 独立目录：/root/aiyolo-app-updates-20261106-AYXX4w/。
- 原应用提交：c1e554f834583f62402d8527ac69a3a2a144c2a1。
- 已核对原视频镜像 ID：sha256:af817eebd8ee0e50a10ba01a5a33ea3f8ad6652116f020c08997d276311331e6。
- 新候选标签：aiyolo-video-service:1.0.3-appupdates.20261106-r1。
- 新候选镜像 ID：sha256:cc0b47ad4ddfdcc063608b0695d158a99e187921096fde5356b286e656f98161。
- 架构：linux/amd64；用户：app/UID 10001；逻辑镜像大小：2514132302 bytes。
- 归档：/root/aiyolo-app-updates-20261106-AYXX4w/aiyolo-video-service-1.0.3-appupdates.20261106-r1.tar.gz。
- 归档大小：897843778 bytes（约 856.25 MiB）。
- 归档 SHA-256：fb3be258e073f77589468fb7b96a97e13d3d87587d78dc79410ad77b7cc7d10b。
- gzip 完整性、SHA-256 回读检查通过；对应 .sha256 文件保留同目录。
- 结束时开发机 df -h 报告 18G 可用、63% 已用。没有删除原镜像/归档或其他服务。
- 原转换器 ID 保持 sha256:56140820124a8a445b9acedbc1774f7d80ce44128d1b8e901d2358d3acc6c7a0，不需要为 APK 核验重建。

实际使用 Dockerfile.app-updates 构建叠加候选；完整 Dockerfile 通过静态测试，但本轮未重新执行全部 npm/pip 全量构建。候选不包含完整工作树其他未提交改动。构建机原项目目录未修改，仅传入本次工具与 Dockerfile 到独立目录。

第一次构建用裸镜像 ID 作 FROM 被 BuildKit 当成仓库名而失败；随后核对原标签的完整 ID，改用已验证本地不可变标签构建成功。保留 build.log 与 build-retry.log，不掩盖首次失败。

## 本轮验证

| 验证 | 结果 |
|---|---|
| test_app_update_container.py | 16 项通过；合成临时密钥仅用于测试，不读取生产密钥 |
| test_kubernetes_deployment.py | 7 项通过；现有模板静态回归 |
| test_docker_deployment.py | 17 项通过；从工作区根运行以避免加载服务 .env |
| Harness 单元测试 | 34 项通过 |
| Harness validate | 通过 |
| 候选非 root 工具执行 | aapt2、Java、apksigner 全部通过 |
| 候选 CPU 检查 | torch 2.12.0+cpu、torchvision 0.27.0+cpu；CUDA 不可用、GPU 包列表为空、CPU NMS 通过 |
| pip check | No broken requirements found |
| 空业务配置负向预检 | 预期拒绝，未误报生产可用 |
| 归档 | gzip -t 与 sha256sum -c 通过 |

合计本轮 74 项自动化用例通过，另有真实 Linux 容器检查；不代表全量后端回归或真实 APK 安装升级通过。原提交已知全量回归失败仍须由对应任务处置。

## 上线前剩余条件

1. 生产 StatefulSet/Deployment、Service、PVC/StorageClass、Ingress 脱敏配置和实际部署入口；当前只有旧 Pod/Secret 结构，不能安全套用片段。
2. 生产数据库当前版本、备份/恢复与迁移核验；由批准流程执行，应用保持 RUN_DATABASE_MIGRATIONS=false。
3. 已批准 App 元数据密钥、scope、客户端信任、APK 证书/版本水位及真实 compatibility 文件。不得把本机 HTTP 试用包的兼容声明自动升格为生产证据。
4. 容器实际 PVC 权限/写入/容量、HTTPS 下载源和入口、手机真实升级/数据保留/回执验收，M42-T10/Android 联合验收及既有部署门禁仍有效。
5. 本轮只保留开发候选及服务器归档；未推送生产镜像仓库、未下载本地、未开启生产功能。下一阶段必须满足以上条件后才切换，不能以关掉 App 升级绕过。
