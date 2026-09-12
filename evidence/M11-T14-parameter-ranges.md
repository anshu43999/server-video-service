# M11-T14 模型参数范围与默认值证据

## 参数契约

- 识别置信度：`0.01-0.99`，默认 `0.35`，步进 `0.01`
- IoU 去重阈值：`0.10-0.90`，默认 `0.45`，步进 `0.01`
- 单帧最大结果数：`1-300`，默认 `100`，步进 `1`
- 类别告警置信度：`0.01-0.99`，默认 `0.55`，步进 `0.01`，且不得低于检测置信度
- 连续帧：`1-120`，默认 `4`，步进 `1`
- 停留时间：`0-600000 ms`，默认 `800 ms`，步进 `100 ms`
- 冷却时间：`0-86400000 ms`，默认 `60000 ms`，步进 `1000 ms`
- 业务名称：长度 `1-80` 个字符
- 事件编码：长度 `2-64` 个字符，并遵守大写编码格式
- 级别：一般、重要、严重，默认重要

## 浏览器验收

- 页面：`http://127.0.0.1:8080/admin/`
- 三个检测输入的 `min`、`max`、`step` 和默认值元数据与契约一致
- 识别置信度提示显示范围、默认值和步进
- 告警置信度提示显示范围、默认值、步进以及不得低于检测置信度的约束
- 将识别置信度输入为 `1.5` 后点击保存，浏览器原生范围校验阻止提交

## 自动化验证

- `node --check app/static/app.js`：通过
- `python -m unittest tests.test_admin_model_parameters`：8/8 通过
- `python -m unittest discover -s tests -p "test_admin_*.py"`：25/25 通过
- `python -m unittest discover -s harness/tests -p "test_*.py"`：30/30 通过
- `python harness/harness.py validate`：通过
- `python harness/harness.py render`：通过
