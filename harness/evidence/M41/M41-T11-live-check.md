# M41-T11 本机集成核验

- 环境：`server-video-service` 本机开发 API（127.0.0.1:8080）、管理台 Vite（127.0.0.1:5173）、PostgreSQL 开发库；凭据未写入证据。
- 迁移前 Alembic revision：`20261104_33`；迁移后：`20261105_34`。
- 迁移前后核对：项目级资料 5 条、建议历史 10 条，数量未改变。
- 系统发布目录可读，初始 V1 含 5 条；Default Project 固定绑定 V1/revision 1，合并资料 API 返回 5 条且项目已有资料作为项目覆盖保留。
- Default Project 最近一次已保存建议仍可读取（HTTP 200）。未生成新的告警建议或改写任何告警处置。
- 后端进程仅重启了经核验的本机 `uvicorn app.main:app --port 8080`；5173 管理台保持运行。新路由由鉴权 API 实测通过。
- 隔离 PostgreSQL 17 专项：系统初始数据迁移、项目固定版本、项目停用遮蔽、发布不自动升级旧项目、新项目固定最新发布版本全部通过；临时 schema 清理且实例端口关闭。运行日志副本：`harness/evidence/M111/T02/runs/m111-updates-j5r86gn2/test_system_alert_knowledge_postgresql.py.log`。
