# M111后端回归 测试报告

<!-- runtime-cleanup-batch2-20261112 -->
## 2026-11-12 第二批：已停止的临时测试数据库与空目录

任务：M05-T09；本报告对应20个目标目录、8898个文件、1025114016字节。当前状态：已移入Windows回收站，并复核所有原路径不存在；失败结论与测试摘要不变。全部29个目录共13,797个文件、1,513,665,918字节；回收过程中7份受保护报告、任务状态、需求和runner文件哈希未变。回收站未清空。

仅清理前轮测试摘要已保留的runner隔离运行目录和空日志归档，不重跑业务测试、不改历史结果。非空目标只能含pg-data；逐一核对PG17、postmaster.opts指向该目录及随机回环端口、pg_ctl status=3/no server running、pg_controldata为shut down、无PID/重解析点/外部表空间，所有文件可独占读取且没有当日变更。系统服务进程可能不允许读取命令行，未把空命令行当作已停止证据，停止结论来自各目标自身的PG检查及文件占用检查。

只含空目录的目标不作为成功测试证明；其中没有结果的空运行目录无法推断历史执行结果。不得因清理补填通过。业务库、应用数据、源码、APK、模型、备份和发布产物不在清单内。

内容树SHA256：按完整路径排序，目录记D+相对路径，文件记F+相对路径+字节数+文件内容SHA256，再用LF连接并对UTF-8求SHA256；用于删除前一致性检查，不是数据库逻辑校验，也不保存原数据库内容。

| 原相对目录 | 文件数 | 字节数 | 内容树SHA256 | 停止状态/原端口 |
|---|---:|---:|---|---|
| .tmp/m111-updates-_76nf_xp | 974 | 42764960 | 04e08c832ee4a66a6695115a3903618cdb92cc95eed026efae8c951f42e52f51 | shut down; 52018 |
| .tmp/m111-updates-_lhxs1wi | 0 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 | empty; none |
| .tmp/m111-updates-2xf46wxd | 0 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 | empty; none |
| .tmp/m111-updates-5ij9hnv_ | 0 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 | empty; none |
| .tmp/m111-updates-813z1f6m | 0 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 | empty; none |
| .tmp/m111-updates-9pa4qn39 | 0 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 | empty; none |
| .tmp/m111-updates-akzl6gd3 | 0 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 | empty; none |
| .tmp/m111-updates-anixhc62 | 976 | 90401440 | 97c1e08e0b3b041196f0de277925e5912dd792226259fd88a3f9c4b82519aef3 | shut down; 61090 |
| .tmp/m111-updates-c7vnopjz | 974 | 42764960 | 53bf4a240c424849263cfe636fa01dcecc1df6a0e18ff7abf2cd0d2884e5605d | shut down; 52723 |
| .tmp/m111-updates-ewzd816c | 1005 | 156584608 | 9b6426c4b05abaf787eb02156e102e1f48bddde33c805607ae6fe1111dced685 | shut down; 61278 |
| .tmp/m111-updates-fgw0imvd | 977 | 116460192 | 64b02972c393e7051178dfe683d0d0ec87ff19c95dd8e897700d471b6f66a8e2 | shut down; 57175 |
| .tmp/m111-updates-hz7umfqy | 0 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 | empty; none |
| .tmp/m111-updates-j5r86gn2 | 974 | 42764960 | b23f64860451208ea401496d6a3d8356e08008e85e87082863a3910df03cfd44 | shut down; 50104 |
| .tmp/m111-updates-khvnz4ga | 1006 | 182733472 | 763497a7fc7135d4f521e8d5cd0dc21efb9527d3462ceb50278d3cb873ab50ea | shut down; 52782 |
| .tmp/m111-updates-mtjkafns | 1006 | 177490592 | 98ec7877637eef4c739ef80221940c1928f1974523a69ce90c90b8ce0ee0763d | shut down; 58345 |
| .tmp/m111-updates-rdfxv035 | 0 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 | empty; none |
| .tmp/m111-updates-rq2735ut | 1006 | 173148832 | 15ebb4269bba1e899b0dab104cef1e39ad3317c2c922303008678278172b50fe | shut down; 59440 |
| .tmp/m111-updates-s6an_rhe | 0 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 | empty; none |
| .tmp/m111-updates-ugc2ckw9 | 0 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 | empty; none |
| harness/evidence/M111/T02/runs | 0 | 0 | ae228135368be022b0a64769effcfa8cd2c9f6df35d1c01ad24ae76b90d28094 | empty; none |

恢复：执行回收后可在Windows回收站按原路径恢复；不清空回收站，不声称磁盘可用空间增加。原路径仅作为历史定位信息，不是现存附件。
<!-- end-runtime-cleanup-batch2-20261112 -->


本报告是该后端验收脚本范围的唯一长期测试输出。各次运行按原结果保留，失败、跳过和未验证不被后续成功覆盖；不替代Android/管理后台/生产联合验收。原始日志不是永久附件。

<!-- run:m111-updates-2xf46wxd -->
## 运行 m111-updates-2xf46wxd

- 时间：2026-10-25T12:47:15.120401+00:00 → 2026-10-25T12:47:51.887659+00:00
- 原结果：False；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：False
- 资源：端口关闭=非PG或未知；剩余测试schema=未记录

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_model_download.py | 0 | 6 | 0/0/0 | OK |
| test_resource_lifecycle.py | 0 | 29 | 0/0/13 | OK (skipped=13) |
| test_assignment_targets.py | 0 | 14 | 0/0/3 | OK (skipped=3) |
| test_project_scenes.py | 0 | 18 | 0/0/5 | OK (skipped=5) |
| test_database.py | 1 | 6 | 1/0/0 | FAILED (failures=1) |

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
- test_assignment_targets.py：test_atomic_failure_leaves_no_rows_or_audits (test_assignment_targets.AssignmentTargetsPostgresTests.test_atomic_failure_leaves_no_rows_or_audits) ... skipped 'requires isolated PostgreSQL schema' 
- test_assignment_targets.py：test_independent_writers_with_no_shared_process_locks_serialize_batch (test_assignment_targets.AssignmentTargetsPostgresTests.test_independent_writers_with_no_shared_process_locks_serialize_batch) ... skipped 'requires isolated PostgreSQL schema' 
- test_assignment_targets.py：test_reopen_independent_parameters_and_disable (test_assignment_targets.AssignmentTargetsPostgresTests.test_reopen_independent_parameters_and_disable) ... skipped 'requires isolated PostgreSQL schema' 
- test_project_scenes.py：test_approval_persists_audit_and_rechecks_membership_inside_transaction (test_project_scenes.ScenePostgreSqlTests.test_approval_persists_audit_and_rechecks_membership_inside_transaction) ... skipped 'requires isolated PostgreSQL schema' 
- test_project_scenes.py：test_audit_failure_rolls_back_scene_and_members_and_inactive_guard (test_project_scenes.ScenePostgreSqlTests.test_audit_failure_rolls_back_scene_and_members_and_inactive_guard) ... skipped 'requires isolated PostgreSQL schema' 
- test_project_scenes.py：test_independent_stores_serialize_first_creation_and_updates (test_project_scenes.ScenePostgreSqlTests.test_independent_stores_serialize_first_creation_and_updates) ... skipped 'requires isolated PostgreSQL schema' 
- test_project_scenes.py：test_new_scene_audit_failure_leaves_no_partial_data (test_project_scenes.ScenePostgreSqlTests.test_new_scene_audit_failure_leaves_no_partial_data) ... skipped 'requires isolated PostgreSQL schema' 
- test_project_scenes.py：test_reopen_order_replace_isolation_and_revision (test_project_scenes.ScenePostgreSqlTests.test_reopen_order_replace_isolation_and_revision) ... skipped 'requires isolated PostgreSQL schema' 
- test_database.py：FAIL: test_schema_and_health_use_isolated_in_memory_database (test_database.DatabaseConfigurationTests.test_schema_and_health_use_isolated_in_memory_database) 
- test_database.py：AssertionError: Items in the first set but not the second: 
- test_database.py：FAILED (failures=1) 

清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m111-updates-2xf46wxd -->

<!-- run:m111-updates-813z1f6m -->
## 运行 m111-updates-813z1f6m

- 时间：2026-10-25T14:42:05.918737+00:00 → 2026-10-25T14:42:14.292651+00:00
- 原结果：True；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：False
- 资源：端口关闭=非PG或未知；剩余测试schema=未记录

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_model_update_projection.py | 0 | 22 | 0/0/11 | OK (skipped=11) |
| test_metrics_api.py | 0 | 1 | 0/0/0 | OK |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。

- test_model_update_projection.py：test_assignment_approval_generates_exact_target_and_scan_is_idempotent (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_assignment_approval_generates_exact_target_and_scan_is_idempotent) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_assignment_domain_event_rolls_back_with_business_write (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_assignment_domain_event_rolls_back_with_business_write) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_authority_revocation_is_checked_before_periodic_scan (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_authority_revocation_is_checked_before_periodic_scan) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_disabled_account_retires_binding_without_dispatching_old_token (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_disabled_account_retires_binding_without_dispatching_old_token) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_inventory_without_approval_cannot_create_executable_target (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_inventory_without_approval_cannot_create_executable_target) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_original_scene_selection_not_expanded_by_new_member (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_original_scene_selection_not_expanded_by_new_member) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_publish_notice_is_not_install_permission_and_cold_bind_recovers (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_publish_notice_is_not_install_permission_and_cold_bind_recovers) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_registry_failure_keeps_events_and_projection_then_restart_repairs (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_registry_failure_keeps_events_and_projection_then_restart_repairs) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_retired_source_cannot_be_revived_by_newer_inventory_revision (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_retired_source_cannot_be_revived_by_newer_inventory_revision) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_running_target_preserved_and_successors_coalesce_to_current_approval (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_running_target_preserved_and_successors_coalesce_to_current_approval) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_two_entries_cannot_alias_one_retained_source (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_two_entries_cannot_alias_one_retained_source) ... skipped 'requires isolated PostgreSQL' 

清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m111-updates-813z1f6m -->

<!-- run:m111-updates-_76nf_xp -->
## 运行 m111-updates-_76nf_xp

- 时间：2026-11-05T09:27:33.769889+00:00 → 2026-11-05T09:27:47.739029+00:00
- 原结果：False；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：True
- 资源：端口关闭=True；剩余测试schema=[]

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_system_alert_knowledge_postgresql.py | 1 | 1 | 0/1/0 | FAILED (errors=1) |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。

- test_system_alert_knowledge_postgresql.py：ERROR: test_migrated_project_inheritance_publication_and_masking (test_system_alert_knowledge_postgresql.SystemAlertKnowledgePostgreSQLTests.test_migrated_project_inheritance_publication_and_masking) 
- test_system_alert_knowledge_postgresql.py：FAILED (errors=1) 

清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m111-updates-_76nf_xp -->

<!-- run:m111-updates-akzl6gd3 -->
## 运行 m111-updates-akzl6gd3

- 时间：2026-10-25T14:57:10.207361+00:00 → 2026-10-25T14:57:59.227710+00:00
- 原结果：False；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：False
- 资源：端口关闭=非PG或未知；剩余测试schema=未记录

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_model_updates.py | 0 | 42 | 0/0/19 | OK (skipped=19) |
| test_model_update_projection.py | 1 | 24 | 1/0/12 | FAILED (failures=1, skipped=12) |
| test_model_update_api.py | 0 | 7 | 0/0/0 | OK |
| test_model_update_delivery.py | 0 | 9 | 0/0/0 | OK |
| test_project_scene_installation.py | 0 | 24 | 0/0/0 | OK |
| test_metrics_api.py | 0 | 1 | 0/0/0 | OK |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。

- test_model_updates.py：test_binding_idempotent_epoch_retirement_and_old_account_isolation (test_model_updates.UpdatePostgreSqlTests.test_binding_idempotent_epoch_retirement_and_old_account_isolation) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_cleanup_compacts_only_old_terminal_history_and_rebuilds_current_truth (test_model_updates.UpdatePostgreSqlTests.test_cleanup_compacts_only_old_terminal_history_and_rebuilds_current_truth) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_current_permission_revocation_hides_snapshot_and_delta (test_model_updates.UpdatePostgreSqlTests.test_current_permission_revocation_hides_snapshot_and_delta) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_expired_and_cross_device_tickets_fail_closed (test_model_updates.UpdatePostgreSqlTests.test_expired_and_cross_device_tickets_fail_closed) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_failed_projection_transaction_does_not_advance_sequence (test_model_updates.UpdatePostgreSqlTests.test_failed_projection_transaction_does_not_advance_sequence) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_install_quarantine_rollback_are_distinct_persisted_facts (test_model_updates.UpdatePostgreSqlTests.test_install_quarantine_rollback_are_distinct_persisted_facts) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_invalid_criteria_and_digest_cannot_be_success (test_model_updates.UpdatePostgreSqlTests.test_invalid_criteria_and_digest_cannot_be_success) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_inventory_atomic_revision_and_capacity (test_model_updates.UpdatePostgreSqlTests.test_inventory_atomic_revision_and_capacity) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_metrics_survive_service_restart_and_measure_document_bytes (test_model_updates.UpdatePostgreSqlTests.test_metrics_survive_service_restart_and_measure_document_bytes) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_missing_fcm_configuration_preserves_dirty_and_marks_disabled (test_model_updates.UpdatePostgreSqlTests.test_missing_fcm_configuration_preserves_dirty_and_marks_disabled) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_no_database_has_no_memory_success (test_model_updates.UpdatePostgreSqlTests.test_no_database_has_no_memory_success) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_offline_batch_receipts_and_unchanged_progress_do_not_push_again (test_model_updates.UpdatePostgreSqlTests.test_offline_batch_receipts_and_unchanged_progress_do_not_push_again) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_pending_retention_survives_ninety_days_and_cleanup_expires_old_cursor (test_model_updates.UpdatePostgreSqlTests.test_pending_retention_survives_ninety_days_and_cleanup_expires_old_cursor) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_push_lease_does_not_clear_new_dirty_and_token_is_retired (test_model_updates.UpdatePostgreSqlTests.test_push_lease_does_not_clear_new_dirty_and_token_is_retired) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_rate_limits_shared_between_store_instances (test_model_updates.UpdatePostgreSqlTests.test_rate_limits_shared_between_store_instances) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_receipts_immutable_duplicate_stale_and_permanent_audit (test_model_updates.UpdatePostgreSqlTests.test_receipts_immutable_duplicate_stale_and_permanent_audit) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_snapshot_fixed_watermark_pages_then_incremental (test_model_updates.UpdatePostgreSqlTests.test_snapshot_fixed_watermark_pages_then_incremental) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_token_generation_rotation_and_equal_generation_conflict (test_model_updates.UpdatePostgreSqlTests.test_token_generation_rotation_and_equal_generation_conflict) ... skipped 'requires isolated PostgreSQL' 
- test_model_updates.py：test_unbind_idempotence_and_no_cross_account (test_model_updates.UpdatePostgreSqlTests.test_unbind_idempotence_and_no_cross_account) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：FAIL: test_running_target_preserved_and_successors_coalesce_to_current_approval (test_model_update_projection.UpdateProjectionTests.test_running_target_preserved_and_successors_coalesce_to_current_approval) 
- test_model_update_projection.py：AssertionError: 'accepted' != 'stale' 
- test_model_update_projection.py：FAILED (failures=1, skipped=12) 
- test_model_update_projection.py：test_assignment_approval_generates_exact_target_and_scan_is_idempotent (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_assignment_approval_generates_exact_target_and_scan_is_idempotent) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_assignment_domain_event_rolls_back_with_business_write (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_assignment_domain_event_rolls_back_with_business_write) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_authority_revocation_is_checked_before_periodic_scan (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_authority_revocation_is_checked_before_periodic_scan) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_disabled_account_retires_binding_without_dispatching_old_token (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_disabled_account_retires_binding_without_dispatching_old_token) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_inventory_without_approval_cannot_create_executable_target (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_inventory_without_approval_cannot_create_executable_target) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_original_scene_selection_not_expanded_by_new_member (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_original_scene_selection_not_expanded_by_new_member) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_parameter_digest_uses_existing_android_canonical_identity (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_parameter_digest_uses_existing_android_canonical_identity) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_publish_notice_is_not_install_permission_and_cold_bind_recovers (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_publish_notice_is_not_install_permission_and_cold_bind_recovers) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_registry_failure_keeps_events_and_projection_then_restart_repairs (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_registry_failure_keeps_events_and_projection_then_restart_repairs) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_retired_source_cannot_be_revived_by_newer_inventory_revision (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_retired_source_cannot_be_revived_by_newer_inventory_revision) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_running_target_preserved_and_successors_coalesce_to_current_approval (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_running_target_preserved_and_successors_coalesce_to_current_approval) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_two_entries_cannot_alias_one_retained_source (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_two_entries_cannot_alias_one_retained_source) ... skipped 'requires isolated PostgreSQL' 

清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m111-updates-akzl6gd3 -->

<!-- run:m111-updates-anixhc62 -->
## 运行 m111-updates-anixhc62

- 时间：2026-10-25T12:41:25.652038+00:00 → 2026-10-25T12:42:17.093475+00:00
- 原结果：True；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：True
- 资源：端口关闭=True；剩余测试schema=[]

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_model_updates.py | 0 | 36 | 0/0/0 | OK |
| test_model_update_migration.py | 0 | 4 | 0/0/0 | OK |
| test_model_update_api.py | 0 | 38 | 0/0/0 | OK |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。


清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m111-updates-anixhc62 -->

<!-- run:m111-updates-c7vnopjz -->
## 运行 m111-updates-c7vnopjz

- 时间：2026-11-05T09:29:48.825593+00:00 → 2026-11-05T09:30:01.380926+00:00
- 原结果：True；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：True
- 资源：端口关闭=True；剩余测试schema=[]

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_system_alert_knowledge_postgresql.py | 0 | 1 | 0/0/0 | OK |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。


清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m111-updates-c7vnopjz -->

<!-- run:m111-updates-ewzd816c -->
## 运行 m111-updates-ewzd816c

- 时间：2026-10-25T14:15:00.356785+00:00 → 2026-10-25T14:17:32.795335+00:00
- 原结果：False；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：True
- 资源：端口关闭=True；剩余测试schema=[]

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_model_updates.py | 0 | 38 | 0/0/0 | OK |
| test_model_update_concurrency.py | 0 | 3 | 0/0/0 | OK |
| test_model_update_projection.py | 1 | 22 | 0/2/0 | FAILED (errors=2) |
| test_model_update_auth.py | 0 | 4 | 0/0/0 | OK |
| test_model_update_delivery.py | 0 | 8 | 0/0/0 | OK |
| test_model_update_api.py | 0 | 7 | 0/0/0 | OK |
| test_model_update_migration.py | 0 | 4 | 0/0/0 | OK |
| test_database.py | 0 | 6 | 0/0/0 | OK |
| test_model_download.py | 0 | 7 | 0/0/0 | OK |
| test_resource_lifecycle.py | 0 | 29 | 0/0/1 | OK (skipped=1) |
| test_assignment_targets.py | 0 | 14 | 0/0/0 | OK |
| test_project_scenes.py | 0 | 18 | 0/0/0 | OK |
| test_metrics_api.py | 1 | 1 | 0/1/0 | FAILED (errors=1) |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。

- test_model_update_projection.py：ERROR: test_running_target_preserved_and_successors_coalesce_to_current_approval (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_running_target_preserved_and_successors_coalesce_to_current_approval) 
- test_model_update_projection.py：ERROR: test_running_target_preserved_and_successors_coalesce_to_current_approval (test_model_update_projection.UpdateProjectionTests.test_running_target_preserved_and_successors_coalesce_to_current_approval) 
- test_model_update_projection.py：app.model_updates.protocol.UpdateError: invalid_request 
- test_model_update_projection.py：app.model_updates.protocol.UpdateError: invalid_request 
- test_model_update_projection.py：FAILED (errors=2) 
- test_resource_lifecycle.py：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'PostgreSQL variant only' 
- test_metrics_api.py：ERROR: test_metrics_endpoint_returns_system_and_streams (test_metrics_api.MetricsApiTests.test_metrics_endpoint_returns_system_and_streams) 
- test_metrics_api.py：sqlalchemy.exc.ProgrammingError: (psycopg.errors.UndefinedTable) relation "model_update_devices" does not exist 
- test_metrics_api.py：FAILED (errors=1) 

清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m111-updates-ewzd816c -->

<!-- run:m111-updates-fgw0imvd -->
## 运行 m111-updates-fgw0imvd

- 时间：2026-10-25T13:10:41.420331+00:00 → 2026-10-25T13:11:48.019571+00:00
- 原结果：True；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：True
- 资源：端口关闭=True；剩余测试schema=[]

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_model_update_concurrency.py | 0 | 3 | 0/0/0 | OK |
| test_model_updates.py | 0 | 38 | 0/0/0 | OK |
| test_model_update_api.py | 0 | 7 | 0/0/0 | OK |
| test_model_update_projection.py | 0 | 14 | 0/0/0 | OK |
| test_model_update_migration.py | 0 | 4 | 0/0/0 | OK |
| test_database.py | 0 | 6 | 0/0/0 | OK |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。


清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m111-updates-fgw0imvd -->

<!-- run:m111-updates-hz7umfqy -->
## 运行 m111-updates-hz7umfqy

- 时间：2026-11-05T09:26:58.633277+00:00 → 2026-11-05T09:27:00.637198+00:00
- 原结果：False；测试遍历完成：未知。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：True
- 资源：端口关闭=True；剩余测试schema=未记录

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。


清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m111-updates-hz7umfqy -->

<!-- run:m111-updates-j5r86gn2 -->
## 运行 m111-updates-j5r86gn2

- 时间：2026-11-05T09:43:56.155099+00:00 → 2026-11-05T09:44:10.108724+00:00
- 原结果：True；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：True
- 资源：端口关闭=True；剩余测试schema=[]

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_system_alert_knowledge_postgresql.py | 0 | 1 | 0/0/0 | OK |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。


清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m111-updates-j5r86gn2 -->

<!-- run:m111-updates-khvnz4ga -->
## 运行 m111-updates-khvnz4ga

- 时间：2026-10-25T15:57:03.195050+00:00 → 2026-10-25T16:00:13.123825+00:00
- 原结果：True；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：True
- 资源：端口关闭=True；剩余测试schema=[]

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_model_updates.py | 0 | 42 | 0/0/0 | OK |
| test_model_update_concurrency.py | 0 | 3 | 0/0/0 | OK |
| test_model_update_auth.py | 0 | 4 | 0/0/0 | OK |
| test_model_update_delivery.py | 0 | 11 | 0/0/0 | OK |
| test_model_update_migration.py | 0 | 4 | 0/0/0 | OK |
| test_model_update_projection.py | 0 | 30 | 0/0/0 | OK |
| test_model_update_api.py | 0 | 8 | 0/0/0 | OK |
| test_model_download.py | 0 | 7 | 0/0/0 | OK |
| test_resource_lifecycle.py | 0 | 29 | 0/0/1 | OK (skipped=1) |
| test_assignment_targets.py | 0 | 14 | 0/0/0 | OK |
| test_project_scenes.py | 0 | 18 | 0/0/0 | OK |
| test_project_scene_installation.py | 0 | 24 | 0/0/0 | OK |
| test_database.py | 0 | 6 | 0/0/0 | OK |
| test_metrics_api.py | 0 | 1 | 0/0/0 | OK |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。

- test_resource_lifecycle.py：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'PostgreSQL variant only' 

清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m111-updates-khvnz4ga -->

<!-- run:m111-updates-mtjkafns -->
## 运行 m111-updates-mtjkafns

- 时间：2026-10-25T15:53:14.919874+00:00 → 2026-10-25T15:56:22.349917+00:00
- 原结果：True；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：True
- 资源：端口关闭=True；剩余测试schema=[]

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_model_updates.py | 0 | 42 | 0/0/0 | OK |
| test_model_update_concurrency.py | 0 | 3 | 0/0/0 | OK |
| test_model_update_auth.py | 0 | 4 | 0/0/0 | OK |
| test_model_update_delivery.py | 0 | 11 | 0/0/0 | OK |
| test_model_update_migration.py | 0 | 4 | 0/0/0 | OK |
| test_model_update_projection.py | 0 | 28 | 0/0/0 | OK |
| test_model_update_api.py | 0 | 8 | 0/0/0 | OK |
| test_model_download.py | 0 | 7 | 0/0/0 | OK |
| test_resource_lifecycle.py | 0 | 29 | 0/0/1 | OK (skipped=1) |
| test_assignment_targets.py | 0 | 14 | 0/0/0 | OK |
| test_project_scenes.py | 0 | 18 | 0/0/0 | OK |
| test_project_scene_installation.py | 0 | 24 | 0/0/0 | OK |
| test_database.py | 0 | 6 | 0/0/0 | OK |
| test_metrics_api.py | 0 | 1 | 0/0/0 | OK |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。

- test_resource_lifecycle.py：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'PostgreSQL variant only' 

清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m111-updates-mtjkafns -->

<!-- run:m111-updates-rdfxv035 -->
## 运行 m111-updates-rdfxv035

- 时间：2026-10-25T13:37:29.949070+00:00 → 2026-10-25T13:37:58.512959+00:00
- 原结果：True；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：False
- 资源：端口关闭=非PG或未知；剩余测试schema=未记录

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_model_update_delivery.py | 0 | 8 | 0/0/0 | OK |
| test_model_update_projection.py | 0 | 20 | 0/0/10 | OK (skipped=10) |
| test_model_update_api.py | 0 | 7 | 0/0/0 | OK |
| test_model_download.py | 0 | 6 | 0/0/0 | OK |
| test_metrics_api.py | 0 | 1 | 0/0/0 | OK |
| test_project_scenes.py | 0 | 18 | 0/0/5 | OK (skipped=5) |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。

- test_model_update_projection.py：test_assignment_approval_generates_exact_target_and_scan_is_idempotent (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_assignment_approval_generates_exact_target_and_scan_is_idempotent) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_assignment_domain_event_rolls_back_with_business_write (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_assignment_domain_event_rolls_back_with_business_write) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_authority_revocation_is_checked_before_periodic_scan (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_authority_revocation_is_checked_before_periodic_scan) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_disabled_account_retires_binding_without_dispatching_old_token (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_disabled_account_retires_binding_without_dispatching_old_token) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_inventory_without_approval_cannot_create_executable_target (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_inventory_without_approval_cannot_create_executable_target) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_original_scene_selection_not_expanded_by_new_member (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_original_scene_selection_not_expanded_by_new_member) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_publish_notice_is_not_install_permission_and_cold_bind_recovers (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_publish_notice_is_not_install_permission_and_cold_bind_recovers) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_registry_failure_keeps_events_and_projection_then_restart_repairs (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_registry_failure_keeps_events_and_projection_then_restart_repairs) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_retired_source_cannot_be_revived_by_newer_inventory_revision (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_retired_source_cannot_be_revived_by_newer_inventory_revision) ... skipped 'requires isolated PostgreSQL' 
- test_model_update_projection.py：test_two_entries_cannot_alias_one_retained_source (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_two_entries_cannot_alias_one_retained_source) ... skipped 'requires isolated PostgreSQL' 
- test_project_scenes.py：test_approval_persists_audit_and_rechecks_membership_inside_transaction (test_project_scenes.ScenePostgreSqlTests.test_approval_persists_audit_and_rechecks_membership_inside_transaction) ... skipped 'requires isolated PostgreSQL schema' 
- test_project_scenes.py：test_audit_failure_rolls_back_scene_and_members_and_inactive_guard (test_project_scenes.ScenePostgreSqlTests.test_audit_failure_rolls_back_scene_and_members_and_inactive_guard) ... skipped 'requires isolated PostgreSQL schema' 
- test_project_scenes.py：test_independent_stores_serialize_first_creation_and_updates (test_project_scenes.ScenePostgreSqlTests.test_independent_stores_serialize_first_creation_and_updates) ... skipped 'requires isolated PostgreSQL schema' 
- test_project_scenes.py：test_new_scene_audit_failure_leaves_no_partial_data (test_project_scenes.ScenePostgreSqlTests.test_new_scene_audit_failure_leaves_no_partial_data) ... skipped 'requires isolated PostgreSQL schema' 
- test_project_scenes.py：test_reopen_order_replace_isolation_and_revision (test_project_scenes.ScenePostgreSqlTests.test_reopen_order_replace_isolation_and_revision) ... skipped 'requires isolated PostgreSQL schema' 

清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m111-updates-rdfxv035 -->

<!-- run:m111-updates-rq2735ut -->
## 运行 m111-updates-rq2735ut

- 时间：2026-10-25T15:41:42.842574+00:00 → 2026-10-25T15:45:07.294041+00:00
- 原结果：False；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：历史结果未记录，不能用当前HEAD补填；工作区：未知
- 环境：历史结果未记录；隔离PostgreSQL：True
- 资源：端口关闭=True；剩余测试schema=[]

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_model_updates.py | 0 | 42 | 0/0/0 | OK |
| test_model_update_concurrency.py | 0 | 3 | 0/0/0 | OK |
| test_model_update_auth.py | 0 | 4 | 0/0/0 | OK |
| test_model_update_delivery.py | 0 | 9 | 0/0/0 | OK |
| test_model_update_migration.py | 0 | 4 | 0/0/0 | OK |
| test_model_update_projection.py | 0 | 24 | 0/0/0 | OK |
| test_model_update_api.py | 0 | 8 | 0/0/0 | OK |
| test_model_download.py | 0 | 7 | 0/0/0 | OK |
| test_resource_lifecycle.py | 0 | 29 | 0/0/1 | OK (skipped=1) |
| test_assignment_targets.py | 0 | 14 | 0/0/0 | OK |
| test_project_scenes.py | 0 | 18 | 0/0/0 | OK |
| test_project_scene_installation.py | 0 | 24 | 0/0/0 | OK |
| test_database.py | 1 | 6 | 1/0/0 | FAILED (failures=1) |
| test_metrics_api.py | 0 | 1 | 0/0/0 | OK |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。

- test_resource_lifecycle.py：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'PostgreSQL variant only' 
- test_database.py：FAIL: test_schema_and_health_use_isolated_in_memory_database (test_database.DatabaseConfigurationTests.test_schema_and_health_use_isolated_in_memory_database) 
- test_database.py：AssertionError: Items in the first set but not the second: 
- test_database.py：FAILED (failures=1) 

清理状态：历史日志已摘要化；回收状态见文末迁移清单，不代表重新执行了测试

<!-- end-run:m111-updates-rq2735ut -->

<!-- historical-log-inventory-20261112 -->
## 2026-11-12 历史原始材料迁移

本节只归档测试事实和文件定位摘要，不包含完整日志。未重跑原业务测试；旧版本、环境缺失项仍未知。缺少result.json的中断轮次只记录可观察日志结束状态，不能据此补记整轮通过。

状态：2026-11-12已逐文件核对内容SHA256、路径边界和占用状态，将本清单141份原始文件（3,034,875字节）送入Windows回收站；回读核验原路径全部不存在。可从回收站恢复，未清空回收站，不声称释放磁盘空间。历史隔离数据库目录、图片、业务数据及其他任务输出不在本次清单内。

### 独立日志核验（包含中断、失败及重复副本）

| 原相对路径 | 执行数 | 结束标记 |
|---|---:|---|
| .tmp/m111-updates-2xf46wxd/test_assignment_targets.py.log | 14 | OK (skipped=3) |
| .tmp/m111-updates-2xf46wxd/test_database.py.log | 6 | FAILED (failures=1) |
| .tmp/m111-updates-2xf46wxd/test_model_download.py.log | 6 | OK |
| .tmp/m111-updates-2xf46wxd/test_project_scenes.py.log | 18 | OK (skipped=5) |
| .tmp/m111-updates-2xf46wxd/test_resource_lifecycle.py.log | 29 | OK (skipped=13) |
| .tmp/m111-updates-813z1f6m/test_metrics_api.py.log | 1 | OK |
| .tmp/m111-updates-813z1f6m/test_model_update_projection.py.log | 22 | OK (skipped=11) |
| .tmp/m111-updates-_76nf_xp/postgres.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-_76nf_xp/runner.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-_76nf_xp/test_system_alert_knowledge_postgresql.py.log | 1 | FAILED (errors=1) |
| .tmp/m111-updates-akzl6gd3/test_metrics_api.py.log | 1 | OK |
| .tmp/m111-updates-akzl6gd3/test_model_update_api.py.log | 7 | OK |
| .tmp/m111-updates-akzl6gd3/test_model_update_delivery.py.log | 9 | OK |
| .tmp/m111-updates-akzl6gd3/test_model_update_projection.py.log | 24 | FAILED (failures=1, skipped=12) |
| .tmp/m111-updates-akzl6gd3/test_model_updates.py.log | 42 | OK (skipped=19) |
| .tmp/m111-updates-akzl6gd3/test_project_scene_installation.py.log | 24 | OK |
| .tmp/m111-updates-anixhc62/postgres.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-anixhc62/runner.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-anixhc62/test_model_update_api.py.log | 38 | OK |
| .tmp/m111-updates-anixhc62/test_model_update_migration.py.log | 4 | OK |
| .tmp/m111-updates-anixhc62/test_model_updates.py.log | 36 | OK |
| .tmp/m111-updates-c7vnopjz/postgres.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-c7vnopjz/runner.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-c7vnopjz/test_system_alert_knowledge_postgresql.py.log | 1 | OK |
| .tmp/m111-updates-ewzd816c/postgres.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-ewzd816c/runner.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-ewzd816c/test_assignment_targets.py.log | 14 | OK |
| .tmp/m111-updates-ewzd816c/test_database.py.log | 6 | OK |
| .tmp/m111-updates-ewzd816c/test_metrics_api.py.log | 1 | FAILED (errors=1) |
| .tmp/m111-updates-ewzd816c/test_model_download.py.log | 7 | OK |
| .tmp/m111-updates-ewzd816c/test_model_update_api.py.log | 7 | OK |
| .tmp/m111-updates-ewzd816c/test_model_update_auth.py.log | 4 | OK |
| .tmp/m111-updates-ewzd816c/test_model_update_concurrency.py.log | 3 | OK |
| .tmp/m111-updates-ewzd816c/test_model_update_delivery.py.log | 8 | OK |
| .tmp/m111-updates-ewzd816c/test_model_update_migration.py.log | 4 | OK |
| .tmp/m111-updates-ewzd816c/test_model_update_projection.py.log | 22 | FAILED (errors=2) |
| .tmp/m111-updates-ewzd816c/test_model_updates.py.log | 38 | OK |
| .tmp/m111-updates-ewzd816c/test_project_scenes.py.log | 18 | OK |
| .tmp/m111-updates-ewzd816c/test_resource_lifecycle.py.log | 29 | OK (skipped=1) |
| .tmp/m111-updates-fgw0imvd/postgres.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-fgw0imvd/runner.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-fgw0imvd/test_database.py.log | 6 | OK |
| .tmp/m111-updates-fgw0imvd/test_model_update_api.py.log | 7 | OK |
| .tmp/m111-updates-fgw0imvd/test_model_update_concurrency.py.log | 3 | OK |
| .tmp/m111-updates-fgw0imvd/test_model_update_migration.py.log | 4 | OK |
| .tmp/m111-updates-fgw0imvd/test_model_update_projection.py.log | 14 | OK |
| .tmp/m111-updates-fgw0imvd/test_model_updates.py.log | 38 | OK |
| .tmp/m111-updates-j5r86gn2/postgres.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-j5r86gn2/runner.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-j5r86gn2/test_system_alert_knowledge_postgresql.py.log | 1 | OK |
| .tmp/m111-updates-khvnz4ga/postgres.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-khvnz4ga/runner.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-khvnz4ga/test_assignment_targets.py.log | 14 | OK |
| .tmp/m111-updates-khvnz4ga/test_database.py.log | 6 | OK |
| .tmp/m111-updates-khvnz4ga/test_metrics_api.py.log | 1 | OK |
| .tmp/m111-updates-khvnz4ga/test_model_download.py.log | 7 | OK |
| .tmp/m111-updates-khvnz4ga/test_model_update_api.py.log | 8 | OK |
| .tmp/m111-updates-khvnz4ga/test_model_update_auth.py.log | 4 | OK |
| .tmp/m111-updates-khvnz4ga/test_model_update_concurrency.py.log | 3 | OK |
| .tmp/m111-updates-khvnz4ga/test_model_update_delivery.py.log | 11 | OK |
| .tmp/m111-updates-khvnz4ga/test_model_update_migration.py.log | 4 | OK |
| .tmp/m111-updates-khvnz4ga/test_model_update_projection.py.log | 30 | OK |
| .tmp/m111-updates-khvnz4ga/test_model_updates.py.log | 42 | OK |
| .tmp/m111-updates-khvnz4ga/test_project_scene_installation.py.log | 24 | OK |
| .tmp/m111-updates-khvnz4ga/test_project_scenes.py.log | 18 | OK |
| .tmp/m111-updates-khvnz4ga/test_resource_lifecycle.py.log | 29 | OK (skipped=1) |
| .tmp/m111-updates-mtjkafns/postgres.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-mtjkafns/runner.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-mtjkafns/test_assignment_targets.py.log | 14 | OK |
| .tmp/m111-updates-mtjkafns/test_database.py.log | 6 | OK |
| .tmp/m111-updates-mtjkafns/test_metrics_api.py.log | 1 | OK |
| .tmp/m111-updates-mtjkafns/test_model_download.py.log | 7 | OK |
| .tmp/m111-updates-mtjkafns/test_model_update_api.py.log | 8 | OK |
| .tmp/m111-updates-mtjkafns/test_model_update_auth.py.log | 4 | OK |
| .tmp/m111-updates-mtjkafns/test_model_update_concurrency.py.log | 3 | OK |
| .tmp/m111-updates-mtjkafns/test_model_update_delivery.py.log | 11 | OK |
| .tmp/m111-updates-mtjkafns/test_model_update_migration.py.log | 4 | OK |
| .tmp/m111-updates-mtjkafns/test_model_update_projection.py.log | 28 | OK |
| .tmp/m111-updates-mtjkafns/test_model_updates.py.log | 42 | OK |
| .tmp/m111-updates-mtjkafns/test_project_scene_installation.py.log | 24 | OK |
| .tmp/m111-updates-mtjkafns/test_project_scenes.py.log | 18 | OK |
| .tmp/m111-updates-mtjkafns/test_resource_lifecycle.py.log | 29 | OK (skipped=1) |
| .tmp/m111-updates-rdfxv035/test_metrics_api.py.log | 1 | OK |
| .tmp/m111-updates-rdfxv035/test_model_download.py.log | 6 | OK |
| .tmp/m111-updates-rdfxv035/test_model_update_api.py.log | 7 | OK |
| .tmp/m111-updates-rdfxv035/test_model_update_delivery.py.log | 8 | OK |
| .tmp/m111-updates-rdfxv035/test_model_update_projection.py.log | 20 | OK (skipped=10) |
| .tmp/m111-updates-rdfxv035/test_project_scenes.py.log | 18 | OK (skipped=5) |
| .tmp/m111-updates-rq2735ut/postgres.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-rq2735ut/runner.log | 未知 | 未提取到unittest结束标记 |
| .tmp/m111-updates-rq2735ut/test_assignment_targets.py.log | 14 | OK |
| .tmp/m111-updates-rq2735ut/test_database.py.log | 6 | FAILED (failures=1) |
| .tmp/m111-updates-rq2735ut/test_metrics_api.py.log | 1 | OK |
| .tmp/m111-updates-rq2735ut/test_model_download.py.log | 7 | OK |
| .tmp/m111-updates-rq2735ut/test_model_update_api.py.log | 8 | OK |
| .tmp/m111-updates-rq2735ut/test_model_update_auth.py.log | 4 | OK |
| .tmp/m111-updates-rq2735ut/test_model_update_concurrency.py.log | 3 | OK |
| .tmp/m111-updates-rq2735ut/test_model_update_delivery.py.log | 9 | OK |
| .tmp/m111-updates-rq2735ut/test_model_update_migration.py.log | 4 | OK |
| .tmp/m111-updates-rq2735ut/test_model_update_projection.py.log | 24 | OK |
| .tmp/m111-updates-rq2735ut/test_model_updates.py.log | 42 | OK |
| .tmp/m111-updates-rq2735ut/test_project_scene_installation.py.log | 24 | OK |
| .tmp/m111-updates-rq2735ut/test_project_scenes.py.log | 18 | OK |
| .tmp/m111-updates-rq2735ut/test_resource_lifecycle.py.log | 29 | OK (skipped=1) |
| harness/evidence/M111/T02/runs/m111-updates-_76nf_xp/test_system_alert_knowledge_postgresql.py.log | 1 | FAILED (errors=1) |
| harness/evidence/M111/T02/runs/m111-updates-c7vnopjz/test_system_alert_knowledge_postgresql.py.log | 1 | OK |
| harness/evidence/M111/T02/runs/m111-updates-j5r86gn2/test_system_alert_knowledge_postgresql.py.log | 1 | OK |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_assignment_targets.py.log | 14 | OK |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_database.py.log | 6 | OK |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_metrics_api.py.log | 1 | OK |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_model_download.py.log | 7 | OK |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_model_update_api.py.log | 8 | OK |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_model_update_auth.py.log | 4 | OK |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_model_update_concurrency.py.log | 3 | OK |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_model_update_delivery.py.log | 11 | OK |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_model_update_migration.py.log | 4 | OK |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_model_update_projection.py.log | 30 | OK |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_model_updates.py.log | 42 | OK |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_project_scene_installation.py.log | 24 | OK |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_project_scenes.py.log | 18 | OK |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_resource_lifecycle.py.log | 29 | OK (skipped=1) |

### 失败/跳过/初始化异常摘要

- `.tmp/m111-updates-2xf46wxd/test_assignment_targets.py.log`：test_atomic_failure_leaves_no_rows_or_audits (test_assignment_targets.AssignmentTargetsPostgresTests.test_atomic_failure_leaves_no_rows_or_audits) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_assignment_targets.py.log`：test_independent_writers_with_no_shared_process_locks_serialize_batch (test_assignment_targets.AssignmentTargetsPostgresTests.test_independent_writers_with_no_shared_process_locks_serialize_batch) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_assignment_targets.py.log`：test_reopen_independent_parameters_and_disable (test_assignment_targets.AssignmentTargetsPostgresTests.test_reopen_independent_parameters_and_disable) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_database.py.log`：FAIL: test_schema_and_health_use_isolated_in_memory_database (test_database.DatabaseConfigurationTests.test_schema_and_health_use_isolated_in_memory_database) 
- `.tmp/m111-updates-2xf46wxd/test_database.py.log`：AssertionError: Items in the first set but not the second: 
- `.tmp/m111-updates-2xf46wxd/test_database.py.log`：FAILED (failures=1) 
- `.tmp/m111-updates-2xf46wxd/test_project_scenes.py.log`：test_approval_persists_audit_and_rechecks_membership_inside_transaction (test_project_scenes.ScenePostgreSqlTests.test_approval_persists_audit_and_rechecks_membership_inside_transaction) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_project_scenes.py.log`：test_audit_failure_rolls_back_scene_and_members_and_inactive_guard (test_project_scenes.ScenePostgreSqlTests.test_audit_failure_rolls_back_scene_and_members_and_inactive_guard) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_project_scenes.py.log`：test_independent_stores_serialize_first_creation_and_updates (test_project_scenes.ScenePostgreSqlTests.test_independent_stores_serialize_first_creation_and_updates) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_project_scenes.py.log`：test_new_scene_audit_failure_leaves_no_partial_data (test_project_scenes.ScenePostgreSqlTests.test_new_scene_audit_failure_leaves_no_partial_data) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_project_scenes.py.log`：test_reopen_order_replace_isolation_and_revision (test_project_scenes.ScenePostgreSqlTests.test_reopen_order_replace_isolation_and_revision) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_resource_lifecycle.py.log`：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'requires PostgreSQL row locks' 
- `.tmp/m111-updates-2xf46wxd/test_resource_lifecycle.py.log`：test_cleanup_failure_recovers_without_cascade_or_duplicate_facts (test_resource_lifecycle.LifecyclePostgreSqlTests.test_cleanup_failure_recovers_without_cascade_or_duplicate_facts) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_resource_lifecycle.py.log`：test_confirmed_database_and_failed_final_registry_ack_recovers (test_resource_lifecycle.LifecyclePostgreSqlTests.test_confirmed_database_and_failed_final_registry_ack_recovers) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_resource_lifecycle.py.log`：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePostgreSqlTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_resource_lifecycle.py.log`：test_model_prepared_intent_blocks_new_scene_and_assignment_then_recovers (test_resource_lifecycle.LifecyclePostgreSqlTests.test_model_prepared_intent_blocks_new_scene_and_assignment_then_recovers) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_resource_lifecycle.py.log`：test_model_registry_commit_and_failed_audit_recovers_without_duplicate_tombstone (test_resource_lifecycle.LifecyclePostgreSqlTests.test_model_registry_commit_and_failed_audit_recovers_without_duplicate_tombstone) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_resource_lifecycle.py.log`：test_pending_intent_blocks_direct_runtime_download_and_registry_mutation (test_resource_lifecycle.LifecyclePostgreSqlTests.test_pending_intent_blocks_direct_runtime_download_and_registry_mutation) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_resource_lifecycle.py.log`：test_prepared_and_confirmed_revocation_block_late_stream_bind (test_resource_lifecycle.LifecyclePostgreSqlTests.test_prepared_and_confirmed_revocation_block_late_stream_bind) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_resource_lifecycle.py.log`：test_recovery_reads_stage_after_waiting_for_catalog_lock (test_resource_lifecycle.LifecyclePostgreSqlTests.test_recovery_reads_stage_after_waiting_for_catalog_lock) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_resource_lifecycle.py.log`：test_replay_rechecks_current_authority (test_resource_lifecycle.LifecyclePostgreSqlTests.test_replay_rechecks_current_authority) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_resource_lifecycle.py.log`：test_scene_tombstone_audit_outbox_members_and_replay_survive_restart (test_resource_lifecycle.LifecyclePostgreSqlTests.test_scene_tombstone_audit_outbox_members_and_replay_survive_restart) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_resource_lifecycle.py.log`：test_scene_transaction_rolls_back_on_outbox_failure (test_resource_lifecycle.LifecyclePostgreSqlTests.test_scene_transaction_rolls_back_on_outbox_failure) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-2xf46wxd/test_resource_lifecycle.py.log`：test_status_crash_after_registry_commit_replays_once (test_resource_lifecycle.LifecyclePostgreSqlTests.test_status_crash_after_registry_commit_replays_once) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-813z1f6m/test_model_update_projection.py.log`：test_assignment_approval_generates_exact_target_and_scan_is_idempotent (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_assignment_approval_generates_exact_target_and_scan_is_idempotent) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-813z1f6m/test_model_update_projection.py.log`：test_assignment_domain_event_rolls_back_with_business_write (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_assignment_domain_event_rolls_back_with_business_write) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-813z1f6m/test_model_update_projection.py.log`：test_authority_revocation_is_checked_before_periodic_scan (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_authority_revocation_is_checked_before_periodic_scan) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-813z1f6m/test_model_update_projection.py.log`：test_disabled_account_retires_binding_without_dispatching_old_token (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_disabled_account_retires_binding_without_dispatching_old_token) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-813z1f6m/test_model_update_projection.py.log`：test_inventory_without_approval_cannot_create_executable_target (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_inventory_without_approval_cannot_create_executable_target) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-813z1f6m/test_model_update_projection.py.log`：test_original_scene_selection_not_expanded_by_new_member (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_original_scene_selection_not_expanded_by_new_member) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-813z1f6m/test_model_update_projection.py.log`：test_publish_notice_is_not_install_permission_and_cold_bind_recovers (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_publish_notice_is_not_install_permission_and_cold_bind_recovers) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-813z1f6m/test_model_update_projection.py.log`：test_registry_failure_keeps_events_and_projection_then_restart_repairs (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_registry_failure_keeps_events_and_projection_then_restart_repairs) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-813z1f6m/test_model_update_projection.py.log`：test_retired_source_cannot_be_revived_by_newer_inventory_revision (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_retired_source_cannot_be_revived_by_newer_inventory_revision) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-813z1f6m/test_model_update_projection.py.log`：test_running_target_preserved_and_successors_coalesce_to_current_approval (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_running_target_preserved_and_successors_coalesce_to_current_approval) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-813z1f6m/test_model_update_projection.py.log`：test_two_entries_cannot_alias_one_retained_source (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_two_entries_cannot_alias_one_retained_source) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-_76nf_xp/test_system_alert_knowledge_postgresql.py.log`：ERROR: test_migrated_project_inheritance_publication_and_masking (test_system_alert_knowledge_postgresql.SystemAlertKnowledgePostgreSQLTests.test_migrated_project_inheritance_publication_and_masking) 
- `.tmp/m111-updates-_76nf_xp/test_system_alert_knowledge_postgresql.py.log`：FAILED (errors=1) 
- `.tmp/m111-updates-akzl6gd3/test_model_update_projection.py.log`：FAIL: test_running_target_preserved_and_successors_coalesce_to_current_approval (test_model_update_projection.UpdateProjectionTests.test_running_target_preserved_and_successors_coalesce_to_current_approval) 
- `.tmp/m111-updates-akzl6gd3/test_model_update_projection.py.log`：AssertionError: 'accepted' != 'stale' 
- `.tmp/m111-updates-akzl6gd3/test_model_update_projection.py.log`：FAILED (failures=1, skipped=12) 
- `.tmp/m111-updates-akzl6gd3/test_model_update_projection.py.log`：test_assignment_approval_generates_exact_target_and_scan_is_idempotent (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_assignment_approval_generates_exact_target_and_scan_is_idempotent) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_update_projection.py.log`：test_assignment_domain_event_rolls_back_with_business_write (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_assignment_domain_event_rolls_back_with_business_write) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_update_projection.py.log`：test_authority_revocation_is_checked_before_periodic_scan (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_authority_revocation_is_checked_before_periodic_scan) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_update_projection.py.log`：test_disabled_account_retires_binding_without_dispatching_old_token (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_disabled_account_retires_binding_without_dispatching_old_token) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_update_projection.py.log`：test_inventory_without_approval_cannot_create_executable_target (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_inventory_without_approval_cannot_create_executable_target) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_update_projection.py.log`：test_original_scene_selection_not_expanded_by_new_member (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_original_scene_selection_not_expanded_by_new_member) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_update_projection.py.log`：test_parameter_digest_uses_existing_android_canonical_identity (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_parameter_digest_uses_existing_android_canonical_identity) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_update_projection.py.log`：test_publish_notice_is_not_install_permission_and_cold_bind_recovers (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_publish_notice_is_not_install_permission_and_cold_bind_recovers) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_update_projection.py.log`：test_registry_failure_keeps_events_and_projection_then_restart_repairs (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_registry_failure_keeps_events_and_projection_then_restart_repairs) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_update_projection.py.log`：test_retired_source_cannot_be_revived_by_newer_inventory_revision (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_retired_source_cannot_be_revived_by_newer_inventory_revision) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_update_projection.py.log`：test_running_target_preserved_and_successors_coalesce_to_current_approval (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_running_target_preserved_and_successors_coalesce_to_current_approval) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_update_projection.py.log`：test_two_entries_cannot_alias_one_retained_source (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_two_entries_cannot_alias_one_retained_source) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_binding_idempotent_epoch_retirement_and_old_account_isolation (test_model_updates.UpdatePostgreSqlTests.test_binding_idempotent_epoch_retirement_and_old_account_isolation) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_cleanup_compacts_only_old_terminal_history_and_rebuilds_current_truth (test_model_updates.UpdatePostgreSqlTests.test_cleanup_compacts_only_old_terminal_history_and_rebuilds_current_truth) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_current_permission_revocation_hides_snapshot_and_delta (test_model_updates.UpdatePostgreSqlTests.test_current_permission_revocation_hides_snapshot_and_delta) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_expired_and_cross_device_tickets_fail_closed (test_model_updates.UpdatePostgreSqlTests.test_expired_and_cross_device_tickets_fail_closed) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_failed_projection_transaction_does_not_advance_sequence (test_model_updates.UpdatePostgreSqlTests.test_failed_projection_transaction_does_not_advance_sequence) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_install_quarantine_rollback_are_distinct_persisted_facts (test_model_updates.UpdatePostgreSqlTests.test_install_quarantine_rollback_are_distinct_persisted_facts) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_invalid_criteria_and_digest_cannot_be_success (test_model_updates.UpdatePostgreSqlTests.test_invalid_criteria_and_digest_cannot_be_success) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_inventory_atomic_revision_and_capacity (test_model_updates.UpdatePostgreSqlTests.test_inventory_atomic_revision_and_capacity) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_metrics_survive_service_restart_and_measure_document_bytes (test_model_updates.UpdatePostgreSqlTests.test_metrics_survive_service_restart_and_measure_document_bytes) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_missing_fcm_configuration_preserves_dirty_and_marks_disabled (test_model_updates.UpdatePostgreSqlTests.test_missing_fcm_configuration_preserves_dirty_and_marks_disabled) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_no_database_has_no_memory_success (test_model_updates.UpdatePostgreSqlTests.test_no_database_has_no_memory_success) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_offline_batch_receipts_and_unchanged_progress_do_not_push_again (test_model_updates.UpdatePostgreSqlTests.test_offline_batch_receipts_and_unchanged_progress_do_not_push_again) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_pending_retention_survives_ninety_days_and_cleanup_expires_old_cursor (test_model_updates.UpdatePostgreSqlTests.test_pending_retention_survives_ninety_days_and_cleanup_expires_old_cursor) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_push_lease_does_not_clear_new_dirty_and_token_is_retired (test_model_updates.UpdatePostgreSqlTests.test_push_lease_does_not_clear_new_dirty_and_token_is_retired) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_rate_limits_shared_between_store_instances (test_model_updates.UpdatePostgreSqlTests.test_rate_limits_shared_between_store_instances) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_receipts_immutable_duplicate_stale_and_permanent_audit (test_model_updates.UpdatePostgreSqlTests.test_receipts_immutable_duplicate_stale_and_permanent_audit) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_snapshot_fixed_watermark_pages_then_incremental (test_model_updates.UpdatePostgreSqlTests.test_snapshot_fixed_watermark_pages_then_incremental) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_token_generation_rotation_and_equal_generation_conflict (test_model_updates.UpdatePostgreSqlTests.test_token_generation_rotation_and_equal_generation_conflict) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-akzl6gd3/test_model_updates.py.log`：test_unbind_idempotence_and_no_cross_account (test_model_updates.UpdatePostgreSqlTests.test_unbind_idempotence_and_no_cross_account) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-ewzd816c/test_metrics_api.py.log`：ERROR: test_metrics_endpoint_returns_system_and_streams (test_metrics_api.MetricsApiTests.test_metrics_endpoint_returns_system_and_streams) 
- `.tmp/m111-updates-ewzd816c/test_metrics_api.py.log`：sqlalchemy.exc.ProgrammingError: (psycopg.errors.UndefinedTable) relation "model_update_devices" does not exist 
- `.tmp/m111-updates-ewzd816c/test_metrics_api.py.log`：FAILED (errors=1) 
- `.tmp/m111-updates-ewzd816c/test_model_update_projection.py.log`：ERROR: test_running_target_preserved_and_successors_coalesce_to_current_approval (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_running_target_preserved_and_successors_coalesce_to_current_approval) 
- `.tmp/m111-updates-ewzd816c/test_model_update_projection.py.log`：ERROR: test_running_target_preserved_and_successors_coalesce_to_current_approval (test_model_update_projection.UpdateProjectionTests.test_running_target_preserved_and_successors_coalesce_to_current_approval) 
- `.tmp/m111-updates-ewzd816c/test_model_update_projection.py.log`：app.model_updates.protocol.UpdateError: invalid_request 
- `.tmp/m111-updates-ewzd816c/test_model_update_projection.py.log`：app.model_updates.protocol.UpdateError: invalid_request 
- `.tmp/m111-updates-ewzd816c/test_model_update_projection.py.log`：FAILED (errors=2) 
- `.tmp/m111-updates-ewzd816c/test_resource_lifecycle.py.log`：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'PostgreSQL variant only' 
- `.tmp/m111-updates-khvnz4ga/test_resource_lifecycle.py.log`：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'PostgreSQL variant only' 
- `.tmp/m111-updates-mtjkafns/test_resource_lifecycle.py.log`：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'PostgreSQL variant only' 
- `.tmp/m111-updates-rdfxv035/test_model_update_projection.py.log`：test_assignment_approval_generates_exact_target_and_scan_is_idempotent (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_assignment_approval_generates_exact_target_and_scan_is_idempotent) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-rdfxv035/test_model_update_projection.py.log`：test_assignment_domain_event_rolls_back_with_business_write (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_assignment_domain_event_rolls_back_with_business_write) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-rdfxv035/test_model_update_projection.py.log`：test_authority_revocation_is_checked_before_periodic_scan (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_authority_revocation_is_checked_before_periodic_scan) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-rdfxv035/test_model_update_projection.py.log`：test_disabled_account_retires_binding_without_dispatching_old_token (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_disabled_account_retires_binding_without_dispatching_old_token) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-rdfxv035/test_model_update_projection.py.log`：test_inventory_without_approval_cannot_create_executable_target (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_inventory_without_approval_cannot_create_executable_target) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-rdfxv035/test_model_update_projection.py.log`：test_original_scene_selection_not_expanded_by_new_member (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_original_scene_selection_not_expanded_by_new_member) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-rdfxv035/test_model_update_projection.py.log`：test_publish_notice_is_not_install_permission_and_cold_bind_recovers (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_publish_notice_is_not_install_permission_and_cold_bind_recovers) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-rdfxv035/test_model_update_projection.py.log`：test_registry_failure_keeps_events_and_projection_then_restart_repairs (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_registry_failure_keeps_events_and_projection_then_restart_repairs) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-rdfxv035/test_model_update_projection.py.log`：test_retired_source_cannot_be_revived_by_newer_inventory_revision (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_retired_source_cannot_be_revived_by_newer_inventory_revision) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-rdfxv035/test_model_update_projection.py.log`：test_two_entries_cannot_alias_one_retained_source (test_model_update_projection.UpdateProjectionPostgreSqlTests.test_two_entries_cannot_alias_one_retained_source) ... skipped 'requires isolated PostgreSQL' 
- `.tmp/m111-updates-rdfxv035/test_project_scenes.py.log`：test_approval_persists_audit_and_rechecks_membership_inside_transaction (test_project_scenes.ScenePostgreSqlTests.test_approval_persists_audit_and_rechecks_membership_inside_transaction) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-rdfxv035/test_project_scenes.py.log`：test_audit_failure_rolls_back_scene_and_members_and_inactive_guard (test_project_scenes.ScenePostgreSqlTests.test_audit_failure_rolls_back_scene_and_members_and_inactive_guard) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-rdfxv035/test_project_scenes.py.log`：test_independent_stores_serialize_first_creation_and_updates (test_project_scenes.ScenePostgreSqlTests.test_independent_stores_serialize_first_creation_and_updates) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-rdfxv035/test_project_scenes.py.log`：test_new_scene_audit_failure_leaves_no_partial_data (test_project_scenes.ScenePostgreSqlTests.test_new_scene_audit_failure_leaves_no_partial_data) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-rdfxv035/test_project_scenes.py.log`：test_reopen_order_replace_isolation_and_revision (test_project_scenes.ScenePostgreSqlTests.test_reopen_order_replace_isolation_and_revision) ... skipped 'requires isolated PostgreSQL schema' 
- `.tmp/m111-updates-rq2735ut/test_database.py.log`：FAIL: test_schema_and_health_use_isolated_in_memory_database (test_database.DatabaseConfigurationTests.test_schema_and_health_use_isolated_in_memory_database) 
- `.tmp/m111-updates-rq2735ut/test_database.py.log`：AssertionError: Items in the first set but not the second: 
- `.tmp/m111-updates-rq2735ut/test_database.py.log`：FAILED (failures=1) 
- `.tmp/m111-updates-rq2735ut/test_resource_lifecycle.py.log`：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'PostgreSQL variant only' 
- `harness/evidence/M111/T02/runs/m111-updates-_76nf_xp/test_system_alert_knowledge_postgresql.py.log`：ERROR: test_migrated_project_inheritance_publication_and_masking (test_system_alert_knowledge_postgresql.SystemAlertKnowledgePostgreSQLTests.test_migrated_project_inheritance_publication_and_masking) 
- `harness/evidence/M111/T02/runs/m111-updates-_76nf_xp/test_system_alert_knowledge_postgresql.py.log`：FAILED (errors=1) 
- `harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_resource_lifecycle.py.log`：test_independent_writer_race_never_leaves_deleted_release_dependency (test_resource_lifecycle.LifecyclePersistenceTests.test_independent_writer_race_never_leaves_deleted_release_dependency) ... skipped 'PostgreSQL variant only' 

### 回收精确清单

SHA256为原文件内容摘要，仅用于迁移前一致性校验，不等价于保留日志。原路径作为历史标识，不是仍存在的附件链接。

| 原相对路径 | 字节数 | SHA256 |
|---|---:|---|
| .tmp/m111-updates-2xf46wxd/result.json | 1225 | 719c78a34ec5f697d0e40f54a54128866bc037f2672b078b7d5f6ea44a3aaa5b |
| .tmp/m111-updates-2xf46wxd/test_assignment_targets.py.log | 40551 | 8a58b4f1e2cd215cea9aa46fcbd839cc5ba689687b1a78bf23b912429f4f96e0 |
| .tmp/m111-updates-2xf46wxd/test_database.py.log | 2590 | 14aecba3004205ac79d32c0dd343c94ef0ccbe4c094ff6f2ed747933d1219d67 |
| .tmp/m111-updates-2xf46wxd/test_model_download.py.log | 20592 | 09e305f74aaf89efde365b502984e8fcec927505f326aa13643ef7f47a29e13f |
| .tmp/m111-updates-2xf46wxd/test_project_scenes.py.log | 45305 | 85d9e2423b4b4e4fa90310c78235e0b2c2e197ea8a80a67e96337e40e7f18328 |
| .tmp/m111-updates-2xf46wxd/test_resource_lifecycle.py.log | 34997 | a3fa070e35186285825a534fc94962a37012d610d3a64eac10e8be38a29aec85 |
| .tmp/m111-updates-813z1f6m/result.json | 671 | f2f8a76053c462c1f3cc0196a236bf9409cecf7a31fb533ad7a34d8e06343f4d |
| .tmp/m111-updates-813z1f6m/test_metrics_api.py.log | 1019 | 65af5aeab448276a10540464f74fc73b4235818b89452742d30872f3a2161b40 |
| .tmp/m111-updates-813z1f6m/test_model_update_projection.py.log | 5059 | 86fe49e6db7fec06e4c646667b6537b2e39ed29871f52d20d58638c9968c9a06 |
| .tmp/m111-updates-_76nf_xp/postgres.log | 1189 | 2684300ce813ac2d945abf3e08999ede3fe0c2f706eea124cca1f8d807de6ef6 |
| .tmp/m111-updates-_76nf_xp/result.json | 925 | 3788626bda5b5744a07287417ee6ecf43edd66b92bd18a4180d5bd8112747d94 |
| .tmp/m111-updates-_76nf_xp/runner.log | 1015 | baa99dba7fc14589e75d7168062dd0712331bd7305ae2abfd34bbea325da2168 |
| .tmp/m111-updates-_76nf_xp/test_system_alert_knowledge_postgresql.py.log | 6175 | e60b939809f10f45f0977215a17e24cead337cb62b8e6c6a2387f2428178a284 |
| .tmp/m111-updates-akzl6gd3/result.json | 1460 | 463fe20a70f7efad15993efcb3f3152a194c12d6419a3be084a549cc10b0a590 |
| .tmp/m111-updates-akzl6gd3/test_metrics_api.py.log | 1018 | 21879154bbf74c95ae3f633993a31e5631bf7869f7c40e4641f34136c0cfcd7c |
| .tmp/m111-updates-akzl6gd3/test_model_update_api.py.log | 1526 | 912652ff3f4b8ae2d82b9505d5fd5fbb7e369dbae4d7c46e21edc0068c8710ca |
| .tmp/m111-updates-akzl6gd3/test_model_update_delivery.py.log | 1939 | 0022c29ba1ab0bbca1e4c9a9aca535edecbc2b693ebecaf429007afff11ed732 |
| .tmp/m111-updates-akzl6gd3/test_model_update_projection.py.log | 6371 | 1c4ab27db77322186c33d48235981273c77b0545eca0a44f2d5c202d87b919c7 |
| .tmp/m111-updates-akzl6gd3/test_model_updates.py.log | 7936 | 73112b7aa18fe9092445f6484b26574c39cba2b9d33f052e2b573451e0711073 |
| .tmp/m111-updates-akzl6gd3/test_project_scene_installation.py.log | 118895 | b8babaa371d93ae242eb404026da7d491693a32c2fc9e9a18a976edf5e7d7c30 |
| .tmp/m111-updates-anixhc62/postgres.log | 1197 | a3a4a64537cb36857daf80de4fd08885b743f5050f14f85fe13cc6cfd9e0a885 |
| .tmp/m111-updates-anixhc62/result.json | 1053 | 5f0307fa35d7afe7347a97ff3a1dd6e976e3afdc3a5eea7afd3fb76fb481d28f |
| .tmp/m111-updates-anixhc62/runner.log | 1013 | d7674bbb31f2c7308de8fe2b74518586e769cb75bd1793ccdc627dab44624c82 |
| .tmp/m111-updates-anixhc62/test_model_update_api.py.log | 6469 | cff2527951139061fc0dcdd873ac8421e32d4a4b35123e627044d5a0395f75c2 |
| .tmp/m111-updates-anixhc62/test_model_update_migration.py.log | 16338 | 1850d9f3a61c456f50df923a65e742ef8f852574d7c9141e9d49853f01a61095 |
| .tmp/m111-updates-anixhc62/test_model_updates.py.log | 58101 | d0f334201614a668a024e7dcebd5c5c9036ab7d0002fd59bcd8feee674abc90e |
| .tmp/m111-updates-c7vnopjz/postgres.log | 1192 | ac169a3f26d909b2c5d72887fef977d8e8f708736c48ad4580fb8c26ee76816f |
| .tmp/m111-updates-c7vnopjz/result.json | 924 | 0538bb8122281d5c8bce8b1707411347ebe0f695545748ae8b2079cba559798c |
| .tmp/m111-updates-c7vnopjz/runner.log | 1013 | 8886a0e89af12c5ecc6e0ead95a9a4c98870f24bb8d2e603a4327251a4254131 |
| .tmp/m111-updates-c7vnopjz/test_system_alert_knowledge_postgresql.py.log | 5141 | 6a97887b00ad72e788273b28026a94dd81fa9bfe3e480ba7aecbcd7571497f2a |
| .tmp/m111-updates-ewzd816c/postgres.log | 11638 | 290ecbd04165a7ce9273ad3ad4d62c0ddc95bfff5c80e54db5b103082e201c18 |
| .tmp/m111-updates-ewzd816c/result.json | 2980 | c24ee1b67b934a7a0d4d568b72909cc596d6ecdcb2361903b86561538087ce4f |
| .tmp/m111-updates-ewzd816c/runner.log | 1013 | a4d9ca952c8ef3fdaa0b38074dcaf51149e0a87cef1c67ca917ef9c464319597 |
| .tmp/m111-updates-ewzd816c/test_assignment_targets.py.log | 44009 | f892b7a1fb0b27160eb2c72d1761a1ef2b109996cbc52982660f87101a377587 |
| .tmp/m111-updates-ewzd816c/test_database.py.log | 1575 | d83c3a0cf759b459f2e8c3d503dc99f30fab6b2cfe77069f9cc422b47167ceef |
| .tmp/m111-updates-ewzd816c/test_metrics_api.py.log | 13033 | 1cfed4ffb2b965f9141bc39a47cebd80d2baeb1520dc43c5c53012f58920b36f |
| .tmp/m111-updates-ewzd816c/test_model_download.py.log | 26798 | 4eba4beabacfb3b6cbc7b0bc56e564041bca8060788dbc67b4dfaeb80ae3c4fa |
| .tmp/m111-updates-ewzd816c/test_model_update_api.py.log | 1526 | 7253cd8406ab8eb0b3efccbf2383d4c8921c111b3df67fc624bc81b0e3bd0b18 |
| .tmp/m111-updates-ewzd816c/test_model_update_auth.py.log | 7611 | 154751eef0fc9d4bcde8d88fff3726242c372299b3c22094a8b65b027c19308e |
| .tmp/m111-updates-ewzd816c/test_model_update_concurrency.py.log | 11951 | 60fb3af77c1b49e4254b20e0c1c326aad106e521d2b9050cb031b376478cc026 |
| .tmp/m111-updates-ewzd816c/test_model_update_delivery.py.log | 1700 | 15db3cc4d238284f243219eeadf4725636a8a927623116fb9ee84942a3364814 |
| .tmp/m111-updates-ewzd816c/test_model_update_migration.py.log | 16338 | 5441c5ce8422ee50774031f678f8086fa61770c78a4c0dc77386df0ae008340a |
| .tmp/m111-updates-ewzd816c/test_model_update_projection.py.log | 43363 | 4fdfa80eb2c90f1ef82deab2c1af7990c7a33e984d2411f6d3e61b638b9591c1 |
| .tmp/m111-updates-ewzd816c/test_model_updates.py.log | 61723 | 90a67b758d0c22e31e9ea8386fc5b5876cc9d2eb296fd24a0327fb912f3a1f80 |
| .tmp/m111-updates-ewzd816c/test_project_scenes.py.log | 61644 | 474b7b4a3d1f92f0030c654ee47a54cb0379c4a88ade0b579c32f7423fdd56b6 |
| .tmp/m111-updates-ewzd816c/test_resource_lifecycle.py.log | 73661 | d4f9cd5301e9b230fe5d8eff5f728f841f35dfb246d7ce21415f9f4025a8bdeb |
| .tmp/m111-updates-fgw0imvd/postgres.log | 1194 | ca26f81ee78c05f06e917d9d0b83e433aa5499f020f9162745714d16ebb7c9cb |
| .tmp/m111-updates-fgw0imvd/result.json | 1640 | d19481fd13592deef896860600611d491916f33fd58d56c0d28cd059a38f8668 |
| .tmp/m111-updates-fgw0imvd/runner.log | 1013 | 6574250e0fa7611f81d41b17b24b4e4b3fb004e583c44984546c701eeb27e1d4 |
| .tmp/m111-updates-fgw0imvd/test_database.py.log | 1575 | eee43ee4003d4f4f03c0ecc87df87bee86021a09442898c3113ed591f490cce2 |
| .tmp/m111-updates-fgw0imvd/test_model_update_api.py.log | 1526 | cdb313fafb4731e04d2a21812684c3ba2d732fa114ff55e18594f3577fb261cd |
| .tmp/m111-updates-fgw0imvd/test_model_update_concurrency.py.log | 11951 | d3599bf8d1d75905241def6a0a6d286b2e95a25920c4ec5d709b384acdd6de17 |
| .tmp/m111-updates-fgw0imvd/test_model_update_migration.py.log | 16338 | 3e7b0bf20ea61740546dece5ac866178f9d6abf42ca88292eeb1cb81a5233edf |
| .tmp/m111-updates-fgw0imvd/test_model_update_projection.py.log | 25834 | d19b430eaaf751f30cb79ade9b7cb5fb6ee06df2fb5225c236fe9d1f48670107 |
| .tmp/m111-updates-fgw0imvd/test_model_updates.py.log | 61723 | 61a9f9b124c021ca67faaea9bebe824e813735d36c0980ab403bc66743dbe4f6 |
| .tmp/m111-updates-j5r86gn2/postgres.log | 1192 | 5d0978ea6af6dc45efb58c70606de18c42512aba5db1e3806ccacf316bea7e87 |
| .tmp/m111-updates-j5r86gn2/result.json | 924 | 3fea8671ed0aa7489dd980913f4c150ec804827f88a829c9c28efdcf4db8a1a2 |
| .tmp/m111-updates-j5r86gn2/runner.log | 1013 | 2d12b895db77b6a6d5f935787d26d8f4b62cad24cd7a2680f029e97a87221ca4 |
| .tmp/m111-updates-j5r86gn2/test_system_alert_knowledge_postgresql.py.log | 5141 | a3778587027c081144878047c427ab831dbfca8034eb00d9fc3d081fd50b749a |
| .tmp/m111-updates-khvnz4ga/postgres.log | 18971 | 7b58b7b65173b645d568d3f97c31431b4732114b06d31174b24c4d59da7bf6e0 |
| .tmp/m111-updates-khvnz4ga/result.json | 4888 | ed40173b4f5ef7f5738484e33f2f67e8efe0c96b5c752573c6cc364a9c58b660 |
| .tmp/m111-updates-khvnz4ga/runner.log | 1013 | 653665b5154c957621f18be2d46fdf766675af32ed69f60d4373f33e8aabcd8b |
| .tmp/m111-updates-khvnz4ga/test_assignment_targets.py.log | 44029 | 38195ccf49ee1d164aba36dc040b28c240a7d1044d4897e13c8cfcad2ddd771e |
| .tmp/m111-updates-khvnz4ga/test_database.py.log | 1575 | bebc4cc6735ca0c1b6c00a1f99d6ae333a8365d352f17d22b377df4ba31a3365 |
| .tmp/m111-updates-khvnz4ga/test_metrics_api.py.log | 1019 | 2d56e4f393d939a2a3a88a3d28fb5266e99b5023daa788786998e999cac51990 |
| .tmp/m111-updates-khvnz4ga/test_model_download.py.log | 26811 | bc751a968310d54c14c11a9df209318b9cea50959eab7ad663c92a08ec8421b6 |
| .tmp/m111-updates-khvnz4ga/test_model_update_api.py.log | 1699 | fc09ed182a27af54718ce814f905453f556990ba013f5ad2f6a6369369e5f85f |
| .tmp/m111-updates-khvnz4ga/test_model_update_auth.py.log | 7611 | e36f335a5aa76be07a5eb2632272eb37a38e864b8ac5cc9fa4d8266aa6210af3 |
| .tmp/m111-updates-khvnz4ga/test_model_update_concurrency.py.log | 11951 | d2b9ba1a3d54f92375e0df25ceda8c59e0f261b4d7b5edc81ec2c8034f19930d |
| .tmp/m111-updates-khvnz4ga/test_model_update_delivery.py.log | 2255 | f42de35c905c20b9ad5b040e5d8c6bb6f80a13c663deb2675bbbc0dd6235a402 |
| .tmp/m111-updates-khvnz4ga/test_model_update_migration.py.log | 16338 | 440322a61fe847a90925fe304ab99c0272d6cf894c65bfa9042b406859cadee8 |
| .tmp/m111-updates-khvnz4ga/test_model_update_projection.py.log | 54970 | 80b0fbe5e6aad40a49571e7408e751ec07e62188484f5717f24ac3ac37d12617 |
| .tmp/m111-updates-khvnz4ga/test_model_updates.py.log | 68971 | 0f19b9cb95dd1ca57a71cae9988124be920c830b6bd0dfc6a9b039b35847f28c |
| .tmp/m111-updates-khvnz4ga/test_project_scene_installation.py.log | 119821 | d7486d74c30408601ff2d289de8e5b51e2fc773502211b00921fc87d520c5f86 |
| .tmp/m111-updates-khvnz4ga/test_project_scenes.py.log | 61653 | 470d7d7ad3bb7751803f7e0fe2f0dcab6adb465ba30e565b5a9e229d153eb798 |
| .tmp/m111-updates-khvnz4ga/test_resource_lifecycle.py.log | 73669 | d2daf0ebf7a61f2e5ee5485a4fe192879561bc1c7f7671fefbe5b2cdf7f052d1 |
| .tmp/m111-updates-mtjkafns/postgres.log | 19345 | e35e11a72715a8aa8c20d993080be149ad6a3d11b571d10688628694b77b9f55 |
| .tmp/m111-updates-mtjkafns/result.json | 3190 | be9a26b53a74defdc3b1e6d517844890762f26c1657f4b57c6e57fcdabea4a5f |
| .tmp/m111-updates-mtjkafns/runner.log | 1013 | 2c9d62be020b4603fe3d25dbd5b2e45b8f9df675632ebb7ddb8edb6a11717c7a |
| .tmp/m111-updates-mtjkafns/test_assignment_targets.py.log | 44042 | 1a4463111df5fee372ff97515f251ea5cb9bc47b76441aed54f121a60046560f |
| .tmp/m111-updates-mtjkafns/test_database.py.log | 1575 | b7c9078918582f32ea7b3cd8364eca6293835fda354e2e49388b11d8771be9f3 |
| .tmp/m111-updates-mtjkafns/test_metrics_api.py.log | 1019 | 873546cab60baf8e8ded1f9a51d96fc2feea6daddc6b6917bfdee6b4fb9deba5 |
| .tmp/m111-updates-mtjkafns/test_model_download.py.log | 26795 | f3574dc9c548b2241f92490141cc11ff0ed569545cf977798cd62d942fc415d0 |
| .tmp/m111-updates-mtjkafns/test_model_update_api.py.log | 1699 | 0eec950368956689dd30ef3f4feb3da34bbb01233ae86720d6af74c2f1a9ddfd |
| .tmp/m111-updates-mtjkafns/test_model_update_auth.py.log | 7611 | f92246d6e66eb9e13d523c419b5faa8f37a0784e2a680dc13926cc4b4c6eb444 |
| .tmp/m111-updates-mtjkafns/test_model_update_concurrency.py.log | 11951 | db156710382a920592bda9ea0bbfd71ae5b72dec91b48b3bfa4d0aaa6d89df7f |
| .tmp/m111-updates-mtjkafns/test_model_update_delivery.py.log | 2255 | d772f5805caec378db54f4f290e4c4035d3d3249cd5a60c12338c518bb9f1126 |
| .tmp/m111-updates-mtjkafns/test_model_update_migration.py.log | 16338 | 4c36d2c09ae955f63fbbfd83597b75f3be5c08418660237b55972fbb370abb2c |
| .tmp/m111-updates-mtjkafns/test_model_update_projection.py.log | 51305 | 8192ebc58987c03949aeb23a210404837f41c0b25f5e421045ddb1daa3e284a9 |
| .tmp/m111-updates-mtjkafns/test_model_updates.py.log | 68971 | 7a9d1991bad754759a9a584684ddc4470c348f04c8eca3a63627c4240ac7d146 |
| .tmp/m111-updates-mtjkafns/test_project_scene_installation.py.log | 119838 | 6511a56738e1a0536eed0200f3c7deb14706b3b1e71b2f40b54cdd916f743d4c |
| .tmp/m111-updates-mtjkafns/test_project_scenes.py.log | 61651 | ee5c723e90af353c084a2cfbbe32adc6216767f98a51eeb97bec27e5949847a0 |
| .tmp/m111-updates-mtjkafns/test_resource_lifecycle.py.log | 73659 | c20d89583736e4eb28b2d156fa6a573dc9f8ed7765742232fcf6aea656e568fc |
| .tmp/m111-updates-rdfxv035/result.json | 1437 | 43a21bf4d36f55bb92d6f138e9741ff5cc173bf0012db00dfaccbfa02946e2ee |
| .tmp/m111-updates-rdfxv035/test_metrics_api.py.log | 1020 | c561ecce73881555f994cc845dcccd3b355ac0ac0eb23bbe7ed1a889ddc3d6e0 |
| .tmp/m111-updates-rdfxv035/test_model_download.py.log | 20592 | cba3e09aa7ca659e64fefbea64d31c79f0f26e08f1a199703faf9d17eb52acac |
| .tmp/m111-updates-rdfxv035/test_model_update_api.py.log | 1526 | 26d0f56c38d577e4891f66055c924a4f81cc7005aec77c3fe8ca0433a9d13351 |
| .tmp/m111-updates-rdfxv035/test_model_update_delivery.py.log | 1700 | 7e087339ba9a02b63636e85069ab27bf70cc233a4cc59a8fd3113fbcd4cd2906 |
| .tmp/m111-updates-rdfxv035/test_model_update_projection.py.log | 4595 | d01452b5107c491d4aaeeec5cc56a580f6331b606a4395fd6e5bbbcc75bec8ed |
| .tmp/m111-updates-rdfxv035/test_project_scenes.py.log | 45306 | 0e547fe26d04457bd8d9ec34c5489f8bace17abc1aebe230d2b588cc272ca282 |
| .tmp/m111-updates-rq2735ut/postgres.log | 19351 | 6648808cbe8c07405bec40248fe20da16e3e33701eb10566d01e453990d8a365 |
| .tmp/m111-updates-rq2735ut/result.json | 3191 | 894a96e2497d0189af30d91c2b436987b2eeeb51a3aba447a455791dcc801a71 |
| .tmp/m111-updates-rq2735ut/runner.log | 1013 | 6b1e2480b407d40e6ed7b7f5d55921bfc884167854102335397a9b69ad9829ce |
| .tmp/m111-updates-rq2735ut/test_assignment_targets.py.log | 44026 | 3b354a3a2963146b42e5c5a3d7ebb04cab242eff3e19d31c4dc8d780ecc40b4d |
| .tmp/m111-updates-rq2735ut/test_database.py.log | 2330 | a9f58bb178f222ecd311d927272aec4257fd724468e7bcd47c4c0823ea66fd5d |
| .tmp/m111-updates-rq2735ut/test_metrics_api.py.log | 1019 | 2a70f54e295a5b45feff282ac1e60eb52638e99bfa24992a4b4f55bc8f9edd89 |
| .tmp/m111-updates-rq2735ut/test_model_download.py.log | 26804 | f3e3a0e3374fde51b2064e006edf1c1466dca3c2ecf4a4b23179ad6e0426d5cf |
| .tmp/m111-updates-rq2735ut/test_model_update_api.py.log | 1699 | e2f4048a1c0e77bd1f47cc1478584c35c1d453c13d4a511b1caec11d19b9791f |
| .tmp/m111-updates-rq2735ut/test_model_update_auth.py.log | 7612 | 855a354cd30dc09431c5db4a169d26e0e66c53b77f1a58bf223c35dac7e09834 |
| .tmp/m111-updates-rq2735ut/test_model_update_concurrency.py.log | 11951 | cb0dbd6de4532bcf0241197513d8051d16b7984c61612fff1dad663e2e632b9b |
| .tmp/m111-updates-rq2735ut/test_model_update_delivery.py.log | 1939 | b7c40340448357cf9b855e7232f082a4d435bb4af229c26231b7c8a17cc8e5ba |
| .tmp/m111-updates-rq2735ut/test_model_update_migration.py.log | 16338 | 9878dc75d49c1b5f70019c5dd3bf78e79993571e60d75d4a6b21f43187e32633 |
| .tmp/m111-updates-rq2735ut/test_model_update_projection.py.log | 44023 | eb222bb6b6b23a308080ff77bb724a06622b12a7900220f44ccbeb33ad9fa49d |
| .tmp/m111-updates-rq2735ut/test_model_updates.py.log | 68971 | 60380cbceb122c7cdc787110a26a349e6b2c1c96a0517c8ea5f8abbb242df863 |
| .tmp/m111-updates-rq2735ut/test_project_scene_installation.py.log | 119852 | defa4c8992d3d3727e3bbf15706adced0b30d2b3e8343900293d384948b27d3d |
| .tmp/m111-updates-rq2735ut/test_project_scenes.py.log | 61649 | 9e2ba2d87973d2ee318e789f331dc95b2c00e8cfd43d63f44672a271776f514d |
| .tmp/m111-updates-rq2735ut/test_resource_lifecycle.py.log | 73657 | 5bcedad4f8a27dcee8d1b44751b3a45f9f8110bf34ba6ecf7d27fb0dee77ace0 |
| harness/evidence/M111/T02/backend-result.json | 1460 | 463fe20a70f7efad15993efcb3f3152a194c12d6419a3be084a549cc10b0a590 |
| harness/evidence/M111/T02/postgres-result.json | 924 | 3fea8671ed0aa7489dd980913f4c150ec804827f88a829c9c28efdcf4db8a1a2 |
| harness/evidence/M111/T02/runs/m111-updates-_76nf_xp/result.json | 925 | 3788626bda5b5744a07287417ee6ecf43edd66b92bd18a4180d5bd8112747d94 |
| harness/evidence/M111/T02/runs/m111-updates-_76nf_xp/test_system_alert_knowledge_postgresql.py.log | 6175 | e60b939809f10f45f0977215a17e24cead337cb62b8e6c6a2387f2428178a284 |
| harness/evidence/M111/T02/runs/m111-updates-c7vnopjz/result.json | 924 | 0538bb8122281d5c8bce8b1707411347ebe0f695545748ae8b2079cba559798c |
| harness/evidence/M111/T02/runs/m111-updates-c7vnopjz/test_system_alert_knowledge_postgresql.py.log | 5141 | 6a97887b00ad72e788273b28026a94dd81fa9bfe3e480ba7aecbcd7571497f2a |
| harness/evidence/M111/T02/runs/m111-updates-hz7umfqy/result.json | 373 | 80b70947c1f5c53c8f64cc7f99d7e9946cd3c6dddc8279863a485e437649fcbb |
| harness/evidence/M111/T02/runs/m111-updates-j5r86gn2/result.json | 924 | 3fea8671ed0aa7489dd980913f4c150ec804827f88a829c9c28efdcf4db8a1a2 |
| harness/evidence/M111/T02/runs/m111-updates-j5r86gn2/test_system_alert_knowledge_postgresql.py.log | 5141 | a3778587027c081144878047c427ab831dbfca8034eb00d9fc3d081fd50b749a |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/result.json | 4888 | ed40173b4f5ef7f5738484e33f2f67e8efe0c96b5c752573c6cc364a9c58b660 |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_assignment_targets.py.log | 44029 | 38195ccf49ee1d164aba36dc040b28c240a7d1044d4897e13c8cfcad2ddd771e |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_database.py.log | 1575 | bebc4cc6735ca0c1b6c00a1f99d6ae333a8365d352f17d22b377df4ba31a3365 |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_metrics_api.py.log | 1019 | 2d56e4f393d939a2a3a88a3d28fb5266e99b5023daa788786998e999cac51990 |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_model_download.py.log | 26811 | bc751a968310d54c14c11a9df209318b9cea50959eab7ad663c92a08ec8421b6 |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_model_update_api.py.log | 1699 | fc09ed182a27af54718ce814f905453f556990ba013f5ad2f6a6369369e5f85f |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_model_update_auth.py.log | 7611 | e36f335a5aa76be07a5eb2632272eb37a38e864b8ac5cc9fa4d8266aa6210af3 |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_model_update_concurrency.py.log | 11951 | d2b9ba1a3d54f92375e0df25ceda8c59e0f261b4d7b5edc81ec2c8034f19930d |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_model_update_delivery.py.log | 2255 | f42de35c905c20b9ad5b040e5d8c6bb6f80a13c663deb2675bbbc0dd6235a402 |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_model_update_migration.py.log | 16338 | 440322a61fe847a90925fe304ab99c0272d6cf894c65bfa9042b406859cadee8 |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_model_update_projection.py.log | 54970 | 80b0fbe5e6aad40a49571e7408e751ec07e62188484f5717f24ac3ac37d12617 |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_model_updates.py.log | 68971 | 0f19b9cb95dd1ca57a71cae9988124be920c830b6bd0dfc6a9b039b35847f28c |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_project_scene_installation.py.log | 119821 | d7486d74c30408601ff2d289de8e5b51e2fc773502211b00921fc87d520c5f86 |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_project_scenes.py.log | 61653 | 470d7d7ad3bb7751803f7e0fe2f0dcab6adb465ba30e565b5a9e229d153eb798 |
| harness/evidence/M111/T02/runs/m111-updates-khvnz4ga/test_resource_lifecycle.py.log | 73669 | d2daf0ebf7a61f2e5ee5485a4fe192879561bc1c7f7671fefbe5b2cdf7f052d1 |

<!-- run:m111-updates-tr65h8gg -->
## 运行 m111-updates-tr65h8gg

- 时间：2026-11-12T06:42:37.456831+00:00 → 2026-11-12T06:42:38.216696+00:00
- 原结果：True；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：4e9faf48dbd4800f7af7d09599337ec2d872840d；工作区：有未提交/未跟踪变更
- 环境：Windows-11-10.0.26200-SP0; Python 3.13.15；隔离PostgreSQL：False
- 资源：端口关闭=非PG或未知；剩余测试schema=未记录

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_test_report_retention.py | 0 | 14 | 0/0/0 | OK |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。


清理状态：完成：本次隔离临时目录已删除；不保留原始日志/结果JSON/测试数据库

<!-- end-run:m111-updates-tr65h8gg -->

<!-- run:m111-updates-cv63s97s -->
## 运行 m111-updates-cv63s97s

- 时间：2026-11-12T06:50:07.989774+00:00 → 2026-11-12T06:50:23.170524+00:00
- 原结果：True；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：4e9faf48dbd4800f7af7d09599337ec2d872840d；工作区：有未提交/未跟踪变更
- 环境：Windows-11-10.0.26200-SP0; Python 3.13.15；隔离PostgreSQL：True
- 资源：端口关闭=True；剩余测试schema=[]

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_test_report_retention.py | 0 | 14 | 0/0/0 | OK |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。


清理状态：完成：本次隔离临时目录已删除；不保留原始日志/结果JSON/测试数据库

<!-- end-run:m111-updates-cv63s97s -->

<!-- run:m111-updates-s38y_5jh -->
## 运行 m111-updates-s38y_5jh

- 时间：2026-11-12T06:51:23.530355+00:00 → 2026-11-12T06:51:23.799362+00:00
- 原结果：False；测试遍历完成：True。该结果只覆盖下表，不代表整个产品验收通过。
- 版本：4e9faf48dbd4800f7af7d09599337ec2d872840d；工作区：有未提交/未跟踪变更
- 环境：Windows-11-10.0.26200-SP0; Python 3.13.15；隔离PostgreSQL：False
- 资源：端口关闭=非PG或未知；剩余测试schema=未记录

| 测试模式/命令参数 | 退出码 | 执行数 | 失败/错误/跳过 | 结束标记 |
|---|---:|---:|---|---|
| test_no_such_report_retention_case.py | 5 | 0 | 0/0/0 | 未提取到unittest结束标记 |

复现命令：在server-video-service中使用同版本环境，运行对应 `tools/accept_m111_updates.py` 或 `tools/accept_m112_lifecycle.py`，每行传 `--pattern <测试模式>`；原运行隔离PG为true时加 `--postgres`。未知版本不可视为精确复现。


清理状态：完成：本次隔离临时目录已删除；不保留原始日志/结果JSON/测试数据库

<!-- end-run:m111-updates-s38y_5jh -->
