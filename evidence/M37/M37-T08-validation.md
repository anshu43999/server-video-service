# M37-T08 验证记录

日期：2026-10-28

## 实现结果

- 新 `SERVER_STREAM` 告警在 MinIO 已配置时，从同一确认帧生成 `thumbnail/1` 与 `original/1`。
- 两级对象键包含项目、事件、类型、版本和内容摘要；事件在两级都保存成功后才持久化和通知。
- 任一层写入失败会尝试移除已写对象并中止告警登记；后续帧可使用稳定事件 ID 重试。
- 默认证据接口通过事件仓储持锁读取缩略图；显式版本化接口读取缩略图或原图。
- PC 详情对服务端新告警提供“查看原图”，历史单级服务端证据只显示兼容提示，不伪造原图。
- 旧本地文件证据路径保留为开发/历史兼容，不被声明为两级证据。

## 自动化结果

- Python 聚焦测试：`test_server_alert_runtime` 6、`test_analysis_alert_closure` 11、`test_analysis_only` 12、`test_alert_evidence` 14、`test_alert_disposition` 9、`test_project_alert_isolation` 2、`test_mobile_alert_ingest` 21、`test_alert_disposition_api` 4，全部通过。
- PostgreSQL：隔离临时 PostgreSQL 执行全部 Alembic 迁移，并通过 `test_server_alert_postgresql` 1 项。
- 管理后台：Vitest 21 files / 136 tests 全部通过；`vue-tsc --noEmit` 与 production Vite build 通过。
- Harness：首次使用系统 TEMP 运行时因当前受限环境拒绝该目录写入而出现 5 个临时目录权限错误；将 `TEMP/TMP` 指向仓库内 `.harness-python-temp` 后 34 项全部通过，`validate`、`render` 通过。失败不是功能断言失败。

## 环境边界

本轮复用既有 M37-T07 对真实远程 MinIO 的上传、读取、摘要和清理验收；新增服务端自动生成两级对象使用内存对象适配器完成确定性单元/持久化/隔离测试，未向业务 MinIO 写入新的测试对象，也未操作生产或 Default Project 数据。完整真实视频源 + 真实 MinIO 的联合链路仍属于 M34-T06 的本地三端验收范围。
