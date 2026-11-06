# Kubernetes 生产部署（saas-prod）

本目录只部署视频服务与模型转换器，不部署媒体分发服务。先完成 M34-T06/M101-T04 等本地真实验收并取得部署批准，再执行下方构建/推送/apply；M34-T04 只解析静态清单，不访问集群。旧部署清理和受限回退见 [分发退役升级手册](../../../docs/media-retirement-upgrade.md)。

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

两个镜像均采用 CPU 版 PyTorch/TorchVision，推理、PT 校验与 LiteRT 转换不使用显卡，无需 NVIDIA 驱动或 GPU 资源请求。构建时自动检查 GPU 依赖、CPU NMS 与 JAX CPU 设备，详见 [CPU 运行与镜像依赖](../../../docs/docker-deployment.md#cpu-only)。旧镜像必须重新构建后发布；只修改 ConfigMap 中的 `YOLO_DEVICE=cpu` 不能移除旧镜像中的 CUDA 库。

## 2. 创建运行时配置

复制示例并填写数据库、MinIO、转换器和模型配置。当前本地验证通过的 Bucket 是私有 Bucket `yolo-system`，对象前缀为 `alerts`：

```bash
cp deploy/k8s/production/config.env.example deploy/k8s/production/config.env
cp deploy/k8s/production/secret.env.example deploy/k8s/production/secret.env
```

编辑两个文件，确保不存在 `CHANGE_ME`。数据库密码中的保留字符必须 URL 编码。当前公司 MinIO 如果仍使用可信内网 HTTP，保留 `MINIO_SECURE=false`；启用 TLS 后改为 `true`。PC预览与后台/API保持同源，不配置媒体 CORS 或播放地址。

创建 ConfigMap 和 Secret：

```bash
kubectl create namespace saas-prod --dry-run=client -o yaml | kubectl apply -f -
kubectl -n saas-prod create configmap aiyolo-runtime-config --from-env-file=deploy/k8s/production/config.env --dry-run=client -o yaml | kubectl apply -f -
kubectl -n saas-prod create secret generic aiyolo-runtime-secret --from-env-file=deploy/k8s/production/secret.env --dry-run=client -o yaml | kubectl apply -f -
```

`secret.env` 和 `config.env` 已加入 `.gitignore`。不要把运行时 Secret 导出后提交 Git。
旧 `MEDIAMTX_*` 和 `MEDIA_*` 配置已移除；旧环境遗留值不能重新开启发布。Secret 不再包含媒体凭据，转换器凭据仍须独立。

`ADMIN_FRONTEND_MODE=vue` 提供 `/admin/` 管理入口，当前仅支持 vue。现有 ConfigMap 如包含 `legacy` 必须显式更新；修改 `config.env` 并执行上述 ConfigMap 命令后，还需 `kubectl rollout restart deployment/aiyolo-video-service -n saas-prod` 并等待 rollout。前端构建已内置于 Docker 镜像，集群不启动 Node。旧代码已本地归档并删除，回退需先恢复兼容代码、重新构建发布，或恢复上一完整不可变镜像；只改为 legacy 会启动失败。缓存与归档恢复细节见 [管理前端发布与回退](../../../docs/admin-frontend-release.md)。

## 3. 修改入口和存储

部署前必须完成：

1. 把 `ingress.yaml` 中的 `CHANGE_ME_PUBLIC_HOST` 和 `CHANGE_ME_TLS_SECRET` 替换为生产域名与 TLS Secret。
2. 确认集群默认 StorageClass 可用；如果没有默认 StorageClass，在 `storage.yaml` 的三个 PVC 中显式增加 `storageClassName`。
3. 不创建媒体 LoadBalancer，不开放旧分发端口；确认网关允许PC同源预览、告警通知，且不缓存画面。
4. 确认云 PostgreSQL 和 MinIO 白名单允许 Kubernetes 节点/NAT 出口地址。

模型转换服务统一使用容器端口和 Service 端口 `8090`，不再使用旧 YAML 中的 `8191`。转换器不注入数据库或 MinIO 凭据。

## 4. 部署与验证

从旧单项目版本升级前，必须先按 [M33-T17 发布与回滚手册](../../../docs/m33-t17-release-runbook.md)
完成停写、云数据库 PITR/原生及平台文件备份、独立恢复校验、默认项目回填与对账，确认线上
MinIO 原对象可读并取得孤立投递回执处置决定。生产 Pod 设置
`RUN_DATABASE_MIGRATIONS=false`，不得依赖部署/重启自动执行 Alembic；多副本/重试 Job
也不能代替停写门禁。以上条件未满足时，不执行下方 `kubectl apply` 切换新镜像。

```bash
kubectl apply -k deploy/k8s/production
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

最后按项目验收登录、`/aiyoloapi/projects/{project_id}/alerts`、真机告警上传、MinIO 图片读取、告警 WebSocket、PC原画面/YOLO预览以及无人预览时的独立分析告警。新告警的数据库 `evidence` 必须包含 `objectStorage.provider=minio`，且不包含 `data:image/`。

## 5. 更新和回滚

含数据库结构变化的版本必须遵循上述手册的恢复点、旧版镜像与数据库版本配对规则；
回退不得恢复移动直播或发布器；旧 MediaMTX Deployment/Service/ConfigMap 必须按升级手册逐项处理，`apply -k` 不会自动删除它们。
`kubectl rollout undo` 只回退 Pod，不回退数据库、对象存储或 PVC，新多项目写入后
不能直接回到单项目旧版。恢复演练仅在隔离实例完成，不表示已授权切换在线数据库。

每次发布只修改 `kustomization.yaml` 的镜像 Tag，然后执行：

```bash
kubectl apply -k deploy/k8s/production
kubectl rollout status deployment/aiyolo-video-service -n saas-prod --timeout=10m
```

当前工作负载使用单副本和 ReadWriteOnce PVC，因此采用 `Recreate` 策略，更新期间会有短暂中断。若后续需要多副本无停机部署，必须先把模型目录、校准文件和转换任务改为共享存储；数据库迁移只能在另行批准的独占停写窗口执行，不由应用副本或自动重试 Job 触发。
