# M42-T01 验证记录

日期：2026-10-29。范围：FR-12 升级契约和数据模型；未实现/验收 APK 分发 HTTP 路由、后台页面或 Android 安装。

## 交付

- `app/app_updates/contract.py`：严格 v1 类型和 API/错误码清单；共同 schema、金样及文档位于 `docs/app-update-v1*`。
- `app/app_updates/signatures.py`：对实际字节验签的参考解析器，受控公钥、请求上下文、修订和有效期检查。
- `app/app_updates/models.py` 与迁移 `20261029_27`：十张持久表，身份/工件/双来源/策略/历史/回退/设备/回执/审计；已注册到 metadata、Alembic 和启动 schema 门禁。
- 正式包名 com.aiyolo.inspection，首正式版本码 1；没有创建或信任生产私钥、证书或 debug 签名。

## 可复验结果

| 检查 | 结果 | 证据 |
|---|---|---|
| v1 契约/金样/签名、SQLite、真实 PostgreSQL | 24/24 通过，无跳过 | T01-20261029T043920Z-test_app_update_all.py.log |
| 数据库配置/health/schema 回归 | 6/6 通过 | T01-20261029T043920Z-test_database.py.log |
| 既有知识库迁移重跑/回退回归 | 2/2 通过 | T01-20261029T043920Z-test_alert_advice_knowledge_migration.py.log |
| 最后 schema 增补设备统计枚举后的契约复验 | 6/6 通过 | T01-contract-final.log |
| Server Harness | 34/34 通过 | T01-harness-tests.log |
| Android Harness（只读回归，未改 App） | 53/53 通过 | 本轮执行输出 |
| Python compileall / 已跟踪改动 diff whitespace | 通过 | 本轮执行输出 |

PostgreSQL runner：`tools/accept_m42_contract.py`；最终隔离运行结果 `T01-20261029T043920Z-result.json`。专用端口 64040，随机 data directory `.tmp/m42-contract-o64tl0ym/pg-data`，角色 aiyolo_app，DB postgres。已核对实例身份，测试 schema 全部清理，专用实例已关闭、端口已关闭。开发端点 5432/aiyolo_dev 未连接或迁移。

最后仅将 OperationResult.deviceCounts 扩展为包含 not_discovered/uncontacted，已执行契约复验；没有修改已通过 PostgreSQL 的 DDL/存储模型。类型和数据库不把未联系设备虚构为成功。

## 失败与修复轨迹

- 初次沙箱测试遭遇 Windows 临时目录拒绝访问，按审批在沙箱外重跑；没有将权限故障当作产品测试通过。
- 初次运行生成迁移中残留 JSONB 渲染符号，修正为显式 JSON/JSONB variant；SQLite 检查连接未关闭导致临时文件占用，已通过上下文管理关闭。
- 初次完整 runner 的数据库健康测试采用旧固定表集合，新增十张表后断言失败；已更新同一门禁断言并通过。初次失败证据保留 `T01-initial-result.json` 和未带时间戳的初次测试日志。
- 后续全部 runner 使用时间戳证据，不覆盖失败日志。

## 跨端交接指纹

- schema SHA-256：`0b2782fe6055c7e649b0c45d90b2635fc73857730f070ec1d998ccb542e413ad`
- golden SHA-256：`a52b7cc1e09ed732608baf2add227225e37cc2d021a2400bc6123fedf158380a`

Android M118-T01 必须使用以上文件及指纹建立兼容测试。当前没有启动或完成 M118，不宣称 JVM/设备已消费金样。

## 后续边界

- M42-T02：真实 APK 核验器；T03/T04：MinIO 和外链完整读取/网络边界；T05/T07/T08：发布 CAS、全局版本高水位、已验证对象不可变、回退事务和实时账号鉴权；T06：管理页面。
- DB 局部约束和本次 SQL CAS 测试不能替代后续业务并发/权限/真实 APK 证据。
- 生产签名、正式显示名称、HTTPS 域名、MinIO/外部托管、许可证/SBOM、API27/厂商真机及历史数据对账仍由后续门禁处理。
