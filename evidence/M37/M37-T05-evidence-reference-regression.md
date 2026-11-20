# M37-T05 证据引用与反馈净化验收

验收日期：2026-10-20。服务端目录：`E:\aiyolo\server-video-service`。

## 验证范围

- 旧路径 fixture、重复 evidence 目录、旧/新鉴权 API 引用及版本后缀。
- 历史 data URL 的反馈持久化、列表/详情/处置响应和训练导出不泄漏图片。
- SERVER_STREAM 误报证据可读取，匿名拒绝、跨项目不可访问。
- 误报后补传证据自动修复反馈；缺图原因显式保留。
- PostgreSQL 反馈重开可读，事件唯一图片 backing 不被元数据净化删除。

## 已执行验证

- 9 个相关测试模块组合：66 项通过（最终收尾新增缺失原因测试另行记录）。
- 远程 PostgreSQL + MinIO：`test_alert_postgresql.py` 7 项通过，
  含真实 MinIO 唯一临时对象上传/清理往返；使用随机隔离 schema 后自动回收。
- 未使用 Docker 替代已有远程服务；未输出凭据，未扫描或删除业务对象。

## 边界

历史便携路径保持兼容，不承诺对应文件均存在；迁移工具通过 fixture 回归，
本次未对业务历史执行 apply。此记录不替代 M37-T06/T07 或 Android M105 验收。
