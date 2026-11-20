# M36-T02 本地验证记录

日期：2026-10-19。范围：模型目标端能力、就绪/发布、项目分配与下载。

## 实现与验证

- 声明 `supportedTargets`，历史条目按有效产物派生，非法声明 fail closed；保留旧 platform 与 ready 别名。
- 纯 PC 上传不触发 Android 自动转换；纯移动不可用于 PC 激活/推理；转换固定精确版本。
- 发布按端验证来源、许可证、运行验证/张量契约，独立记录 publishedTargets；双端可 PC 先发布，再转换和发布移动端。
- 移动发布生成内容寻址、Ed25519 签名的 releaseEligible Manifest，原转换文件不变；签名失败不更新注册表，重试不改已发布字节。
- 项目目录、分配与下载按端复验，跨端/越权拒绝；发布同时记录注册表 modelHistory 与平台审计。

## 真实执行的命令

使用 `.venv/Scripts/python.exe`，`PYTHONPATH=tests`，TEMP/TMP 指向项目 `.harness-python-temp`。

`unittest` 模块：test_conversion_api、test_model_version_lifecycle、test_project_model_assignments、test_model_catalog、test_model_download、test_model_marketplace_automation、test_project_model_assignment_storage。

结果：79 项，74 passed、5 skipped（未启用隔离 PostgreSQL 测试），0 failures/errors，73.763 秒。包括真实生成 Ed25519 密钥并验签、签名失败原子性、原文件不变、移动后补发布、SQLite 参数快照存储、CAS 和 API 权限。

`python -m unittest discover -s harness/tests -p 'test_*.py'`：34 passed。`python harness/harness.py validate`：passed。目标文件 `git diff --check`：passed（仅 CRLF 提示）。

## 限制与风险

- 模型转换/推理测试使用 FakeRunner 和合成文件，不代表真实模型质量、Android 真机或生产性能验收。
- 未执行生产迁移、部署、Git 提交或推送；未启用隔离 PostgreSQL 回归。
- 注册表 JSON 与数据库审计无跨存储事务；modelHistory 与发布状态原子持久化，平台审计失败可通过重试补记。
- 保留已登记产物启动完整性 fail-fast，不把“端独立就绪”解释为容忍已登记文件被破坏。
- 场景 CRUD/授权由后续 M36-T03/T04 交付，多模型同步/异步执行不在第一阶段。
