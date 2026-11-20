# M36-T17 Progress Evidence

Date: 2026-10-21

## Verified

- Multi-member plan parameter sources retain each member's approval-frozen snapshot after saving to SQLite, closing the database manager, and reopening the scene store.
- A v3 sync resolve succeeds for an approved plan; editing the scene invalidates approval and a repeated request with the old revision is rejected (`404 scene_not_found`).
- Focused regression command (Windows):
  `PYTHONPATH=tests .venv/Scripts/python.exe -m unittest test_scene_execution_parameters.SceneParameterSqliteTests.test_approved_multimember_plan_parameter_sources_persist_after_reopen test_project_scene_installation.SceneInstallationApiTests.test_multimember_resolve_rejects_stale_approval_after_scene_revision_changes -v`
  Result: 2 tests passed.
- Harness unit tests: `python -m unittest discover -s harness/tests -p "test_*.py"` — 34 tests passed.
- `python harness/harness.py validate` — passed.
- PostgreSQL was run using the documented isolation procedure: an ephemeral cluster initialized with role `aiyolo_app`, test URL targeting only `127.0.0.1:55441/postgres`, and random-schema cleanup through `tests/postgresql_support.py`.
- PostgreSQL scene persistence/concurrency/migration tests: `test_scene_execution_parameters.SceneParameterPostgresTests` and `SceneParameterMigrationTests` — 10 tests passed, no skips.
- Combined scene API, v2/v3 contract, SQLite persistence, PostgreSQL persistence/concurrency, and migration regression: 37 tests passed.
- Migration downgrade coverage now reflects backend DDL semantics: PostgreSQL transactional DDL rolls back the partial downgrade; SQLite reports the later migration revision after non-transactional DDL. Both retain the explicit guard against dropping stable member identities.

## Scope and limitations

The application connection was verified read-only at `127.0.0.1:5432/aiyolo_dev` as role `aiyolo_app`. The earlier failed attempt had combined a temporary cluster initialized with another default role and an inherited development URL. No application database role or data was changed. The corrected temporary PostgreSQL instance was stopped by its exact data directory, and port 55441 was confirmed closed.

The durable connection/isolation procedure is documented in `harness/POSTGRES_TESTING.md` and linked from `harness/README.md`. This contract resolves configuration only; it does not start multi-model inference and has not been validated on Android/API 27.
