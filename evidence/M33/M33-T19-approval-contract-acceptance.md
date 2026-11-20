# M33-T19 验收证据

日期：2026-10-14；执行目录：`E:/aiyolo/server-video-service`；执行者：codex。

## 交付范围

任务：冻结移动旧数据归属审批契约与可执行测试金样。**仅为契约/测试交付，不是审批功能上线或移动迁移完成。**

- `docs/mobile-legacy-ownership-approval.md`：mobile-legacy-approval-v1 的权限、完整绑定、签名、规范清单、状态/TTL、幂等/CAS、撤销竞态、审计/隐私和跨仓库承接矩阵。
- `tests/legacy_approval_reference.py`：测试专用内存状态机，不被 app 代码导入；真实P-256签名校验；注册/账号权限作为可信前提。
- `tests/fixtures/mobile_legacy_approval_cases.json`：六类数据的规范清单和12条可移植流程场景。
- `tests/test_mobile_legacy_approval_contract.py`：64项真实执行的单测，其中12项运行JSON流程金样，其余52项覆盖身份/签名/绑定/重放/并发/TTL/结果/隐私等。
- `tests/test_local_project_baseline.py`：依赖回归现要求 T18 等待 T22，审批本地任务不依赖容器部署或Android任务的完成状态。
- RBAC总契约、本地验收决策追加引用。Harness新增T19–T22并保留原T17/T18全部完成标准和阻塞证据。

## 冻结的重要决定

1. 原服务origin/实例 + accountId + 安装公钥 + 数据集/代次 + 双清单摘要 + 固定默认项目全部绑定。摘要只能证明一致性；管理员依据账号映射和设备保管/使用证据核实归属，未知/混用不批准。审批人不能是申请人自己。
2. 请求签名证明安装密钥持有，不宣称硬件证明或旧数据所有权；原机器/设备服务token不能代替人类会话。nonce防重放与业务幂等分开，实时权限优先于重放缓存。
3. 领取后永久保留同一operation，TTL/崩溃只可恢复，不自动改投/再导入。回执保留历史，布尔/浮点不被当作整数计数；相同结果不重复首次业务审计。
4. 本地复制/提交后仍隐藏，在线回执和激活许可完成才可显示。撤销不能原子撤回离线Room写入，明确最多剩余60秒许可窗口，原件保留；既已导出/截屏的数据不可遥控收回。
5. 先本地全流程验收后容器部署；T05/T22共用证据但不互等completed，不能因增加审批免除旧APK升级恢复、ENOSPC、长稳及完整回归。

## 实际执行的测试

原始输出：`evidence/M33/M33-T19-tests-20261014.log`。

| 命令 | 最终结果 |
| --- | --- |
| `.venv/Scripts/python.exe -m unittest discover -s tests -p test_mobile_legacy_approval_contract.py -v` | 64/64 通过，含12流程金样 |
| `.venv/Scripts/python.exe -m unittest discover -s tests -p test_local_project_baseline.py -v` | 2/2 通过 |
| `.venv/Scripts/python.exe -m unittest discover -s tests -p test_project_authorization.py -v` | 11/11 通过 |
| `python -m unittest discover -s harness/tests -p 'test_*.py'` | 授权重跑30/30通过 |
| `python harness/harness.py validate` / `render` | 通过并生成任务板 |
| 本次7个文档/测试文件逐行空白检查；任务状态 scoped git diff --check | 通过；已有LF/CRLF提示不修改无关文件 |

过程如实记录：首轮58项通过；加严历史/计数校验后发现两项测试自身问题（断言插入位置、格式错误预期码），修正后最终64项通过。首次Harness沙箱运行因Windows Temp目录权限产生4项错误，按权限流程申请沙箱外重跑后30项全部通过，未绕过测试或修改Harness规则。现有FastAPI/Starlette测试依赖发出httpx弃用告警，不在本任务变更依赖。

## 完成标准逐项对应

| 标准 | 证据 |
| --- | --- |
| 平台管理员审批/普通用户不可维护/数据隔离 | 非管理员与机器主体拒绝、自批拒绝、10个独立绑定替换负向、动态成员/账号/安装/项目状态测试 |
| 完整申请/批准/拒绝/领取/确认/撤销/恢复流程 | 12条JSON场景；拒绝终态+新代次重新审批单测 |
| TTL/修订/幂等/并发/重放/禁止改投 | 时钟边界、nonce签名、改体幂等冲突、CAS竞争、并行claim、领取后永久锁定测试 |
| 中断/撤销竞态不作虚假安全承诺 | commit后撤销、回执丢失、重启离线、租约过期、恢复同operation、60秒窗口模拟 |
| API/错误/审计/隐私 | 契约接口表/错误码表/隐私字段约束；模型安全审计不含摘要和凭据测试 |
| 全流程任务承接且本地优先 | 契约追踪表；T19→T20→T21→T22→T18→T17；依赖回归通过 |

## 未完成范围与风险

- T20尚未实现挑战注册、持久化审批API、动态新增能力、真实SQLite/PG并发/事务/重启/审计故障、限流/序列化/缓存头；不要把参考模型接入生产绕过这些验收。
- T21尚未交付审批管理PC页面和真实浏览器验收；原PC任务完成不包含本次新增页面。
- T22尚未完成真实服务、PC、隔离PG、API27联调；这里的crash是状态模拟，不是设备SIGKILL/断电证据。
- Android M100-T05仍阻塞；双摘要适配、Keystore、隐藏分区、结果清单、读取/上传来源与短许可、ENOSPC、旧APK完整升级恢复和长稳仍须真正实现/验收。
- 必须有受控历史保管/归属证据及不同于申请人的审核管理员；缺失就保持隔离，不虚构证明。
- 不访问生产库、不迁移用户真数据、不启动容器部署、不提交/推送Git、不修改App任务状态。
