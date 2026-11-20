# M33-T50 场景批准参数快照校验

代码修复及自动回归完成；人工状态：**待人工复测**，未代填人工验收通过。

## 真实故障与边界

2026-11-02 只读核查 Default Project：`cj02`（场景02）于21:27:21新建、21:27:50批准，场景修订为2。
它引用已恢复的 helmet 2.0.0/mobile，以及尚未恢复的 ppe 1.0.0/mobile。
ppe 移动端项目分配 `cebb3b7b-0a84-4867-abcd-2264bf1ac4e8` 的分配修订仍为1，
其参数快照及 `cj02` 中的冻结快照均缺少 `schemaVersion`、`source`、`updatedAt`。
因此重新创建场景仍会复制旧分配的不完整快照，移动端按契约拒绝读取。

M33-T49 只恢复了 test01 引用的 helmet 移动端和 ppe PC端，没有恢复 ppe 移动端。
本次发现另一个后端缺口：审批只校验基础身份和参数容器，未校验移动端所需元数据，导致不完整快照也能批准。
设备错误布局见 `device-error.xml`；观测设备 emulator-5554 实际为 API30，不作为 API27 验收结果。

本任务没有改动业务数据库、重新保存用户分配、重新审批 `cj02`、安装模型或启动识别。
共享8080后端未重启，仍运行本轮修改前代码；不能将本次代码回归写成运行环境恢复成功。

## 修复内容

- `app/project_scenes.py`：批准场景时严格校验冻结的项目模型参数快照，检查精确身份、参数修订、schemaVersion=2、合法source、显式updatedAt和继承修订关系；不推测来源，不用最新参数替换批准参数。
- 任一成员无效时返回409 `project_model_snapshot_invalid`，用中文说明恢复路径，附成员、项目分配、模型版本、目标端及无效字段；不泄露原始参数内容。
- 失败保持整次批准的原子性，场景修订、旧审批、冻结参数和成功审计均不变化。
- `tests/test_scene_snapshot_approval.py`：新增旧分配被新场景引用、混合成员整体拒绝、畸形元数据、有效默认/自定义/继承、正常重存恢复及SQLite/PostgreSQL持久化回归。
- `tests/test_project_scenes.py`：补全合法存储夹具元数据，保留原有“default快照不包含inheritedRevision”的断言。
- `docs/project-scene-suite-v2.md`：记录校验规则、错误契约和显式恢复要求。
- `tools/accept_scene_snapshot_approval.py`：仅使用随机回环端口的一次性PostgreSQL，显式覆盖数据库环境，检查数据库身份、清理测试schema并停止实例。

## 真实测试结果

| 检查 | 结果 | 证据 |
|---|---|---|
| 7组后端相关回归 | 176项：145通过、31条件跳过、0失败；88.028秒 | `backend-regression-final.log` |
| 隔离PostgreSQL审批回归 | 5/5通过，无跳过 | `SceneSnapshotApprovalPostgresTests.log` |
| 隔离PostgreSQL场景参数回归 | 11/11通过，无跳过 | `SceneParameterPostgresTests.log` |
| 隔离PostgreSQL项目模型清单回归 | 8/8通过，无跳过 | `ProjectModelInventoryPostgreSqlTests.log` |
| Harness单元测试 | 34/34通过；complete后复查经批准重跑仍34/34通过 | `harness-tests.log`、`harness-final-recheck.log` |
| 隔离数据库清理 | remainingSchemas=[]，portClosed=true，passed=true | `postgres-result.json` |

非PG回归的31项条件跳过不视为通过；上述24项PG用例为单独执行的相关覆盖，不声称覆盖全部31项。
最终PG实例目录为 `.tmp/m33-t50-pg-mbvytb8p/data`，端口50840，实例已停止；未使用业务数据库连接串。

保留首次失败材料：`SceneParameterPostgresTests.first-run.log`、`postgres-result.first-run.json`。
首轮PG失败原因是合法夹具额外加入 `inheritedRevision:null`，与既有“不包含该键”的断言冲突；修正夹具后重跑上述全部相关回归通过，未删改原有断言。
首轮PG临时实例端口49824也已停止。另一次默认沙箱尝试在写临时runner日志时被ACL拒绝，未启动数据库；随后通过批准的受控命令完成隔离PG验收。

Harness complete之后的默认沙箱复查有5项临时目录ACL错误，随后按权限流程获准在沙箱外执行同一命令，34/34通过（0.070秒）；未修改测试或文件权限。validate和render通过，完成记录已读回。

## 待执行与人工复测

1. 获准后加载新版后端代码，防止其他旧坏快照再次被批准；当前运行服务尚未加载本修复。
2. 如获用户授权，通过正常鉴权/CAS API，在参数值不变的前提下重存 ppe 1.0.0/mobile 的上述分配，再重新批准 `cj02`；执行前重新核对修订，不能复用T49对test01的操作授权。
3. 移动端点击刷新，确认场景02正常显示，再由人工验证模型准备和使用流程。

当前 `cj02` 的数据尚未恢复，因此不能宣称手机上的本次错误已消失。
其他旧分配不批量补写、不清库；不自动迁移历史参数。未提交或推送Git。
