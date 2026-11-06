# 告警证据展示叠加 v1（M40 / Android M109）

本文件记录实现契约，产品范围以移动端 `docs/产品需求基线.md` PR-05 为准。仅保障更新后采集的新告警，不回填历史数据。

## 数据与显示

告警 `evidence.displayOverlay` 为可选的轻量展示元数据：

```json
{"version":1,"capturedAtUs":123,"bakedIn":false,"detections":[{"label":"安全帽","confidence":0.91,"box":{"left":0.1,"top":0.2,"right":0.6,"bottom":0.8}}]}
```

坐标归一化到证据图片，客户端也接受服务端的 `box: {x,y,w,h}`。App 本地读取截图/原图现有 sidecar；L1 事实上传携带同一份元数据。服务端视频在生成证据时冻结该帧匹配结果，并记录当前截图是否已经烘焙识别框。此元数据随原有事件持久化和查询返回，无数据库迁移。

App 本地/远端证据与 PC 列表/详情按实际图片缩放、留白绘制框、类别、置信度。`bakedIn=true` 不再绘制；缺失、未知版本或非法框不绘制。不使用事件后续更新的 `detectionResults`，不重新推理。

## 保持的边界

不修改截图、缩略图、原图内容、编码/压缩参数和源位图；叠加只存在于显示画布/DOM。下载图片保持原样。媒体上传接口、鉴权、补传、重试、清理及保留期限均不变。仅在现有 L1 JSON 增加上述展示元数据。

客户端与服务端均需发布本次更新，更新后新采集并同步的证据才能跨端展示。旧客户端缺少元数据时仍正常展示图片，但不保证有框。

## 验证入口

- Android `EvidenceDisplayOverlayTest`、`EvidenceDisplayOverlayInstrumentedTest`：坐标、同帧 sidecar、缩放裁剪、烘焙跳过、源位图/文件 SHA-256 不变。
- PC `tests/evidence-overlay.test.ts` 和 `tests-e2e/alerts.spec.ts`：组件复用、失败、横竖图及真实浏览器布局。
- 服务端 `test_analysis_only.py`、`test_analysis_alert_closure.py`、`test_mobile_alert_ingest.py`：同帧冻结、持久化、L1 重放、媒体上传与 JPEG 字节不变。
