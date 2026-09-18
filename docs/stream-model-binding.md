# 按流绑定服务端模型（M08-T09）

每个 `StreamSession` 持有自己的 `YoloDetector`。模型注册表中的全局
`activeServerModel` 保存唯一的注册表 `modelId`，仅作为创建新流时的默认值；
服务仍兼容旧注册表中的文件名值，并按注册顺序解析为唯一模型。它不会在运行中覆盖已有流。

## 接口

- 创建流时可传 `model_id`：`POST /api/streams`。
- 切换已存在流：`PUT /api/streams/{stream_id}/model`，请求体
  `{ "model_id": "<registered-id>" }`。
- 查询当前绑定：`GET /api/streams/{stream_id}/model`。
- 也可在 `PATCH /api/streams/{stream_id}/config` 中传 `model_id`。

服务端只接受注册表中存在且校验通过的 `pt`/`onnx` 产物；移动端专用
`tflite` 返回 409。不存在的模型返回 404，文件缺失、大小或 SHA-256
不匹配返回 409。切换时创建新的惰性检测器，不影响其他流的检测器和
运行状态。

流列表及切换响应的 `model` 字段包含 `catalog_model_id`、`scenario`、
`purpose`、输入尺寸和类别标签，便于管理页按场景展示当前绑定关系。
