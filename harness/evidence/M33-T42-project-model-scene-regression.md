# M33-T42 Project Model and Scene Regression Evidence

Date: 2026-11-02

## Delivered

- Removed the retired scenario-keyed project model assignment implementation and the scene-list legacy projection hook.
- Kept project inventory identity on exact model release and target; PC/mobile releases can be separately authorized and multiple releases can coexist.
- Updated project model API and persistence fixtures to use the inventory endpoint and projectModelId.
- Updated scene, lifecycle, model-update, and cross-project stream fixtures to select project inventory members and explicitly select an approved scene plan for streams.
- Removed the obsolete target-assignment and scenario-assignment migration regression suites. Added isolated SQLite coverage for discarding old scenario assignment rows and refusing downgrade to the retired schema.
- Retired v1 compatibility text now directs readers to the current project model/scene contracts. Historical migrations remain immutable.
- No runtime database or Default Project configuration was opened or changed.

## Verification

- test_project_model_inventory.py: 18 passed, 7 PostgreSQL-only tests skipped.
- test_project_model_assignment_storage.py: 8 passed, 5 PostgreSQL-only tests skipped.
- Cross-layer SQLite-focused suite (test_project_scenes, scene authorization/installation/suite tests, scene execution/runtime grants, stream config/recovery, model download/catalog/marketplace): 216 passed, 36 PostgreSQL-only tests skipped.
- Model-update consumers (test_m112_sync, test_model_update_projection): 81 passed, 41 PostgreSQL-only tests skipped.
- test_resource_lifecycle.py: 29 passed, 13 PostgreSQL-only tests skipped.
- test_project_isolation_matrix.py: 7 passed.
- Admin web tests: 24 files, 161 tests passed. Production build/typecheck passed.
- Harness unit tests: 34 passed.
- alembic heads: one head, 20261102_32.

## Residual Risk

PostgreSQL-only concurrency and migration cases were skipped because the isolated PostgreSQL test environment was not configured. The historical migration chain retains scenario columns only in pre-reset revisions so isolated upgrade tests can construct old schemas; the current inventory schema and runtime code contain no scenario-based project authorization.
