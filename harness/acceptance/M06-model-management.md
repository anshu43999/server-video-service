---
major_task_id: M06
result: passed
owner: codex
accepted_at: 2026-09-02T18:20:09+08:00
---

# M06 模型资产迁移与转换管理测试验收报告

## 验收结论

**通过**

模型资产迁移、双目标转换工具、注册校验、活动模型切换和管理后台回归验收通过。移动端原有 YOLO11n PT/TFLite 已迁移到独立服务项目；服务端默认使用 yolo11n.pt，转换工具可生成 ONNX/PT 与移动端 LiteRT INT8，并以 Manifest/哈希追溯。

## 验收标准

- [x] 移动端现有 YOLO11n 开发模型资产已复制并登记到服务端
- [x] 支持 PT 转换为移动端 TFLite 和服务端可用模型格式
- [x] 管理 API 和页面可以查看模型、校验元数据并选择服务端活动模型
- [x] 模型来源、哈希、标签、用途和许可证状态可追溯，未具备发布条件的资产保持冻结

## 小任务完成记录

| ID | 小任务 | 状态 | 记录 |
|---|---|---|---|
| M06-T01 | 迁移并登记移动端现有 YOLO11n 模型资产 | completed | [M06-T01.md](../records/M06/M06-T01.md) |
| M06-T02 | 实现 PT 到移动端与服务端模型的转换工具 | completed | [M06-T02.md](../records/M06/M06-T02.md) |
| M06-T03 | 接入模型注册、校验与活动模型切换 | completed | [M06-T03.md](../records/M06/M06-T03.md) |
| M06-T04 | 完成模型转换与管理回归验证 | completed | [M06-T04.md](../records/M06/M06-T04.md) |

## 测试结果

- 27 server tests passed; 7 harness tests passed; ONNX checker passed; PT real CPU inference previously passed; LiteRT Windows-native limitation and ONNX Runtime/Python 3.13 gap explicitly frozen

## 验收证据

- harness/records/M06/M06-T01.md; harness/records/M06/M06-T02.md; harness/records/M06/M06-T03.md; harness/records/M06/M06-T04.md; models/registry.json; tools/convert_model.py; app/model_catalog.py

## 遗留风险

- LiteRT 导出器在 Windows 原生环境不支持，移动端 TFLite 转换需 WSL2 Ubuntu/Linux x86 或 macOS；该限制已冻结并在工具中给出明确提示。
- 当前 Python 3.13 环境没有可用的 `onnxruntime` wheel，因此只完成 ONNX 结构校验，ONNX 端到端推理需在目标部署 Python/平台安装 `requirements-onnx.txt` 后复测。
- 当前 YOLO11n/COCO 资产仅用于内部开发链路，业务五类精度和商业发布资格未验收，`releaseEligible=false` 保持不变。
