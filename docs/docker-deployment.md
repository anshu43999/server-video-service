# Linux Docker 部署

根目录唯一的 `compose.yml` 同时编排 `server-video-service`、独立 `model-converter`、PostgreSQL 16 和 MediaMTX 1.20.1。支持具备 Docker Engine 与 Compose 插件的主流 Linux；CentOS Stream 9、Rocky Linux 9、AlmaLinux 9 和 Ubuntu 共用同一套文件。CentOS Linux 7 已于 2024-06-30 结束维护，不作为生产部署目标。

## 1. 主机准备

不启用转换时最低建议为 4 核 CPU、8 GB 内存和 40 GB 可用磁盘；同机执行 LiteRT 转换建议至少 8 核 CPU、16 GB 内存和 80 GB 可用磁盘。默认给转换容器限制 2 CPU、8 GB 内存和 4 GB 临时空间，可按模型大小调整。真实流数、分辨率、FPS 和 CPU/GPU 编码方式会改变容量，正式上线前仍需执行 `docs/capacity-benchmark.md` 的目标服务器压测。

服务器需要已安装 Docker Engine 与 Compose 插件。CentOS/RHEL 的安装、firewalld 和 SELinux 命令见 `deploy/centos/README.md`。确认版本：

```bash
sudo docker version
sudo docker compose version
```

可将运维账号加入 `docker` 组，但该组等同主机 root 权限；生产环境应限制成员并记录操作审计。以下命令假设当前账号已有 Docker 权限，否则在 `docker` 前加 `sudo`。

## 2. 配置目录和模型

将仓库部署到固定目录，例如 `/opt/aiyolo/server-video-service`。仓库已包含转换后的 ONNX/TFLite 测试资产，不包含 PT 源权重；默认允许后端在没有可用服务端推理模型时启动并提供原始视频：

```bash
cd /opt/aiyolo/server-video-service
mkdir -p calibration
cp .env.example .env
chmod 0600 .env
```

编辑 `.env`，必须替换全部 `CHANGE_ME`：

- `POSTGRES_PASSWORD` 与 `DATABASE_URL` 中的密码必须一致；URL 中的保留字符需要百分号编码。
- 不要在生产 `.env` 中设置 `ADMIN_TOKEN` 或 `MOBILE_TOKEN`。生产环境通过 `/api/auth/setup`、`/api/auth/login` 签发动态账号 Session；容器入口会拒绝误配置的静态客户端令牌。
- `MEDIA_PUBLIC_HOST` 填 App 实际可访问的服务器 DNS 名或 IP，不能填 `127.0.0.1`。
- `MODEL_MOUNT_PATH` 默认 `./models`，容器内以只读方式挂载到 `/models`。
- `YOLO_MODEL_PATH` 预留为转换后的 ONNX 路径；当前运行镜像未安装 ONNX Runtime，因此默认 `REQUIRE_YOLO_MODEL=false`。需要服务器 ONNX 推理时先补充 `requirements-onnx.txt`，再改为 `true`。
- `CONVERTER_TOKEN` 使用第三个独立随机值，只在 Compose 内部网络用于视频服务调用转换服务。
- `CALIBRATION_MOUNT_PATH` 默认 `./calibration`，转换容器以只读方式挂载到 `/calibration`。
- `CONVERSION_CALIBRATION_DATA` 填相对于校准集目录的 YAML，例如 `dataset.yaml`；YAML 引用的图片也必须位于同一挂载目录中。
- `CONVERTER_CPUS`、`CONVERTER_MEMORY_LIMIT`、`CONVERTER_TMPFS_SIZE` 按服务器资源和模型大小调整，避免转换挤占实时视频推理。

后端容器固定使用 UID/GID `10001`，转换容器固定使用 UID/GID `10002`。若另行放入受控模型或校准数据，需要为对应 UID/GID 提供只读权限；CentOS/RHEL 上 Compose 的 `:Z` 会设置 SELinux 挂载标签。

Dockerfile 不复制 `.env`、密钥、校准数据或历史日志。模型市场数据和上传产物写入 `model-data` 卷；仓库中的转换资产和外部交付模型通过 `/models` 只读挂载。

部分仍使用旧版 Docker Engine 默认 seccomp 配置的 CentOS/RHEL 主机会阻止 PostgreSQL 16 创建 `postmaster.pid` 或 WAL 临时文件，并返回 `Operation not permitted`。统一 Compose 仅对不发布宿主机端口、只连接内部 `control` 网络的 `postgres` 容器设置 `seccomp=unconfined` 兼容项，同时保留 `no-new-privileges`。视频服务、转换服务和 MediaMTX 继续使用默认 seccomp。该配置避免不同 Linux 主机首次初始化数据库时出现环境相关失败；主机仍应及时升级内核和 Docker Engine。

## 3. 网络和防火墙

默认端口策略：

| 端口 | 协议 | 用途 | 默认暴露 |
|---|---|---|---|
| 18080 | TCP | FastAPI/管理后台 | `.env.example` 直接 HTTP 部署时对外监听，必须用安全组或防火墙限制来源 |
| 8889 | TCP | WebRTC/WHEP 信令 | 对 App 网络开放 |
| 8189 | UDP | WebRTC 媒体 | 对 App 网络开放 |
| 8888 | TCP | LL-HLS 回退 | 对 App 网络开放 |
| 8554 | TCP | RTSP 诊断 | 仅 `127.0.0.1` |
| 5432 | TCP | PostgreSQL | 不发布到主机 |
| 9997 | TCP | MediaMTX API | 不发布到主机 |
| 8090 | TCP | 模型转换 HTTP API | 仅 Compose 内部网络，不发布到主机 |

`.env.example` 面向当前直接 HTTP 联调场景，使用 `CONTROL_BIND_ADDRESS=0.0.0.0` 和 `CONTROL_PORT=18080`。如果部署了 Nginx/Caddy/TLS 网关，应将控制面改回仅本机绑定，并让网关上游指向该端口。媒体端口冲突时修改对应的 `MEDIA_*_PORT`，同时更新防火墙和客户端地址。未提供 `.env` 覆盖时，Compose 仍使用仅本机 `8080` 作为安全回退值。

按实际来源网段收紧防火墙；下面示例展示直接 HTTP 联调需要放行的端口：

```bash
sudo firewall-cmd --permanent --add-port=18080/tcp
sudo firewall-cmd --permanent --add-port=8889/tcp
sudo firewall-cmd --permanent --add-port=8888/tcp
sudo firewall-cmd --permanent --add-port=8189/udp
sudo firewall-cmd --reload
```

公网部署必须在 8080 前配置 Nginx/Caddy/负载均衡器，启用 HTTPS、动态账号 Session 鉴权、限流和访问日志。WHEP/LL-HLS 也应通过 MediaMTX 原生 TLS 或独立媒体反向代理启用 HTTPS；在 TLS 完成前只应在受信任内网使用 `MEDIA_PUBLIC_SCHEME=http`。跨 NAT 的公网 WebRTC 还需要按实际拓扑部署 STUN/TURN，当前 Compose 不宣称已解决 NAT 穿透。

## 4. 启动和验收

部署脚本会先执行 `docker compose config --quiet`，不会把展开后的密钥打印到终端；后端入口会再次校验数据库、公共播放地址、模型和转换接线，并确认生产环境未启用开发静态客户端令牌，然后运行 Alembic 迁移。转换容器会校验独立的 `CONVERTER_TOKEN`，并以单 Worker、单转换任务串行执行。

```bash
cd /opt/aiyolo/server-video-service
bash deploy/deploy.sh config
bash deploy/deploy.sh up
bash deploy/deploy.sh status
```

预期四个服务最终均为 `healthy`。从服务器本机验证：

```bash
curl --fail http://127.0.0.1:18080/healthz
docker compose --env-file .env -f compose.yml ps
```

从 App 所在网络验证 `8889/tcp`、`8888/tcp` 和 `8189/udp`，再创建真实 RTSP 流检查 WHEP 首帧与 LL-HLS 回退。仅看到容器运行不等于视频链路验收通过。

转换服务不对宿主机发布端口。管理后台首次读取转换配置时会从容器环境得到 `remote` 模式，地址为 `http://model-converter:8090`；这里的明文 HTTP 只允许用于不可从宿主机访问的 Compose 内部网络，并由独立 Bearer Token 保护。若数据库中已有 Windows/WSL 时代保存的转换配置，它会优先于环境默认值，需要在管理后台重新保存为 remote 模式。上传 PT 并执行一次真实移动端转换，检查任务成功、TFLite 下载后本地复验通过且模型目录登记成功。

## 5. 日志、备份和恢复

应用只向 stdout/stderr 输出日志，Compose 使用 `json-file` 驱动，单文件 20 MB、保留 5 个。查看日志：

```bash
bash deploy/deploy.sh logs video-service
bash deploy/deploy.sh logs mediamtx
bash deploy/deploy.sh logs model-converter
```

数据库备份：

```bash
bash deploy/deploy.sh backup-db
```

备份文件写入项目的 `backups/`，应转存到独立存储并按组织策略加密。还需要单独备份 Docker 卷 `aiyolo_model-data`、`aiyolo_evidence-data`、`aiyolo_converter-data`，以及宿主机只读模型与校准集目录。恢复会覆盖业务状态，必须先停止写入并在隔离环境验证备份；不要在运行中的生产库上直接试恢复。

## 6. 升级和回滚

每次发布为视频服务和转换服务都使用不可变镜像标签，例如 `aiyolo-video-service:2026.09.1` 与 `aiyolo-model-converter:2026.09.1`，不要在生产长期使用 `latest`：

```bash
bash deploy/deploy.sh backup-db
# 修改 .env 中的 VIDEO_SERVICE_IMAGE 和 MODEL_CONVERTER_IMAGE
bash deploy/deploy.sh config
bash deploy/deploy.sh up
```

升级后检查 `/healthz`、转换服务健康状态、登录、模型目录、持久视频流恢复、真实转换和真实播放。应用回滚时把两个镜像变量改回上一标签并重新执行 `up`。数据库迁移默认只向前执行；若新版本已执行不兼容迁移，必须进入维护窗口，使用升级前备份恢复数据库后再启动旧镜像。禁止只降级应用、继续使用未经确认兼容的新数据库结构。

停止容器但保留数据：

```bash
bash deploy/deploy.sh stop
```

不要使用 `docker compose down -v`，该命令会删除 PostgreSQL、模型市场、转换任务/产物和告警证据卷。
