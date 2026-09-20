# CentOS / RHEL 主机准备

项目不维护 CentOS 专用 Compose。CentOS Stream 9、Rocky Linux 9、
AlmaLinux 9、Ubuntu 等 Linux 服务器统一使用项目根目录的 `compose.yml`、
`.env` 和 `deploy/deploy.sh`。

CentOS/RHEL 系宿主机仅需额外处理以下事项：

1. 使用 Docker CE 官方仓库安装 Docker Engine 与 Compose 插件；
2. 使用 `firewall-cmd` 放行 `8889/tcp`、`8888/tcp` 和 `8189/udp`；
3. 保持 Compose 挂载中的 `:Z`，让 Docker 为 bind mount 设置 SELinux 标签；
4. 通过 systemd 启用 Docker：`sudo systemctl enable --now docker`。

CentOS Stream 9 / Rocky Linux 9 / AlmaLinux 9 安装示例：

```bash
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

媒体端口示例：

```bash
sudo firewall-cmd --permanent --add-port=8889/tcp
sudo firewall-cmd --permanent --add-port=8888/tcp
sudo firewall-cmd --permanent --add-port=8189/udp
sudo firewall-cmd --reload
```

完整部署步骤见 `docs/docker-deployment.md`。
