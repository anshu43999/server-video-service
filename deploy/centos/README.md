# CentOS / RHEL 主机准备

项目不维护 CentOS 专用 Compose。CentOS Stream 9、Rocky Linux 9、
AlmaLinux 9、Ubuntu 等 Linux 服务器统一使用项目根目录的 `compose.yml`、
`.env` 和 `deploy/deploy.sh`。

CentOS/RHEL 系宿主机仅需额外处理以下事项：

1. 使用 Docker CE 官方仓库安装 Docker Engine 与 Compose 插件；
2. 直接 HTTP 部署时使用 `firewall-cmd` 放行 `18080/tcp`、`8889/tcp`、`8888/tcp` 和 `8189/udp`；
3. 保持 Compose 挂载中的 `:Z`，让 Docker 为 bind mount 设置 SELinux 标签；
4. 通过 systemd 启用 Docker：`sudo systemctl enable --now docker`。

仅在启用 Android 模型签名时，外部私钥挂载需要保留 `:ro,Z`，以便 SELinux 为其设置
正确标签。容器 UID、文件权限和覆盖文件的完整配置见 `docs/docker-deployment.md` 附录 C。

业务 PostgreSQL 使用云数据库，不由 Compose 在本机启动，因此不需要为 PostgreSQL 容器配置 `seccomp=unconfined` 或开放 `5432`。请在云数据库安全组中只允许部署主机访问，并保持 TLS 连接；本机 Docker 服务仍使用默认 seccomp，主机 Docker Engine 与内核应保持受支持版本。

CentOS Stream 9 / Rocky Linux 9 / AlmaLinux 9 安装示例：

```bash
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

媒体端口示例：

```bash
sudo firewall-cmd --permanent --add-port=18080/tcp
sudo firewall-cmd --permanent --add-port=8889/tcp
sudo firewall-cmd --permanent --add-port=8888/tcp
sudo firewall-cmd --permanent --add-port=8189/udp
sudo firewall-cmd --reload
```

完整部署步骤见 `docs/docker-deployment.md`。
