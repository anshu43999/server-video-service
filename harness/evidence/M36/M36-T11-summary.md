# M36-T11 本地服务与内部测试发布

## 结果

- 本地 `127.0.0.1:8080` 已升级到 `20261020_17`，健康和新版 OpenAPI 参数路由正常。
- 停止前精确核对原监听进程 38032 / 父进程 17856；仅操作该实例，未部署容器、未修改前端构建。
- 数据库备份：`backups/M36-T11-20261020-144036/aiyolo_dev-before.dump`，4,729,455 bytes，SHA256 `8fb76b6bd6eb2fe183b865b9ca26042be746c915b6bb0963ba1a108a80c399e6`。备份含敏感数据库内容，保留在受 ACL 保护且不提交的本机目录；独立临时 PostgreSQL 实例已恢复并逐表核对数量和规范化摘要。临时实例已关闭，文件保留可恢复。
- 迁移前后全部原业务字段摘要一致；新增字段均为空，未隐式批准任何旧场景。原模型权重、注册表、环境配置在服务更新步骤均未改变。

## 真实发布与隔离项目

用户在本对话明确确认“仅授权内部测试发布”。平台 admin 通过正常发布 API 发布 `uploaded-06b4dd2f10544673ab723226f91c34a7` 的 2.0.0 和 3.0.0，**仅 mobile**，PC 仍未获准。原因中记录内部测试限制；此结论不是商业/生产分发许可，也没有声称完成 PC runtime 验证。现有发布 API 的 `licenseApproved` 是布尔值，目录/Manifest 的 `approved` 字样本身不能表达内部使用限制，必须同时保留本记录和发布审计理由。

两版发布前后真实下载核对 size/SHA256，并使用独立受信 Ed25519 公钥验证 Manifest 签名。发布只生成合法 release Manifest，不改变 TFLite 权重：

| version | TFLite SHA256 | published Manifest SHA256 |
|---|---|---|
| 2.0.0 | `84f1a2cd2cb9ad08cb62a5cb40b37f8872f53b6194c50ce6722938ae0c44703e` | `dc70cf7aad35fe73bc08314795746f1658050a48ec98b65e8f919cb6f5a90488` |
| 3.0.0 | `92ef171e77e1ad479a517e1515b1188022fcb3489f1141b65e52b9a39b839c5b` | 见真实 `result.json` |

继续复用原 A/B 两个 `m104-*` 项目，无重复创建项目。gly 明确审批 8 个场景快照：各项目 image、video、multi、versioned。ptcy 真实获取精确 Android 参数和签名包；项目用户审批均 403。单模型 resolve 成功，真实双模型 sync/async resolve 明确 409，未伪称已支持编排。

Default Project 的 members/model-assignments/scenes 在操作前后完全相等，原 helmet1.0.0 产物未变。

## 证据与测试

- `M36-T11-runtime-20261020-144036.json`：备份恢复、迁移、配置保留、健康与 smoke。
- `M36-T11-service-20261020-144312/result.json` / `api-trace.json` / `default-before.json`：2 个真实发布版本、8 个场景、真实哈希签名与角色检查。
- 首次发布前检查发现测试驱动对大写 SHA256 比较错误，**尚未发布任何版本即停止**。失败证据 `M36-T11-service-20261020-144247/` 保留，修复为大小写无关比较后重跑通过。
- `M36-T11-tools.log`：6 项工具单测通过，覆盖大小写摘要、精确版本 URL、真实错误签名与坏字节拒绝、外域 URL 不发送令牌、进程维护预检不停止服务。
- `M36-T11-harness.log`：34 项 Harness 单测通过；validate/render 通过。
- M36-T10 完成后 Harness 复检曾因 Windows 沙箱临时目录权限报错；同命令获准在沙箱外重跑 34 项全通过，日志 `M36-T10-harness-postcomplete.log`。未改测试或绕过门禁。

## 后续边界

Android 生产工作台接线和真实版本升级/回滚尚未因此自动完成，仍由 M104 后续任务执行。缓存参数/模型文件不是离线运行授权。未提交或推送 Git。
