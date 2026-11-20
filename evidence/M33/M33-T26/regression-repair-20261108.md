# M33-T26 后端回归修复记录

日期：2026-11-08。范围为本地后端回归修复，不是生产部署/发布验收。

## 环境与安全边界

- 使用 `tools/run_m33_regression.py` 将被测源码和明确测试资源复制到 `.tmp/m33-t26-*`；不读取应用 `.env`，不修改原模型清单或已上传模型。
- 每轮用 `D:/PostgreSQL/bin` 创建独立 PostgreSQL data directory、随机回环端口和 `aiyolo_test` 角色；启动后验证 data_directory/current_user。
- 显式设置测试 DATABASE_URL，启用 PostgreSQL 集成测试；测试子进程拒绝非回环连接/DNS，YOLO 使用离线设置，不放开外网以绕过错误。
- 每轮记录源文件哈希、测试数量、失败/错误/跳过列表、日志、残留 schema、数据库停止结果及端口关闭结果。未连接开发库/生产库，未改 K8s、Secret、Nginx、APK发布或Git提交。

## 根因与修复

1. 原历史7项残留范围：当前隔离环境未复现告警验证的3项外键错误与项目业务配置2项404，保持相应业务逻辑和断言；流 API/E2E 使用已退役的输出语义且缺少当前必须的场景方案。改为通过真实模型分配、场景创建/批准建立测试条件，以JPEG入站、同源鉴权预览及 `ingesting` 状态验证现行接口。
2. PostgreSQL ORM/迁移差异：`uq_alert_disposition_operation` 在既有迁移中是唯一索引；3个知识库/方案字段在迁移中是JSON。修正 `app/database.py` 元数据与既有DDL一致，未重写历史迁移、未取消唯一性保护。通过 head 下Alembic差异检查验证。此项属于产品代码变更，后续视频镜像须重建新候选标签。
3. 历史降级测试跨越新增不可逆迁移：改为在相应历史revision执行原降级/数据保护断言，保留升级到head和head元数据核对；多项目测试分别验证历史旧审批不可逆门禁和最新不可变知识库门禁，未放宽downgrade保护。
4. 项目管理数据库fixture原来只建空表，缺少迁移写入的不可变知识库版本。改为执行真实Alembic迁移；默认项目也会被创建，暂停/归档断言改为按projectId定位，不能用返回列表首项代表被测项目。
5. 流恢复fixture缺少已审核参数中的alertRules；补齐明确空规则。流持久化/告警隔离测试使用独立TemporaryDirectory，不依赖其他测试先创建 `.test-db`。
6. 双项目流测试保留角色限制、跨项目404、撤权/暂停/归档、凭据脱敏和退役路由拒绝断言；增加真实两组JPEG经ingest到preview的内容区分和同源cookie跨项目拒绝，不再写入无效的动态latest_frame属性。RTSP源保持disabled，未启动外部采集。
7. SceneMember/ScenePlan golden按当前项目模型清单及cameraPolicy契约逐项修正；不是自动用实际输出覆盖快照。退役的验证入口按既有410契约核对无写入，跨项目404仍保留。
8. `ProjectApiSupport` 仅对成功进入生命周期的TestClient调用exit；新增启动失败清理测试，保留原始异常并恢复补丁/配置。模型完整性测试在独立临时目录创建合成文件，继续验证缺失文件、哈希和必填元数据拒绝。
9. 隔离运行器补齐Dockerfile.app-updates、.env.example、Harness状态、前端包清单/既有构建、转换manifest与只读移动端合同文件；缺失这些资源属于测试副本准备问题，不能据此修改产品行为。

## 已完成的复测

- 原故障范围：23项、0失败、0错误、0跳过，`m33-t26-jhdxf2rh-focused-after.json`。
- 清理回归：1项通过，`m33-t26-f7pp86_v-fixture-cleanup.json`。
- 剩余迁移/权限/持久化/双项目隔离/契约：71项、0失败、0错误、0跳过，`m33-t26-ds8trfqk-remaining-after.json`。
- 既有管理后台两个真实构建托管：7项、0失败、0错误、0跳过，`m33-t26-uetwasgp-frontend-hosting.json`。只测试已存在的2026-11-06构建，没有宣称重新构建前端。
- Harness：34项通过，validate通过。首次受Windows沙箱临时目录权限影响出现5项PermissionError，经授权原命令重跑全部通过；未修改Harness测试以掩盖权限错误。
- 修复前完整基线：1391项、15失败、33错误、16跳过，`m33-t26-rmocmsps-full-after.json`；对应原始结果和日志已另存同目录。
- 最终完整回归：**1409项，1393通过，0失败，0错误，16跳过**，用时839.973秒，退出0。证据 `m33-t26-q_rd5tbx-full-final.json` 及其 `*-tests-result.json`/`*-tests.log`。临时端口63411，data directory对应runtime q_rd5tbx；残留schema为[]、stopExitCode=0、portClosed=true。
- 完成前重新核对全量报告中的257个app/tests源码SHA-256，均与当前工作区一致；`git diff --check`退出0。运行器在全量启动后仅增加dist-preview复制，随后单独完成上述7项托管复测；未改变被测产品代码或测试断言。

## 跳过项说明（不等同通过）

最终全量运行保留16个明确skip，不把它们计入1393项成功执行：

- 1项前端双构建托管：全量启动时副本未包含dist-preview，已补齐复制并在独立复测7/7中真实通过；未篡改全量原始16项跳过记录。
- 2项是SQLite变体不支持PostgreSQL锁/并发，匹配PostgreSQL变体已在本轮完整回归执行通过（资源删除竞争、运行授权只消费一次）。
- 剩余13项是显式可选的真实环境集成：MinIO保留/真实APK上传与交付，真实Android SDK验包，真实浏览器与服务故障恢复，运行器所有的数据库进程重启，以及真实旧MediaMTX二进制拒绝检查。本轮未提供这些环境开关/材料，不能宣称这些检查通过；详细逐项原因保留在tests-result.json。
- 本次已真实运行其余PostgreSQL集成与schema迁移，不是以统一关闭数据库测试得到绿色结果。

## 发布限制

- M34-T06真实视频/YOLO/PC/API27联合验收、M42-T10双来源升级/恢复及其他部署门禁不能由本任务代替。
- 正式APK继续用用户指定外部存储，不新增APK专用卷；升级开启配置不变；生产数据库、签名身份、水位和登记记录均不变。
- 新镜像构建、生产工作负载切换、APK来源关联/发布和设备安装均未执行。
