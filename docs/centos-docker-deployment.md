# CentOS Docker 部署

本部署覆盖 `server-video-service`、PostgreSQL 16 和 MediaMTX 1.20.1。支持基线为 CentOS Stream 9，以及与 RHEL 9 兼容的 Rocky Linux/AlmaLinux。CentOS Linux 7 已于 2024-06-30 结束维护，不作为生产部署目标；若现有服务器仍是 CentOS 7，应先升级操作系统。

## 1. 主机准备

最低建议为 4 核 CPU、8 GB 内存和 40 GB 可用磁盘。真实流数、分辨率、FPS 和 CPU/GPU 编码方式会改变容量，正式上线前仍需执行 `docs/capacity-benchmark.md` 的目标服务器压测。

在 CentOS Stream 9 安装 Docker CE 与 Compose 插件：

```bash
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
```

可将运维账号加入 `docker` 组，但该组等同主机 root 权限；生产环境应限制成员并记录操作审计。以下命令假设当前账号已有 Docker 权限，否则在 `docker` 前加 `sudo`。

## 2. 配置目录和模型

将仓库部署到固定目录，例如 `/opt/aiyolo/server-video-service`，然后创建只读模型目录：

```bash
sudo install -d -o root -g 10001 -m 0750 /opt/aiyolo/models
sudo install -o root -g 10001 -m 0440 /secure/model-delivery/best.pt /opt/aiyolo/models/best.pt
sudo restorecon -RFv /opt/aiyolo/models

cd /opt/aiyolo/server-video-service
cp deploy/centos/.env.example deploy/centos/.env
chmod 0600 deploy/centos/.env
```

编辑 `deploy/centos/.env`，必须替换全部 `CHANGE_ME`：

- `POSTGRES_PASSWORD` 与 `DATABASE_URL` 中的密码必须一致；URL 中的保留字符需要百分号编码。
- `ADMIN_TOKEN`、`MOBILE_TOKEN` 使用不同的随机值，至少 24 字符，建议用 `openssl rand -hex 32` 分别生成。
- `MEDIA_PUBLIC_HOST` 填 App 实际可访问的服务器 DNS 名或 IP，不能填 `127.0.0.1`。
- `MODEL_MOUNT_PATH` 填 CentOS 主机模型目录，容器内以只读方式挂载到 `/models`。
- `YOLO_MODEL_PATH` 是容器内路径，默认 `/models/best.pt`。

后端容器固定使用 UID/GID `10001`。上面的目录和文件组权限允许容器读取模型，但不能修改宿主机模型；若企业基线要求使用 ACL，可改用 `setfacl -m u:10001:rX` 达到相同效果。

Dockerfile 不复制 `.env`、密钥、模型权重或历史日志。模型市场数据和上传产物写入 `model-data` 卷；外部交付的主模型始终通过 `/models` 只读挂载。

## 3. 网络和防火墙

默认端口策略：

| 端口 | 协议 | 用途 | 默认暴露 |
|---|---|---|---|
| 8080 | TCP | FastAPI/管理后台 | 仅 `127.0.0.1`，由 TLS 网关反代 |
| 8889 | TCP | WebRTC/WHEP 信令 | 对 App 网络开放 |
| 8189 | UDP | WebRTC 媒体 | 对 App 网络开放 |
| 8888 | TCP | LL-HLS 回退 | 对 App 网络开放 |
| 8554 | TCP | RTSP 诊断 | 仅 `127.0.0.1` |
| 5432 | TCP | PostgreSQL | 不发布到主机 |
| 9997 | TCP | MediaMTX API | 不发布到主机 |

按实际来源网段收紧防火墙；下面示例只展示需要放行的媒体端口：

```bash
sudo firewall-cmd --permanent --add-port=8889/tcp
sudo firewall-cmd --permanent --add-port=8888/tcp
sudo firewall-cmd --permanent --add-port=8189/udp
sudo firewall-cmd --reload
```

公网部署必须在 8080 前配置 Nginx/Caddy/负载均衡器，启用 HTTPS、鉴权、限流和访问日志。WHEP/LL-HLS 也应通过 MediaMTX 原生 TLS 或独立媒体反向代理启用 HTTPS；在 TLS 完成前只应在受信任内网使用 `MEDIA_PUBLIC_SCHEME=http`。跨 NAT 的公网 WebRTC 还需要按实际拓扑部署 STUN/TURN，当前 Compose 不宣称已解决 NAT 穿透。

## 4. 启动和验收

部署脚本会先执行 `docker compose config --quiet`，不会把展开后的密钥打印到终端；后端入口会再次校验数据库、令牌、公共播放地址和模型文件，然后运行 Alembic 迁移。

```bash
cd /opt/aiyolo/server-video-service
bash deploy/centos/deploy.sh config
bash deploy/centos/deploy.sh up
bash deploy/centos/deploy.sh status
```

预期三个服务最终均为 `healthy`。从服务器本机验证：

```bash
curl --fail http://127.0.0.1:8080/healthz
docker compose --env-file deploy/centos/.env -f compose.centos.yml ps
```

从 App 所在网络验证 `8889/tcp`、`8888/tcp` 和 `8189/udp`，再创建真实 RTSP 流检查 WHEP 首帧与 LL-HLS 回退。仅看到容器运行不等于视频链路验收通过。

## 5. 日志、备份和恢复

应用只向 stdout/stderr 输出日志，Compose 使用 `json-file` 驱动，单文件 20 MB、保留 5 个。查看日志：

```bash
bash deploy/centos/deploy.sh logs video-service
bash deploy/centos/deploy.sh logs mediamtx
```

数据库备份：

```bash
bash deploy/centos/deploy.sh backup-db
```

备份文件写入项目的 `backups/`，应转存到独立存储并按组织策略加密。还需要单独备份 Docker 卷 `aiyolo_model-data`、`aiyolo_evidence-data`，以及宿主机只读模型目录。恢复会覆盖业务状态，必须先停止写入并在隔离环境验证备份；不要在运行中的生产库上直接试恢复。

## 6. 升级和回滚

每次发布使用不可变镜像标签，例如 `aiyolo-video-service:2026.09.1`，不要在生产长期使用 `latest`：

```bash
bash deploy/centos/deploy.sh backup-db
# 修改 deploy/centos/.env 中的 VIDEO_SERVICE_IMAGE
bash deploy/centos/deploy.sh config
bash deploy/centos/deploy.sh up
```

升级后检查 `/healthz`、登录、模型目录、持久视频流恢复和真实播放。应用回滚时把 `VIDEO_SERVICE_IMAGE` 改回上一标签并重新执行 `up`。数据库迁移默认只向前执行；若新版本已执行不兼容迁移，必须进入维护窗口，使用升级前备份恢复数据库后再启动旧镜像。禁止只降级应用、继续使用未经确认兼容的新数据库结构。

停止容器但保留数据：

```bash
bash deploy/centos/deploy.sh stop
```

不要使用 `docker compose down -v`，该命令会删除 PostgreSQL、模型市场和告警证据卷。
