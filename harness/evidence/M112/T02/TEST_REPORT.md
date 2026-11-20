# M112后端回归 测试报告

<!-- runtime-cleanup-batch2-20261112 -->
## 2026-11-12 第二批：已停止的临时测试数据库与空目录

任务：M05-T09；本报告对应9个目标目录、4899个文件、488551902字节。当前状态：已移入Windows回收站，并复核所有原路径不存在；失败结论与测试摘要不变。全部29个目录共13,797个文件、1,513,665,918字节；回收过程中7份受保护报告、任务状态、需求和runner文件哈希未变。回收站未清空。

仅清理前轮测试摘要已保留的runner隔离运行目录和空日志归档，不重跑业务测试、不改历史结果。非空目标只能含pg-data；逐一核对PG17、postmaster.opts指向该目录及随机回环端口、pg_ctl status=3/no server running、pg_controldata为shut down、无PID/重解析点/外部表空间，所有文件可独占读取且没有当日变更。系统服务进程可能不允许读取命令行，未把空命令行当作已停止证据，停止结论来自各目标自身的PG检查及文件占用检查。

只含空目录的目标不作为成功测试证明；其中没有结果的空运行目录无法推断历史执行结果。不得因清理补填通过。业务库、应用数据、源码、APK、模型、备份和发布产物不在清单内。

内容树SHA256：按完整路径排序，目录记D+相对路径，文件记F+相对路径+字节数+文件内容SHA256，再用LF连接并对UTF-8求SHA256；用于删除前一致性检查，不是数据库逻辑校验，也不保存原数据库内容。

| 原相对目录 | 文件数 | 字节数 | 内容树SHA256 | 停止状态/原端口 |
|---|---:|---:|---|---|
| .tmp/m112-lifecycle-10a3d7cy | 981 | 104483526 | b5383541620a1535fc56f5792058b95817b5f8d02aa02fcb4421e5a4c7e86bbc | shut down; 54034 |
| .tmp/m112-lifecycle-62ydrayj | 981 | 105466566 | 26fe4c631b522f866078a5f4134b42eea0b6e337e0dfdfb40d4250b3aff595fb | shut down; 61369 |
| .tmp/m112-lifecycle-8kw8k8fl | 0 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 | empty; none |
| .tmp/m112-lifecycle-9a2pjzbn | 981 | 105654982 | fd333b86b57aa4f08f95d5affb59f7a94aceb278e5cfde28a7894ed246dfc96a | shut down; 63971 |
| .tmp/m112-lifecycle-m7b23rp4 | 0 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 | empty; none |
| .tmp/m112-lifecycle-nrw3h_nj | 981 | 105908934 | 33605fd95291663393cef28b211bf836f94c34cc184a359571b0e9e76051ae62 | shut down; 57077 |
| .tmp/m112-lifecycle-qv58m3_4 | 975 | 67037894 | da6efe98527fb8d1eb9168e7e1d8e9e5cdd66a83f5585807154aa75267c4cf63 | shut down; 60014 |
| .tmp/m112-lifecycle-yvsiacxz | 0 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 | empty; none |
| harness/evidence/M112/T02/backend-final | 0 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 | empty; none |

恢复：执行回收后可在Windows回收站按原路径恢复；不清空回收站，不声称磁盘可用空间增加。原路径仅作为历史定位信息，不是现存附件。
<!-- end-runtime-cleanup-batch2-20261112 -->


本报告是该后端验收脚本范围的唯一长期测试输出。各次运行按原结果保留，失败、跳过和未验证不被后续成功覆盖；不替代Android/管理后台/生产联合验收。原始日志不是永久附件。

<!-- run:m112-lifecycle-m7b23rp4 -->
## 运行 m112-lifecycle-m7b23rp4

- 时间：2026-10-25T10:04:52.156259+00:00 → 2026-10-25T10:05:40.918190+00:00
- 原结果：True；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：False
- 资源：端口关闭=非PG或未知；剩余测试schema=未记录

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_model_catalog.py | 0 | 6 | 0/0/0 | OK |
| test_model_download.py | 0 | 6 | 0/0/0 | OK |
| test_stream_model_binding.py | 0 | 3 | 0/0/0 | OK |
| test_project_scene_authorization.py | 0 | 15 | 0/0/0 | OK |
| test_project_scene_installation.py | 0 | 23 | 0/0/0 | OK |
| test_assignment_targets.py | 0 | 14 | 0/0/3 | OK (skipped=3) |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。

- test_assignment_targets.py：test_atomic_failure_leaves_no_rows_or_audits (test_assignment_targets.AssignmentTargetsPostgresTests.test_atomic_failure_leaves_no_rows_or_audits) ... skipped 'requires isolated PostgreSQL schema' 
- test_assignment_targets.py：test_independent_writers_with_no_shared_process_locks_serialize_batch (test_assignment_targets.AssignmentTargetsPostgresTests.test_independent_writers_with_no_shared_process_locks_serialize_batch) ... skipped 'requires isolated PostgreSQL schema' 
- test_assignment_targets.py：test_reopen_independent_parameters_and_disable (test_assignment_targets.AssignmentTargetsPostgresTests.test_reopen_independent_parameters_and_disable) ... skipped 'requires isolated PostgreSQL schema' 

清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m112-lifecycle-m7b23rp4 -->

<!-- run:m112-lifecycle-nrw3h_nj -->
## 运行 m112-lifecycle-nrw3h_nj

- 时间：2026-10-25T10:00:24.852927+00:00 → 2026-10-25T10:02:19.296412+00:00
- 原结果：True；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：True
- 资源：端口关闭=True；剩余测试schema=[]

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_resource_lifecycle.py | 0 | 29 | 0/0/1 | OK (skipped=1) |
| test_resource_lifecycle_migration.py | 0 | 4 | 0/0/0 | OK |
| test_project_scenes.py | 0 | 18 | 0/0/0 | OK |
| test_project_model_assignments.py | 0 | 18 | 0/0/0 | OK |
| test_model_uninstall.py | 0 | 9 | 0/0/0 | OK |
| test_model_version_lifecycle.py | 0 | 21 | 0/0/0 | OK |
| test_project_scene_suite_persistence.py | 0 | 4 | 0/0/0 | OK |
| test_scene_composite_runtime_grants.py | 0 | 42 | 0/0/0 | OK |
| test_stream_config_persistence.py | 0 | 9 | 0/0/0 | OK |
| test_database.py | 0 | 6 | 0/0/0 | OK |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。

- test_resource_lifecycle.py：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'PostgreSQL variant only' 

清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m112-lifecycle-nrw3h_nj -->

<!-- run:m112-lifecycle-qv58m3_4 -->
## 运行 m112-lifecycle-qv58m3_4

- 时间：2026-10-25T10:09:30.615244+00:00 → 2026-10-25T10:10:04.703187+00:00
- 原结果：True；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：True
- 资源：端口关闭=True；剩余测试schema=[]

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_resource_lifecycle.py | 0 | 29 | 0/0/1 | OK (skipped=1) |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。

- test_resource_lifecycle.py：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'PostgreSQL variant only' 

清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m112-lifecycle-qv58m3_4 -->

<!-- run:m112-lifecycle-yvsiacxz -->
## 运行 m112-lifecycle-yvsiacxz

- 时间：2026-10-25T10:08:29.494534+00:00 → 2026-10-25T10:08:38.965751+00:00
- 原结果：True；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：False
- 资源：端口关闭=非PG或未知；剩余测试schema=未记录

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_resource_lifecycle.py | 0 | 29 | 0/0/13 | OK (skipped=13) |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。

- test_resource_lifecycle.py：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'requires PostgreSQL row locks' 
- test_resource_lifecycle.py：test_cleanup_failure_recovers_without_cascade_or_duplicate_facts (test_resource_lifecycle.LifecyclePostgreSqlTests.test_cleanup_failure_recovers_without_cascade_or_duplicate_facts) ... skipped 'requires isolated PostgreSQL schema' 
- test_resource_lifecycle.py：test_confirmed_database_and_failed_final_registry_ack_recovers (test_resource_lifecycle.LifecyclePostgreSqlTests.test_confirmed_database_and_failed_final_registry_ack_recovers) ... skipped 'requires isolated PostgreSQL schema' 
- test_resource_lifecycle.py：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePostgreSqlTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'requires isolated PostgreSQL schema' 
- test_resource_lifecycle.py：test_model_prepared_intent_blocks_new_scene_and_assignment_then_recovers (test_resource_lifecycle.LifecyclePostgreSqlTests.test_model_prepared_intent_blocks_new_scene_and_assignment_then_recovers) ... skipped 'requires isolated PostgreSQL schema' 
- test_resource_lifecycle.py：test_model_registry_commit_and_failed_audit_recovers_without_duplicate_tombstone (test_resource_lifecycle.LifecyclePostgreSqlTests.test_model_registry_commit_and_failed_audit_recovers_without_duplicate_tombstone) ... skipped 'requires isolated PostgreSQL schema' 
- test_resource_lifecycle.py：test_pending_intent_blocks_direct_runtime_download_and_registry_mutation (test_resource_lifecycle.LifecyclePostgreSqlTests.test_pending_intent_blocks_direct_runtime_download_and_registry_mutation) ... skipped 'requires isolated PostgreSQL schema' 
- test_resource_lifecycle.py：test_prepared_and_confirmed_revocation_block_late_stream_bind (test_resource_lifecycle.LifecyclePostgreSqlTests.test_prepared_and_confirmed_revocation_block_late_stream_bind) ... skipped 'requires isolated PostgreSQL schema' 
- test_resource_lifecycle.py：test_recovery_reads_stage_after_waiting_for_catalog_lock (test_resource_lifecycle.LifecyclePostgreSqlTests.test_recovery_reads_stage_after_waiting_for_catalog_lock) ... skipped 'requires isolated PostgreSQL schema' 
- test_resource_lifecycle.py：test_replay_rechecks_current_authority (test_resource_lifecycle.LifecyclePostgreSqlTests.test_replay_rechecks_current_authority) ... skipped 'requires isolated PostgreSQL schema' 
- test_resource_lifecycle.py：test_scene_tombstone_audit_outbox_members_and_replay_survive_restart (test_resource_lifecycle.LifecyclePostgreSqlTests.test_scene_tombstone_audit_outbox_members_and_replay_survive_restart) ... skipped 'requires isolated PostgreSQL schema' 
- test_resource_lifecycle.py：test_scene_transaction_rolls_back_on_outbox_failure (test_resource_lifecycle.LifecyclePostgreSqlTests.test_scene_transaction_rolls_back_on_outbox_failure) ... skipped 'requires isolated PostgreSQL schema' 
- test_resource_lifecycle.py：test_status_crash_after_registry_commit_replays_once (test_resource_lifecycle.LifecyclePostgreSqlTests.test_status_crash_after_registry_commit_replays_once) ... skipped 'requires isolated PostgreSQL schema' 

清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m112-lifecycle-yvsiacxz -->

<!-- historical-log-inventory-20261112 -->
## 2026-11-12 历史原始材料迁移

本节只归档测试事实和文件定位摘要，不包含完整日志。未重跑原业务测试；旧版本、环境缺失项仍未知。缺少result.json的中断轮次只记录可观察日志结束状态，不能据此补记整轮通过。

状态：2026-11-12已逐文件核对内容SHA256、路径边界和占用状态，将本清单85份原始文件（2,825,525字节）送入Windows回收站；回读核验原路径全部不存在。可从回收站恢复，未清空回收站，不声称释放磁盘空间。历史隔离数据库目录、图片、业务数据及其他任务输出不在本次清单内。

### 独立日志核验（包含中断、失败及重复副本）

| 原相对路径 | 执行数 | 结束标记 |
|---|---:|---|
| .tmp/m112-lifecycle-10a3d7cy/postgres.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m112-lifecycle-10a3d7cy/runner.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m112-lifecycle-10a3d7cy/test_database.py.log | 6 | FAILED (failures=1) |
| .tmp/m112-lifecycle-10a3d7cy/test_model_uninstall.py.log | 9 | FAILED (failures=3, errors=1) |
| .tmp/m112-lifecycle-10a3d7cy/test_model_version_lifecycle.py.log | 21 | OK |
| .tmp/m112-lifecycle-10a3d7cy/test_project_model_assignments.py.log | 18 | FAILED (failures=1) |
| .tmp/m112-lifecycle-10a3d7cy/test_project_scene_suite_persistence.py.log | 4 | OK |
| .tmp/m112-lifecycle-10a3d7cy/test_project_scenes.py.log | 18 | OK |
| .tmp/m112-lifecycle-10a3d7cy/test_resource_lifecycle.py.log | 20 | OK |
| .tmp/m112-lifecycle-10a3d7cy/test_scene_composite_runtime_grants.py.log | 42 | FAILED (failures=1) |
| .tmp/m112-lifecycle-10a3d7cy/test_stream_config_persistence.py.log | 9 | OK |
| .tmp/m112-lifecycle-62ydrayj/postgres.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m112-lifecycle-62ydrayj/runner.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m112-lifecycle-62ydrayj/test_database.py.log | 6 | OK |
| .tmp/m112-lifecycle-62ydrayj/test_model_uninstall.py.log | 9 | FAILED (failures=2, errors=1) |
| .tmp/m112-lifecycle-62ydrayj/test_model_version_lifecycle.py.log | 21 | OK |
| .tmp/m112-lifecycle-62ydrayj/test_project_model_assignments.py.log | 18 | FAILED (failures=1) |
| .tmp/m112-lifecycle-62ydrayj/test_project_scene_suite_persistence.py.log | 4 | OK |
| .tmp/m112-lifecycle-62ydrayj/test_project_scenes.py.log | 18 | OK |
| .tmp/m112-lifecycle-62ydrayj/test_resource_lifecycle.py.log | 25 | OK (skipped=1) |
| .tmp/m112-lifecycle-62ydrayj/test_resource_lifecycle_migration.py.log | 4 | OK |
| .tmp/m112-lifecycle-62ydrayj/test_scene_composite_runtime_grants.py.log | 42 | OK |
| .tmp/m112-lifecycle-62ydrayj/test_stream_config_persistence.py.log | 9 | OK |
| .tmp/m112-lifecycle-8kw8k8fl/test_model_uninstall.py.log | 9 | OK |
| .tmp/m112-lifecycle-8kw8k8fl/test_project_model_assignments.py.log | 18 | OK |
| .tmp/m112-lifecycle-9a2pjzbn/postgres.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m112-lifecycle-9a2pjzbn/runner.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m112-lifecycle-9a2pjzbn/test_database.py.log | 6 | OK |
| .tmp/m112-lifecycle-9a2pjzbn/test_model_uninstall.py.log | 9 | OK |
| .tmp/m112-lifecycle-9a2pjzbn/test_model_version_lifecycle.py.log | 21 | OK |
| .tmp/m112-lifecycle-9a2pjzbn/test_project_model_assignments.py.log | 18 | OK |
| .tmp/m112-lifecycle-9a2pjzbn/test_project_scene_suite_persistence.py.log | 4 | OK |
| .tmp/m112-lifecycle-9a2pjzbn/test_project_scenes.py.log | 18 | OK |
| .tmp/m112-lifecycle-9a2pjzbn/test_resource_lifecycle.py.log | 27 | OK (skipped=1) |
| .tmp/m112-lifecycle-9a2pjzbn/test_resource_lifecycle_migration.py.log | 4 | OK |
| .tmp/m112-lifecycle-9a2pjzbn/test_scene_composite_runtime_grants.py.log | 42 | OK |
| .tmp/m112-lifecycle-9a2pjzbn/test_stream_config_persistence.py.log | 9 | OK |
| .tmp/m112-lifecycle-m7b23rp4/test_assignment_targets.py.log | 14 | OK (skipped=3) |
| .tmp/m112-lifecycle-m7b23rp4/test_model_catalog.py.log | 6 | OK |
| .tmp/m112-lifecycle-m7b23rp4/test_model_download.py.log | 6 | OK |
| .tmp/m112-lifecycle-m7b23rp4/test_project_scene_authorization.py.log | 15 | OK |
| .tmp/m112-lifecycle-m7b23rp4/test_project_scene_installation.py.log | 23 | OK |
| .tmp/m112-lifecycle-m7b23rp4/test_stream_model_binding.py.log | 3 | OK |
| .tmp/m112-lifecycle-nrw3h_nj/postgres.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m112-lifecycle-nrw3h_nj/runner.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m112-lifecycle-nrw3h_nj/test_database.py.log | 6 | OK |
| .tmp/m112-lifecycle-nrw3h_nj/test_model_uninstall.py.log | 9 | OK |
| .tmp/m112-lifecycle-nrw3h_nj/test_model_version_lifecycle.py.log | 21 | OK |
| .tmp/m112-lifecycle-nrw3h_nj/test_project_model_assignments.py.log | 18 | OK |
| .tmp/m112-lifecycle-nrw3h_nj/test_project_scene_suite_persistence.py.log | 4 | OK |
| .tmp/m112-lifecycle-nrw3h_nj/test_project_scenes.py.log | 18 | OK |
| .tmp/m112-lifecycle-nrw3h_nj/test_resource_lifecycle.py.log | 29 | OK (skipped=1) |
| .tmp/m112-lifecycle-nrw3h_nj/test_resource_lifecycle_migration.py.log | 4 | OK |
| .tmp/m112-lifecycle-nrw3h_nj/test_scene_composite_runtime_grants.py.log | 42 | OK |
| .tmp/m112-lifecycle-nrw3h_nj/test_stream_config_persistence.py.log | 9 | OK |
| .tmp/m112-lifecycle-qv58m3_4/postgres.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m112-lifecycle-qv58m3_4/runner.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m112-lifecycle-qv58m3_4/test_resource_lifecycle.py.log | 29 | OK (skipped=1) |
| .tmp/m112-lifecycle-yvsiacxz/test_resource_lifecycle.py.log | 29 | OK (skipped=13) |
| harness/evidence/M112/T02/backend-final/pg-lifecycle-races.log | 29 | OK (skipped=1) |
| harness/evidence/M112/T02/backend-final/recovery-race-followup.log | 1 | FAILED (errors=1) |
| harness/evidence/M112/T02/backend-final/test_assignment_targets.py.log | 14 | OK (skipped=3) |
| harness/evidence/M112/T02/backend-final/test_database.py.log | 6 | OK |
| harness/evidence/M112/T02/backend-final/test_model_catalog.py.log | 6 | OK |
| harness/evidence/M112/T02/backend-final/test_model_download.py.log | 6 | OK |
| harness/evidence/M112/T02/backend-final/test_model_uninstall.py.log | 9 | OK |
| harness/evidence/M112/T02/backend-final/test_model_version_lifecycle.py.log | 21 | OK |
| harness/evidence/M112/T02/backend-final/test_project_model_assignments.py.log | 18 | OK |
| harness/evidence/M112/T02/backend-final/test_project_scene_authorization.py.log | 15 | OK |
| harness/evidence/M112/T02/backend-final/test_project_scene_installation.py.log | 23 | OK |
| harness/evidence/M112/T02/backend-final/test_project_scene_suite_persistence.py.log | 4 | OK |
| harness/evidence/M112/T02/backend-final/test_project_scenes.py.log | 18 | OK |
| harness/evidence/M112/T02/backend-final/test_resource_lifecycle.py.log | 29 | OK (skipped=1) |
| harness/evidence/M112/T02/backend-final/test_resource_lifecycle_migration.py.log | 4 | OK |
| harness/evidence/M112/T02/backend-final/test_scene_composite_runtime_grants.py.log | 42 | OK |
| harness/evidence/M112/T02/backend-final/test_stream_config_persistence.py.log | 9 | OK |
| harness/evidence/M112/T02/backend-final/test_stream_model_binding.py.log | 3 | OK |

### 失败/跳过/初始化异常摘要

- `.tmp/m112-lifecycle-10a3d7cy/test_database.py.log`：FAIL: test_schema_and_health_use_isolated_in_memory_database (test_database.DatabaseConfigurationTests.test_schema_and_health_use_isolated_in_memory_database) 
- `.tmp/m112-lifecycle-10a3d7cy/test_database.py.log`：AssertionError: Items in the first set but not the second: 
- `.tmp/m112-lifecycle-10a3d7cy/test_database.py.log`：FAILED (failures=1) 
- `.tmp/m112-lifecycle-10a3d7cy/test_model_uninstall.py.log`：ERROR: test_activate_persists_model_id_and_resolves_exact_server_path (test_model_uninstall.ModelCatalogUninstallTests.test_activate_persists_model_id_and_resolves_exact_server_path) 
- `.tmp/m112-lifecycle-10a3d7cy/test_model_uninstall.py.log`：FAIL: test_admin_can_uninstall_an_unbound_model (test_model_uninstall.ModelUninstallApiTests.test_admin_can_uninstall_an_unbound_model) 
- `.tmp/m112-lifecycle-10a3d7cy/test_model_uninstall.py.log`：FAIL: test_bound_model_is_rejected_before_catalog_mutation (test_model_uninstall.ModelUninstallApiTests.test_bound_model_is_rejected_before_catalog_mutation) 
- `.tmp/m112-lifecycle-10a3d7cy/test_model_uninstall.py.log`：FAIL: test_uninstall_requires_admin_and_maps_missing_model (test_model_uninstall.ModelUninstallApiTests.test_uninstall_requires_admin_and_maps_missing_model) 
- `.tmp/m112-lifecycle-10a3d7cy/test_model_uninstall.py.log`：KeyError: 'version' 
- `.tmp/m112-lifecycle-10a3d7cy/test_model_uninstall.py.log`：AssertionError: 401 != 200 
- `.tmp/m112-lifecycle-10a3d7cy/test_model_uninstall.py.log`：AssertionError: 401 != 409 
- `.tmp/m112-lifecycle-10a3d7cy/test_model_uninstall.py.log`：AssertionError: 401 != 404 
- `.tmp/m112-lifecycle-10a3d7cy/test_model_uninstall.py.log`：FAILED (failures=3, errors=1) 
- `.tmp/m112-lifecycle-10a3d7cy/test_project_model_assignments.py.log`：FAIL: test_project_owner_assignment_catalog_download_and_revoke_guard (test_project_model_assignments.ProjectModelAssignmentsApiTests.test_project_owner_assignment_catalog_download_and_revoke_guard) 
- `.tmp/m112-lifecycle-10a3d7cy/test_project_model_assignments.py.log`：AssertionError: 409 != 428 
- `.tmp/m112-lifecycle-10a3d7cy/test_project_model_assignments.py.log`：FAILED (failures=1) 
- `.tmp/m112-lifecycle-10a3d7cy/test_scene_composite_runtime_grants.py.log`：FAIL: test_postgres_legacy_token_migration_and_downgrade_guard (test_scene_composite_runtime_grants.CompositeGrantMigrationTests.test_postgres_legacy_token_migration_and_downgrade_guard) 
- `.tmp/m112-lifecycle-10a3d7cy/test_scene_composite_runtime_grants.py.log`：AssertionError: '20261022_21' != '20261025_22' 
- `.tmp/m112-lifecycle-10a3d7cy/test_scene_composite_runtime_grants.py.log`：FAILED (failures=1) 
- `.tmp/m112-lifecycle-62ydrayj/test_model_uninstall.py.log`：ERROR: test_bound_model_is_rejected_before_catalog_mutation (test_model_uninstall.ModelUninstallApiTests.test_bound_model_is_rejected_before_catalog_mutation) 
- `.tmp/m112-lifecycle-62ydrayj/test_model_uninstall.py.log`：FAIL: test_admin_can_uninstall_an_unbound_model (test_model_uninstall.ModelUninstallApiTests.test_admin_can_uninstall_an_unbound_model) 
- `.tmp/m112-lifecycle-62ydrayj/test_model_uninstall.py.log`：FAIL: test_bound_model_is_rejected_before_catalog_mutation (test_model_uninstall.ModelUninstallApiTests.test_bound_model_is_rejected_before_catalog_mutation) 
- `.tmp/m112-lifecycle-62ydrayj/test_model_uninstall.py.log`：AttributeError: 'types.SimpleNamespace' object has no attribute 'close' 
- `.tmp/m112-lifecycle-62ydrayj/test_model_uninstall.py.log`：AssertionError: 503 != 200 
- `.tmp/m112-lifecycle-62ydrayj/test_model_uninstall.py.log`：AssertionError: 503 != 409 
- `.tmp/m112-lifecycle-62ydrayj/test_model_uninstall.py.log`：FAILED (failures=2, errors=1) 
- `.tmp/m112-lifecycle-62ydrayj/test_project_model_assignments.py.log`：FAIL: test_project_owner_assignment_catalog_download_and_revoke_guard (test_project_model_assignments.ProjectModelAssignmentsApiTests.test_project_owner_assignment_catalog_download_and_revoke_guard) 
- `.tmp/m112-lifecycle-62ydrayj/test_project_model_assignments.py.log`：AssertionError: 409 != 503 
- `.tmp/m112-lifecycle-62ydrayj/test_project_model_assignments.py.log`：FAILED (failures=1) 
- `.tmp/m112-lifecycle-62ydrayj/test_resource_lifecycle.py.log`：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'PostgreSQL variant only' 
- `.tmp/m112-lifecycle-9a2pjzbn/test_resource_lifecycle.py.log`：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'PostgreSQL variant only' 
- `.tmp/m112-lifecycle-m7b23rp4/test_assignment_targets.py.log`：test_atomic_failure_leaves_no_rows_or_audits (test_assignment_targets.AssignmentTargetsPostgresTests.test_atomic_failure_leaves_no_rows_or_audits) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m112-lifecycle-m7b23rp4/test_assignment_targets.py.log`：test_independent_writers_with_no_shared_process_locks_serialize_batch (test_assignment_targets.AssignmentTargetsPostgresTests.test_independent_writers_with_no_shared_process_locks_serialize_batch) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m112-lifecycle-m7b23rp4/test_assignment_targets.py.log`：test_reopen_independent_parameters_and_disable (test_assignment_targets.AssignmentTargetsPostgresTests.test_reopen_independent_parameters_and_disable) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m112-lifecycle-nrw3h_nj/test_resource_lifecycle.py.log`：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'PostgreSQL variant only' 
- `.tmp/m112-lifecycle-qv58m3_4/test_resource_lifecycle.py.log`：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'PostgreSQL variant only' 
- `.tmp/m112-lifecycle-yvsiacxz/test_resource_lifecycle.py.log`：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'requires PostgreSQL row locks' 
- `.tmp/m112-lifecycle-yvsiacxz/test_resource_lifecycle.py.log`：test_cleanup_failure_recovers_without_cascade_or_duplicate_facts (test_resource_lifecycle.LifecyclePostgreSqlTests.test_cleanup_failure_recovers_without_cascade_or_duplicate_facts) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m112-lifecycle-yvsiacxz/test_resource_lifecycle.py.log`：test_confirmed_database_and_failed_final_registry_ack_recovers (test_resource_lifecycle.LifecyclePostgreSqlTests.test_confirmed_database_and_failed_final_registry_ack_recovers) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m112-lifecycle-yvsiacxz/test_resource_lifecycle.py.log`：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePostgreSqlTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m112-lifecycle-yvsiacxz/test_resource_lifecycle.py.log`：test_model_prepared_intent_blocks_new_scene_and_assignment_then_recovers (test_resource_lifecycle.LifecyclePostgreSqlTests.test_model_prepared_intent_blocks_new_scene_and_assignment_then_recovers) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m112-lifecycle-yvsiacxz/test_resource_lifecycle.py.log`：test_model_registry_commit_and_failed_audit_recovers_without_duplicate_tombstone (test_resource_lifecycle.LifecyclePostgreSqlTests.test_model_registry_commit_and_failed_audit_recovers_without_duplicate_tombstone) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m112-lifecycle-yvsiacxz/test_resource_lifecycle.py.log`：test_pending_intent_blocks_direct_runtime_download_and_registry_mutation (test_resource_lifecycle.LifecyclePostgreSqlTests.test_pending_intent_blocks_direct_runtime_download_and_registry_mutation) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m112-lifecycle-yvsiacxz/test_resource_lifecycle.py.log`：test_prepared_and_confirmed_revocation_block_late_stream_bind (test_resource_lifecycle.LifecyclePostgreSqlTests.test_prepared_and_confirmed_revocation_block_late_stream_bind) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m112-lifecycle-yvsiacxz/test_resource_lifecycle.py.log`：test_recovery_reads_stage_after_waiting_for_catalog_lock (test_resource_lifecycle.LifecyclePostgreSqlTests.test_recovery_reads_stage_after_waiting_for_catalog_lock) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m112-lifecycle-yvsiacxz/test_resource_lifecycle.py.log`：test_replay_rechecks_current_authority (test_resource_lifecycle.LifecyclePostgreSqlTests.test_replay_rechecks_current_authority) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m112-lifecycle-yvsiacxz/test_resource_lifecycle.py.log`：test_scene_tombstone_audit_outbox_members_and_replay_survive_restart (test_resource_lifecycle.LifecyclePostgreSqlTests.test_scene_tombstone_audit_outbox_members_and_replay_survive_restart) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m112-lifecycle-yvsiacxz/test_resource_lifecycle.py.log`：test_scene_transaction_rolls_back_on_outbox_failure (test_resource_lifecycle.LifecyclePostgreSqlTests.test_scene_transaction_rolls_back_on_outbox_failure) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m112-lifecycle-yvsiacxz/test_resource_lifecycle.py.log`：test_status_crash_after_registry_commit_replays_once (test_resource_lifecycle.LifecyclePostgreSqlTests.test_status_crash_after_registry_commit_replays_once) ... skipped 'requires isolated PostgreSQL schema' 
- `harness/evidence/M112/T02/backend-final/pg-lifecycle-races.log`：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'PostgreSQL variant only' 
- `harness/evidence/M112/T02/backend-final/recovery-race-followup.log`：ERROR: test_resource_lifecycle (unittest.loader._FailedTest.test_resource_lifecycle) 
- `harness/evidence/M112/T02/backend-final/recovery-race-followup.log`：ImportError: Failed to import test module: test_resource_lifecycle 
- `harness/evidence/M112/T02/backend-final/recovery-race-followup.log`：ModuleNotFoundError: No module named 'tests.test_resource_lifecycle' 
- `harness/evidence/M112/T02/backend-final/recovery-race-followup.log`：FAILED (errors=1) 
- `harness/evidence/M112/T02/backend-final/test_assignment_targets.py.log`：test_atomic_failure_leaves_no_rows_or_audits (test_assignment_targets.AssignmentTargetsPostgresTests.test_atomic_failure_leaves_no_rows_or_audits) ... skipped 'requires isolated PostgreSQL schema' 
- `harness/evidence/M112/T02/backend-final/test_assignment_targets.py.log`：test_independent_writers_with_no_shared_process_locks_serialize_batch (test_assignment_targets.AssignmentTargetsPostgresTests.test_independent_writers_with_no_shared_process_locks_serialize_batch) ... skipped 'requires isolated PostgreSQL schema' 
- `harness/evidence/M112/T02/backend-final/test_assignment_targets.py.log`：test_reopen_independent_parameters_and_disable (test_assignment_targets.AssignmentTargetsPostgresTests.test_reopen_independent_parameters_and_disable) ... skipped 'requires isolated PostgreSQL schema' 
- `harness/evidence/M112/T02/backend-final/test_resource_lifecycle.py.log`：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'PostgreSQL variant only' 

### 回收精确清单

SHA256为原文件内容摘要，仅用于迁移前一致性校验，不等价于保留日志。原路径作为历史标识，不是仍存在的附件链接。

| 原相对路径 | 字节数 | SHA256 |
|---|---:|---|
| .tmp/m112-lifecycle-10a3d7cy/postgres.log | 2334 | ed3f0c666d6c7a355323275faa6fc3e624ff8955c8c9f5d9519cb1ef8d49373e |
| .tmp/m112-lifecycle-10a3d7cy/runner.log | 1017 | 04c6a2a8da1c0ffa02f3986b4b1c75ded90643e40e57157ea6e8afc58e1c4367 |
| .tmp/m112-lifecycle-10a3d7cy/test_database.py.log | 2633 | 381bb1fbf6e8494b34d4c37b32ca62ca9e125d1bd96a509b4c0bc92a5aa063af |
| .tmp/m112-lifecycle-10a3d7cy/test_model_uninstall.py.log | 5778 | 41788a82716661a2ed0350fe0460345994b3d8ba149b1861a2c8e3db94bb0d9a |
| .tmp/m112-lifecycle-10a3d7cy/test_model_version_lifecycle.py.log | 4092 | 339b16bf5384750742818255454f614afaa378ccf0ba7eaaf4a9886428a7f37c |
| .tmp/m112-lifecycle-10a3d7cy/test_project_model_assignments.py.log | 81427 | a1a0adbbbdd5d830358fabc1efad9960a20fd2629cb15d5e8970667b2cab6d74 |
| .tmp/m112-lifecycle-10a3d7cy/test_project_scene_suite_persistence.py.log | 7788 | 38157fdd369e5029929d2a4ff2e47be1b222088369ad80cb3f03c9cf66d0f4a9 |
| .tmp/m112-lifecycle-10a3d7cy/test_project_scenes.py.log | 60657 | 500065a866772a937beace700d82a803c7c74a89e5a0820e7fd1efbd2111a480 |
| .tmp/m112-lifecycle-10a3d7cy/test_resource_lifecycle.py.log | 52428 | 9d7f347f998cfa320485f044bff5b25958f61f1c1b943dc2fdb5ee5095882f98 |
| .tmp/m112-lifecycle-10a3d7cy/test_scene_composite_runtime_grants.py.log | 145356 | b92432b39d67d1ee99b268291d72469da9fa3c1bb9b4ec77883fba6994532c60 |
| .tmp/m112-lifecycle-10a3d7cy/test_stream_config_persistence.py.log | 1782 | 2d5e99eb6f9068e50d316d6abac8db795444f8170ddb78e9bda4eb7647b766af |
| .tmp/m112-lifecycle-62ydrayj/postgres.log | 4801 | c7b62052802454b8dc1c045689c997127cc3272b77dd5ae8943cbd7c9f61efb3 |
| .tmp/m112-lifecycle-62ydrayj/runner.log | 1017 | 86fa596575e0bd30888db6c8893831bd435b64c09a4af8a65cf5d389d48e631e |
| .tmp/m112-lifecycle-62ydrayj/test_database.py.log | 1575 | e4d21646cda4f94282fabde006888f12f9e3c7da39633213062092a10db3bf3d |
| .tmp/m112-lifecycle-62ydrayj/test_model_uninstall.py.log | 21126 | d5a2bf171b5ecd133dd762adf62a31a8ba734ad6303dc64dc789bb5a131b23db |
| .tmp/m112-lifecycle-62ydrayj/test_model_version_lifecycle.py.log | 4092 | 0a55c7c9ee0b9cc2e3629a9622bbdad05c278644c648b4e898d788cb15402053 |
| .tmp/m112-lifecycle-62ydrayj/test_project_model_assignments.py.log | 81582 | 8fb6d6e3bd2a1c8fbdd2f49f9c3a15e9154af471a9b8f9bc3cda67825c73d88f |
| .tmp/m112-lifecycle-62ydrayj/test_project_scene_suite_persistence.py.log | 7788 | 6c20232239e69227fda8cc336198eb601172a2cec197bf62810ca42c426f5ca3 |
| .tmp/m112-lifecycle-62ydrayj/test_project_scenes.py.log | 60646 | 313e658db13058b6d57c91ff5296237e9ff33dc84f89ac4c4d4cc0a79e65ea86 |
| .tmp/m112-lifecycle-62ydrayj/test_resource_lifecycle.py.log | 64516 | d94e23b101d0b01aafadb62c6f09cb3c955fcfe0c7cee7f86138aadbf75d157a |
| .tmp/m112-lifecycle-62ydrayj/test_resource_lifecycle_migration.py.log | 16052 | 0fca6455d3df32946d07e81313c75a35d571715452f70b434cb4a4f921e60b73 |
| .tmp/m112-lifecycle-62ydrayj/test_scene_composite_runtime_grants.py.log | 144414 | 6420397784e2c1c1f016431bbae027ce7369ae4de3fadae00f78dd566289bd05 |
| .tmp/m112-lifecycle-62ydrayj/test_stream_config_persistence.py.log | 1782 | 66afab52651d9169cf07e123c9622639cbf0ac9ab6aaefaf10e14c273baaf976 |
| .tmp/m112-lifecycle-8kw8k8fl/test_model_uninstall.py.log | 12067 | d7c056b2bd17f4bc331d12663ee79996e35529a7463ac20e44278100c666d2cc |
| .tmp/m112-lifecycle-8kw8k8fl/test_project_model_assignments.py.log | 81158 | 90457064a1f0a285d186f23068248f1fc8fdbff60e597f20341b22f4e336b3f8 |
| .tmp/m112-lifecycle-9a2pjzbn/postgres.log | 2338 | 8bba46375b36a837676b0cbce8fe72d8e5073700257b22b0f4f0b990c5a4f1dd |
| .tmp/m112-lifecycle-9a2pjzbn/runner.log | 1017 | 7a1e0fcf20520f23bbc6f4bce0b84816940d96e1f1067ff5535309198245f923 |
| .tmp/m112-lifecycle-9a2pjzbn/test_database.py.log | 1575 | 96967e7e4adef83513df2cc7d9ee1052069981ab70dd7764ec13bcaa7a0a97db |
| .tmp/m112-lifecycle-9a2pjzbn/test_model_uninstall.py.log | 12071 | fe3979ae0d9ce2afe743d323b6c9c6e94672bf6517d1bf7c66dc4832a2672df5 |
| .tmp/m112-lifecycle-9a2pjzbn/test_model_version_lifecycle.py.log | 4092 | ef262f9a3a29ca74f81eee9b570495e9c5072d77b66fd155b3920b26b76a9e3c |
| .tmp/m112-lifecycle-9a2pjzbn/test_project_model_assignments.py.log | 81180 | 547f695c8126712c0c6d5ba19b42c48c608cbbd3ee57fec67cf5e1bd6119bfc3 |
| .tmp/m112-lifecycle-9a2pjzbn/test_project_scene_suite_persistence.py.log | 7788 | 0920a4c1400e7fb0a0052721b2d60f3a31bc76b7d233e6d7a5761336cbf116f8 |
| .tmp/m112-lifecycle-9a2pjzbn/test_project_scenes.py.log | 60669 | 36bbee9cb693d216ae4a9e9bc00be11c43d356e7229afa51cb3a79bc4e3218ba |
| .tmp/m112-lifecycle-9a2pjzbn/test_resource_lifecycle.py.log | 68403 | d39ab03e0e3dcfa399b43c1e216797adff8a832797aaf23f85f9005b46f12058 |
| .tmp/m112-lifecycle-9a2pjzbn/test_resource_lifecycle_migration.py.log | 16052 | 481bf62691521256e39d3cc8471068b16f4a316209a63492e1e096fa385709d1 |
| .tmp/m112-lifecycle-9a2pjzbn/test_scene_composite_runtime_grants.py.log | 144407 | e8e85015e12888fb38d0eaf6e16bdaf5aa4dd2dc312a29db71a0eceee6bf7e65 |
| .tmp/m112-lifecycle-9a2pjzbn/test_stream_config_persistence.py.log | 1782 | 3318460f12de9ee672c00f1319fa9ed8d1600f299b86a7dbb65d857784364f25 |
| .tmp/m112-lifecycle-m7b23rp4/result.json | 1489 | 6993dde43b10fcd482e415d4278a0e41fe018ae997e3fe2855388c821e5e97f7 |
| .tmp/m112-lifecycle-m7b23rp4/test_assignment_targets.py.log | 40563 | 0f793e6836e107271864815a79ea8acaf0c9c567c73259a127341322d44432e7 |
| .tmp/m112-lifecycle-m7b23rp4/test_model_catalog.py.log | 19559 | 23ed250a0df49197ab520e4a1e190f4680056d07104060c9c2fb7aec99426aa8 |
| .tmp/m112-lifecycle-m7b23rp4/test_model_download.py.log | 20602 | 15e791276e63809cba8ac1ddf1f749a23859cd76def904480426be993bd6c7d5 |
| .tmp/m112-lifecycle-m7b23rp4/test_project_scene_authorization.py.log | 84675 | b0a5ab543809f369c394647895c1460662731be4d48bb6eaa76496e37d1ee4a6 |
| .tmp/m112-lifecycle-m7b23rp4/test_project_scene_installation.py.log | 112932 | 7dc2c7e5e6cc00ba16ed32ccc6d375181aec849ddce4eb40b2e020ce96e06fa8 |
| .tmp/m112-lifecycle-m7b23rp4/test_stream_model_binding.py.log | 591 | 301a69e7a8f5b762b84b46ad3f6660a3e9731da1217775d57056f2d00cd50e34 |
| .tmp/m112-lifecycle-nrw3h_nj/postgres.log | 2331 | 46db4dc4969c9c4684f2748aa39487d3a46e76d85752b290e26caca06536e801 |
| .tmp/m112-lifecycle-nrw3h_nj/result.json | 2522 | 2c291b37ddcb9707911c289d2233b0af1b961634b088103792cca4d4b94032f0 |
| .tmp/m112-lifecycle-nrw3h_nj/runner.log | 1018 | 8bb91b897a0d529bae90698a6af0df51a059a5b48b69b2b9e259beb949fb11e1 |
| .tmp/m112-lifecycle-nrw3h_nj/test_database.py.log | 1575 | 57982cb7154a3332bce923b89a71a225d8097095826912b561e9d90293681eca |
| .tmp/m112-lifecycle-nrw3h_nj/test_model_uninstall.py.log | 12077 | 215ad0f0177eca3cd8238b79fe0dbb6ab21a61847419b4015247c1158dfc1279 |
| .tmp/m112-lifecycle-nrw3h_nj/test_model_version_lifecycle.py.log | 4092 | 29b9b42787856fbe120dcc3879cfe4cf8b5596cc28e645e932706728472836fd |
| .tmp/m112-lifecycle-nrw3h_nj/test_project_model_assignments.py.log | 81196 | e66c45fa2a02a50a161eb9811ee6e7e2894036f84a6df4563d1b2ff11f29c9b4 |
| .tmp/m112-lifecycle-nrw3h_nj/test_project_scene_suite_persistence.py.log | 7788 | 650979401dc139357628fa0fcdbac92e41b3c8b58514f586e959beabd881b70d |
| .tmp/m112-lifecycle-nrw3h_nj/test_project_scenes.py.log | 60652 | ceebaf2a5f3b2b590ed2cd6e84cd73689a2542cf19e0159a1f46e88384a7584f |
| .tmp/m112-lifecycle-nrw3h_nj/test_resource_lifecycle.py.log | 71857 | 4abf9088340bd886b5ef30a5cdf08f3be2f8a5b1d924949af02330718a54e95a |
| .tmp/m112-lifecycle-nrw3h_nj/test_resource_lifecycle_migration.py.log | 16052 | e439b0a0d7fd7fffd88b144dd840a9ad98250bc75f1c066abc01d16ad45fac00 |
| .tmp/m112-lifecycle-nrw3h_nj/test_scene_composite_runtime_grants.py.log | 144426 | e07106d372cc0786d651a04f649263680615e0de7b6706350c5e2d504c31c711 |
| .tmp/m112-lifecycle-nrw3h_nj/test_stream_config_persistence.py.log | 1782 | eb1ad3eb316e3bb6bc04ee14a5507a03857ec4710f0b6f3a6c99693ddc206336 |
| .tmp/m112-lifecycle-qv58m3_4/postgres.log | 1192 | 9dbc81bb1cd4025720a89f5ce1bbd4309a610ad5ff6e660cc577e5b9dd6f2364 |
| .tmp/m112-lifecycle-qv58m3_4/result.json | 675 | c36d419b307469e3be559b43b4671374b1cd03c0a0ba1a2cb261f33cd77d7d2e |
| .tmp/m112-lifecycle-qv58m3_4/runner.log | 1018 | 091f49b0b67b8b84e4c6131e2a6d29728dfb5175aae573fd15f88b97cfbbc176 |
| .tmp/m112-lifecycle-qv58m3_4/test_resource_lifecycle.py.log | 71869 | 41a358fa59b55fab48e70a61b2d8fe6d032d0a4bff76a23000c97259a74769b9 |
| .tmp/m112-lifecycle-yvsiacxz/result.json | 484 | c44c16b2455033e35b66eaff87914924a14bfc8accab3bee3f6def3f80688a0e |
| .tmp/m112-lifecycle-yvsiacxz/test_resource_lifecycle.py.log | 34996 | 5ed4586eec6e675c55349eaa6204692755970b8643747c024baca024cc51cb52 |
| harness/evidence/M112/T02/backend-final/pg-lifecycle-races.log | 71869 | 41a358fa59b55fab48e70a61b2d8fe6d032d0a4bff76a23000c97259a74769b9 |
| harness/evidence/M112/T02/backend-final/recovery-race-followup.log | 772 | b462b92377166a96d63f7bcc6e51582aa42c2c1c6d071403c1cf9b26095849fd |
| harness/evidence/M112/T02/backend-final/test_assignment_targets.py.log | 40563 | 0f793e6836e107271864815a79ea8acaf0c9c567c73259a127341322d44432e7 |
| harness/evidence/M112/T02/backend-final/test_database.py.log | 1575 | 57982cb7154a3332bce923b89a71a225d8097095826912b561e9d90293681eca |
| harness/evidence/M112/T02/backend-final/test_model_catalog.py.log | 19559 | 23ed250a0df49197ab520e4a1e190f4680056d07104060c9c2fb7aec99426aa8 |
| harness/evidence/M112/T02/backend-final/test_model_download.py.log | 20602 | 15e791276e63809cba8ac1ddf1f749a23859cd76def904480426be993bd6c7d5 |
| harness/evidence/M112/T02/backend-final/test_model_uninstall.py.log | 12077 | 215ad0f0177eca3cd8238b79fe0dbb6ab21a61847419b4015247c1158dfc1279 |
| harness/evidence/M112/T02/backend-final/test_model_version_lifecycle.py.log | 4092 | 29b9b42787856fbe120dcc3879cfe4cf8b5596cc28e645e932706728472836fd |
| harness/evidence/M112/T02/backend-final/test_project_model_assignments.py.log | 81196 | e66c45fa2a02a50a161eb9811ee6e7e2894036f84a6df4563d1b2ff11f29c9b4 |
| harness/evidence/M112/T02/backend-final/test_project_scene_authorization.py.log | 84675 | b0a5ab543809f369c394647895c1460662731be4d48bb6eaa76496e37d1ee4a6 |
| harness/evidence/M112/T02/backend-final/test_project_scene_installation.py.log | 112932 | 7dc2c7e5e6cc00ba16ed32ccc6d375181aec849ddce4eb40b2e020ce96e06fa8 |
| harness/evidence/M112/T02/backend-final/test_project_scene_suite_persistence.py.log | 7788 | 650979401dc139357628fa0fcdbac92e41b3c8b58514f586e959beabd881b70d |
| harness/evidence/M112/T02/backend-final/test_project_scenes.py.log | 60652 | ceebaf2a5f3b2b590ed2cd6e84cd73689a2542cf19e0159a1f46e88384a7584f |
| harness/evidence/M112/T02/backend-final/test_resource_lifecycle.py.log | 71857 | 4abf9088340bd886b5ef30a5cdf08f3be2f8a5b1d924949af02330718a54e95a |
| harness/evidence/M112/T02/backend-final/test_resource_lifecycle_migration.py.log | 16052 | e439b0a0d7fd7fffd88b144dd840a9ad98250bc75f1c066abc01d16ad45fac00 |
| harness/evidence/M112/T02/backend-final/test_scene_composite_runtime_grants.py.log | 144426 | e07106d372cc0786d651a04f649263680615e0de7b6706350c5e2d504c31c711 |
| harness/evidence/M112/T02/backend-final/test_stream_config_persistence.py.log | 1782 | eb1ad3eb316e3bb6bc04ee14a5507a03857ec4710f0b6f3a6c99693ddc206336 |
| harness/evidence/M112/T02/backend-final/test_stream_model_binding.py.log | 591 | 301a69e7a8f5b762b84b46ad3f6660a3e9731da1217775d57056f2d00cd50e34 |
| harness/evidence/M112/T02/backend-result.json | 484 | c44c16b2455033e35b66eaff87914924a14bfc8accab3bee3f6def3f80688a0e |
| harness/evidence/M112/T02/backend-supplement-result.json | 1489 | 6993dde43b10fcd482e415d4278a0e41fe018ae997e3fe2855388c821e5e97f7 |
| harness/evidence/M112/T02/postgres-full-result.json | 2522 | 2c291b37ddcb9707911c289d2233b0af1b961634b088103792cca4d4b94032f0 |
| harness/evidence/M112/T02/postgres-result.json | 675 | c36d419b307469e3be559b43b4671374b1cd03c0a0ba1a2cb261f33cd77d7d2e |

<!-- run:m112-lifecycle-1tmme5bo -->
## 运行 m112-lifecycle-1tmme5bo

- 时间：2026-11-12T06:42:38.829614+00:00 → 2026-11-12T06:42:39.319958+00:00
- 原结果：True；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：4e9faf48dbd4800f7af7d09599337ec2d872840d；工作区：有未提交/未跟踪变更
- 环境：Windows-11-10.0.26200-SP0; Python 3.13.15；隔离PostgreSQL：False
- 资源：端口关闭=非PG或未知；剩余测试schema=未记录

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_test_report_retention.py | 0 | 14 | 0/0/0 | OK |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。


清理状态：完成：本次隔离临时目录已删除；不保留原始日志/结果JSON/测试数据库

<!-- end-run:m112-lifecycle-1tmme5bo -->

<!-- run:m112-lifecycle-yz04cmk6 -->
## 运行 m112-lifecycle-yz04cmk6

- 时间：2026-11-12T06:50:24.322084+00:00 → 2026-11-12T06:50:36.660558+00:00
- 原结果：True；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：4e9faf48dbd4800f7af7d09599337ec2d872840d；工作区：有未提交/未跟踪变更
- 环境：Windows-11-10.0.26200-SP0; Python 3.13.15；隔离PostgreSQL：True
- 资源：端口关闭=True；剩余测试schema=[]

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_test_report_retention.py | 0 | 14 | 0/0/0 | OK |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。


清理状态：完成：本次隔离临时目录已删除；不保留原始日志/结果JSON/测试数据库

<!-- end-run:m112-lifecycle-yz04cmk6 -->
