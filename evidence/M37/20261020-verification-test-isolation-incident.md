# 复核测试隔离事故记录

日期：2026-10-20。此记录不含数据库地址、凭据或业务行内容。

## 已确认事实

首次执行旧 `test_alert_verification_api.py` / `test_alert_verification_provider_api.py`
时，其 setUp/tearDown 调用了仍绑定配置数据库的全局复核 store 的 `reset()`。
旧方法对 `alert_verifications` 和 `alert_verification_config` 执行无 WHERE 的 DELETE，
相关测试之后在临时内存项目写配置时出现外键失败，暴露了此隔离缺口。

事后只读计数显示两个配置库表均为 0 行。本轮没有事前计数，无法确定是否存在、
或丢失了多少原有业务复核结果/策略；不得宣称“没有数据损失”。reset 路径未删除
事件或图片。本次没有执行备份恢复，也没有伪造策略/额度回填。

## 已修正

- 两个 API 测试在任何 reset 前显式切换到独立内存复核 store，结束恢复绑定。
- 生产方法 `reset()` 默认拒绝数据库删除；只有明确指定
  `allow_database_delete=True` 才可清空隔离测试库，新增防护回归。
- 后续 PostgreSQL 联调均使用随机 schema，迁移后测试并自动回收，不触碰 public 业务表。

## 恢复边界

工作区存在 2026-09-28 的备份，时间早且为旧 schema，不能自动恢复到当前多项目库；
需先确认原表是否有需要恢复的数据、可用的最近备份/PITR，以及明确恢复授权。
保留现状并向用户报告，未对业务库执行额外修改。
