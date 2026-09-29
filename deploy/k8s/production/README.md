# Kubernetes 生产部署（saas-prod）

本目录将 Docker 镜像部署到 Kubernetes。PostgreSQL 和 MinIO 都使用外部托管服务，集群内不会启动 PostgreSQL 或 MinIO 容器。

## 1. 发布镜像

使用不可变版本号构建并推送两个镜像，然后把 `kustomization.yaml` 中的两个 `CHANGE_ME` 更新为相同发布版本：

```bash
docker build -t 192.168.0.171:30002/saas-prod/aiyolo-video-service:1.0.2 .
docker build -f Dockerfile.converter -t 192.168.0.171:30002/saas-prod/aiyolo-model-converter:1.0.2 .
docker push 192.168.0.171:30002/saas-prod/aiyolo-video-service:1.0.2
docker push 192.168.0.171:30002/saas-prod/aiyolo-model-converter:1.0.2
```

不要复用已经发布过的 Tag，也不要在生产环境使用 `latest`。

## 2. 创建运行时配置

复制示例并填写公网媒体地址。当前本地验证通过的 Bucket 是私有 Bucket `yolo-system`，对象前缀为 `alerts`：

```bash
cp deploy/k8s/production/config.env.example deploy/k8s/production/config.env
cp deploy/k8s/production/secret.env.example deploy/k8s/production/secret.env
```

编辑两个文件，确保不存在 `CHANGE_ME`。数据库密码中的保留字符必须 URL 编码。当前公司 MinIO 如果仍使用可信内网 HTTP，保留 `MINIO_SECURE=false`；启用 TLS 后改为 `true`。`MEDIA_ALLOW_ORIGINS` 应填写真实 HTTPS 管理域名，不要在公网生产环境长期使用 `*`。

创建 ConfigMap 和 Secret：

```bash
kubectl create namespace saas-prod --dry-run=client -o yaml | kubectl apply -f -
kubectl -n saas-prod create configmap aiyolo-runtime-config --from-env-file=deploy/k8s/production/config.env --dry-run=client -o yaml | kubectl apply -f -
kubectl -n saas-prod create secret generic aiyolo-runtime-secret --from-env-file=deploy/k8s/production/secret.env --dry-run=client -o yaml | kubectl apply -f -
```

`secret.env` 和 `config.env` 已加入 `.gitignore`。不要把运行时 Secret 导出后提交 Git。

## 3. 修改入口和存储

部署前必须完成：

1. 把 `ingress.yaml` 中的 `CHANGE_ME_PUBLIC_HOST` 和 `CHANGE_ME_TLS_SECRET` 替换为生产域名与 TLS Secret。
2. 确认集群默认 StorageClass 可用；如果没有默认 StorageClass，在 `storage.yaml` 的三个 PVC 中显式增加 `storageClassName`。
3. 如果集群不支持 `LoadBalancer` Service，将 `aiyolo-mediamtx-public` 改为云平台支持的负载均衡或 NodePort，并同步防火墙开放 8888/TCP、8889/TCP、8189/UDP。
4. 确认云 PostgreSQL 和 MinIO 白名单允许 Kubernetes 节点/NAT 出口地址。

模型转换服务统一使用容器端口和 Service 端口 `8090`，不再使用旧 YAML 中的 `8191`。转换器不注入数据库或 MinIO 凭据。

## 4. 部署与验证

```bash
kubectl apply -k deploy/k8s/production
kubectl rollout status deployment/aiyolo-mediamtx -n saas-prod --timeout=5m
kubectl rollout status deployment/aiyolo-model-converter -n saas-prod --timeout=10m
kubectl rollout status deployment/aiyolo-video-service -n saas-prod --timeout=10m
kubectl get pod,service,ingress,pvc -n saas-prod -o wide
```

检查日志和健康状态：

```bash
kubectl logs -n saas-prod deployment/aiyolo-video-service --tail=200 --timestamps
kubectl exec -n saas-prod deployment/aiyolo-video-service -- python -m app.container_healthcheck
kubectl exec -n saas-prod deployment/aiyolo-video-service -- python -c 'from app.alert_evidence import AlertEvidenceStore; from app.config import settings; s=AlertEvidenceStore.from_settings(settings); s.validate(); print("MINIO_OK",settings.minio_bucket)'
```

最后验收登录、`/aiyoloapi/alerts`、真机告警上传、MinIO 图片读取、WebSocket、WHEP 和 LL-HLS。新告警的数据库 `evidence` 必须包含 `objectStorage.provider=minio`，且不包含 `data:image/`。

## 5. 更新和回滚

每次发布只修改 `kustomization.yaml` 的镜像 Tag，然后执行：

```bash
kubectl apply -k deploy/k8s/production
kubectl rollout status deployment/aiyolo-video-service -n saas-prod --timeout=10m
```

当前工作负载使用单副本和 ReadWriteOnce PVC，因此采用 `Recreate` 策略，更新期间会有短暂中断。若后续需要多副本无停机部署，必须先把模型目录、校准文件和转换任务改为共享存储，并确认 Alembic 迁移只由一个专用 Job 执行。
