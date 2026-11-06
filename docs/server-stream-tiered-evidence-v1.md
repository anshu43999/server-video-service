# 服务端视频流告警两级证据 v1（M37-T08）

新生成的 `origin=SERVER_STREAM` 正式告警从同一确认帧派生两份证据：`thumbnail/1` 与 `original/1`。两份对象均为 JPEG，缩略图最长边不超过 320 像素且解码后文件不超过 128 KiB；原图保留确认帧分辨率，在必要时只为满足 5 MiB 上限进行有界压缩或缩小。

事件中的证据结构为：

```json
{
  "snapshotUri": "/aiyoloapi/projects/{projectId}/alerts/{eventId}/evidence",
  "thumbnail": {"1": {"type":"thumbnail","contentVersion":1,"sha256":"...","objectStorage":{}}},
  "original": {"1": {"type":"original","contentVersion":1,"sha256":"...","objectStorage":{}}},
  "displayOverlay": {"version":1,"capturedAtUs":123,"bakedIn":false,"detections":[]}
}
```

默认 `GET .../evidence` 返回最新有效缩略图；`GET .../evidence/{thumbnail|original}/{version}` 显式读取指定层级。两者都要求当前项目的 `project.alerts.read`，读取时持有告警行锁并复核对象键中的项目、事件、层级、版本和摘要。

MinIO 对象键沿用分级证据格式：

```text
{prefix}/projects/{sha256(projectId)}/events/{sha256(eventId)}/{type}/{version}/{sha256(content)}.jpg
```

两层必须作为一个完整生成步骤成功。原图写入失败时回收已写缩略图，且正式告警不入库、不通知；下一帧可使用同一稳定 eventId 重试。两层均使用相同的确认帧 `displayOverlay`，图片字节已含框时 `bakedIn=true`，客户端不得再次叠加。

历史单级服务端证据仍由兼容接口读取；系统不回填或伪造历史原图。两级对象适用既有 90 天默认留存、显式样本保留、宽限删除和共享引用保护策略。
