# Multi-project database baseline migration

Owner: `M33-T02`  
Revision: `20261010_06`  
Contract: `docs/multi-project-rbac-contract.md`

T14 operational tooling and current rollout blockers are documented in
`docs/default-project-rollout.md`. Its restore rehearsal gate must pass before
applying a migration bundle; the current local legacy database has 167 orphan
delivery receipts and has not been upgraded.

## Scope

This revision establishes the storage primitives used by later authorization and API tasks:

- immutable `accounts.account_id` and `accounts.platform_role` while retaining `username` as the legacy login key;
- `projects` and the explicit default project `00000000-0000-0000-0000-000000000001`;
- many-to-many `project_memberships` with project-scoped roles;
- project model assignments and append-only project audit events;
- non-null `project_id` ownership on existing project business tables;
- project-qualified primary/unique keys and composite foreign keys for reusable external IDs.

Global conversion jobs, conversion configuration and calibration datasets remain platform-scoped.

## Safe ordering

The migration performs these phases in one Alembic revision:

1. Add nullable identity columns and deterministically backfill account IDs.
2. Validate that identity columns contain no null values, then add constraints.
3. Create the explicit default project and deterministic legacy-role memberships for later review.
4. Capture row counts for every project-owned table.
5. Add nullable `project_id`, backfill only to the known default project, and validate no nulls.
6. Replace global external-ID keys and foreign keys with project-qualified constraints.
7. Create assignment and audit tables.
8. Reconcile every captured row count before the revision is accepted.

No migration step chooses the first available project. The default project ID is fixed and auditable.

## Capacity and locking assessment

Before applying this revision to a production snapshot, collect row counts and relation sizes for all
tables listed in `PROJECT_OWNED_TABLES`. PostgreSQL uses native `ALTER TABLE`; it does not copy whole
tables. Adding and backfilling `project_id`, changing primary keys, and creating indexes can still take
locks and scan each table. Schedule a write-maintenance window sized from the largest of
`alert_events`, `alert_delivery_receipts`, and `stream_configs`, with free disk space for new indexes.

SQLite uses Alembic batch table reconstruction because SQLite cannot express the required constraint
changes in place. It therefore needs free disk space greater than the sum of affected table and index
sizes and exclusive access for the complete migration.

`M33-T14` owns production dry-run reports, checkpoints, backup/restore orchestration, evidence-object
reconciliation, and bounded compatibility rollout. This baseline intentionally fails rather than
guessing if a required backfill is null or if row counts change.

## Rollback boundary

Downgrade to `20260920_05` is supported only while all business rows remain in the default project and
the new assignment/audit tables are empty. Alembic refuses a lossy downgrade when it detects another
project, non-default project data, model assignments, or project audit history. Take and verify a
database backup before production migration even when this downgrade gate is expected to remain open.

## Verification

M33-T17 snapshot rehearsal found the unreleased `_06` migration omitted
`CURRENT_TIMESTAMP` defaults on `projects` and `project_memberships` timestamps,
unlike the ORM-created schema. The migration now supplies them, and membership
creation explicitly supplies timestamps for compatibility with earlier rehearsal
schemas. This does not retrofit a database already stamped `_06` or later;
inspect deployed schema defaults before release and plan a forward repair if
required. Do not re-run or stamp historical revisions over live data.

Automated coverage includes:

- SQLite empty-schema upgrade, repeated upgrade, downgrade, and re-upgrade;
- SQLite upgrade of a populated legacy schema and row-count/null reconciliation;
- duplicate `stream_id` and `event_id` values in separate projects;
- downgrade refusal when it would lose multi-project state;
- PostgreSQL 17 upgrade/downgrade/re-upgrade in a random isolated schema with seeded legacy rows.

Run the PostgreSQL migration test explicitly:

```powershell
$env:RUN_POSTGRES_MIGRATION_TESTS = '1'
python -m unittest discover -s tests -p "test_multi_project_migration_postgresql.py" -v
```
