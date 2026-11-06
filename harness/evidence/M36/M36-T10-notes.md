# M36-T10 development evidence

- Initial pre-fixture-update scene suite: 33 tests, 5 PostgreSQL skips, 1 SQLite approval error (`Mock` parameter fixture had no real parameter store). Product/API tests passed. The fixture now uses the production parameter store and exact model identities; rerun logs are retained beside this file.
- Scope: source and isolated test schemas only. No changes to the running 8080 instance or Default Project under this task.

## Final verification

- `M36-T10-combined-regression.log`: 116 tests passed, no skips (148.295 s), including model catalog, parameter store/API, database health, assignment migration, scene authorization/storage/migrations and assignment APIs with real isolated PostgreSQL enabled.
- `M36-T10-concurrency-final.log`: 9 tests passed, no skips (11.430 s), including independent-store project parameter and inherited platform parameter write/approval races, SQLite/PostgreSQL upgrade/retry/downgrade protection, durable snapshots and audit rollback.
- `M36-T10-harness.log`: 34 Harness tests passed.
- Earlier targeted runs retained: scene regression 33 tests (5 PostgreSQL skips), parameter regression 38 tests with PostgreSQL enabled (all passed), assignment regression 26 tests (5 PostgreSQL skips). Final combined runs fill those real database cases.

## Boundaries

The current local service is not changed by M36-T10. M36-T11 owns backup, migration, restart and explicitly user-authorized mobile-only internal-test publication. M104-T06 owns Android consumption and production workbench wiring. Multi-model orchestration remains unsupported; this implementation only resolves authorized single-member scenes.
