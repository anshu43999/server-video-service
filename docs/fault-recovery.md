# M04-T04 弱网、重启与故障恢复验证

本任务冻结故障注入步骤和可观察的通过条件。仓库中的自动化测试只注入发布器管道故障；它们验证状态机和资源释放，不替代真实 Docker/网络实测。没有运行真实环境时，报告必须明确写“未实测”，不得伪造延迟、恢复时间或并发数据。

## 通过条件

| 场景 | 注入方式 | 通过条件 |
| --- | --- | --- |
| 输入断流 | 停止 `tools/push_video.py` 或关闭 ingest WebSocket | `frames_received` 停止增长；服务保持可用，重新推帧后恢复 `outputting` |
| 弱网/丢包 | Linux 使用 `tc netem loss 10% delay 100ms`；Windows 在测试网关或交换机注入 | 播放器显示离线并重连；发布器依次进入 `reconnecting`，成功后回到 `connected`，不产生重复会话 |
| 播放器断开 | 关闭 WHEP/LL-HLS 客户端或 MJPEG/WS 连接 | `active_subscribers` 回到断开前水平（通常为 0），发布器和拉流任务仍存活 |
| WHEP 不可用 | 阻断 8889 或返回非 2xx | 客户端按协议顺序回退 LL-HLS（8888），并在 UI 显示“回退”状态 |
| 服务重启 | `docker compose restart video-service` | 健康检查恢复；旧会话被关闭；重新创建/推流后无残留进程 |
| MediaMTX 重启 | `docker compose restart mediamtx` | 首帧触发发布器重连；状态从 `reconnecting` 回到 `connected`；路径列表无重复发布者 |
| 资源泄漏 | 重复执行启动→播放→断开→删除（至少 20 次） | `GET /api/metrics` 中会话数、订阅数和发布进程数回到基线；无持续增长 |

## 可重复执行

先准备本地配置并启动：

```powershell
Copy-Item deploy/mediamtx/mediamtx.yml.example deploy/mediamtx/mediamtx.yml
docker compose up --build -d
docker compose ps
```

在另一个终端创建流并持续推帧，然后记录基线：

```powershell
python tools/push_video.py --help
Invoke-RestMethod http://127.0.0.1:8080/healthz
Invoke-RestMethod http://127.0.0.1:8080/api/metrics | ConvertTo-Json -Depth 8
```

按上表逐项注入故障。MediaMTX 重启使用：

```powershell
docker compose restart mediamtx
docker compose logs --tail=100 mediamtx
```

模拟媒体服务硬断流（用于断流/故障恢复场景）：

```powershell
docker compose stop mediamtx
# 观察 video-service 的 publish_state/reconnect 日志后再启动
docker compose start mediamtx
```

服务重启使用：

```powershell
docker compose restart video-service
docker compose ps
```

Linux 弱网示例（仅针对测试接口/容器网卡，测试完成后删除规则）：

```bash
sudo tc qdisc add dev eth0 root netem loss 10% delay 100ms 20ms
# ...执行 WHEP/LL-HLS 播放与重连观察...
sudo tc qdisc del dev eth0 root
```

## 自动化证据

`tests/test_fault_recovery.py` 使用受控 BrokenPipe 注入模拟媒体进程断开、重试耗尽、播放器订阅释放和会话关闭，确保不会留下 publisher 进程或订阅计数。运行：

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_fault_recovery.py' -v
```

该测试通过仅表示本地状态机检查通过；真实 Docker、网络丢包、WHEP/LL-HLS 回退和 20 次泄漏循环仍需在具备 MediaMTX、浏览器/播放器及网络控制权限的环境执行并附原始日志。
