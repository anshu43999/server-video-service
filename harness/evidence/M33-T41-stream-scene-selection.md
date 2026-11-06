# M33-T41 Stream Scene Selection Evidence

Date: 2026-11-02

## Delivered

- Stream creation now requires `sceneId`, `planId`, and `sceneRevision`.
- Stream selection is resolved for the current project, PC target, and video input. Disabled, unapproved, stale, cross-project, unavailable, and multi-member plans fail closed through the scene resolver; the stream runtime accepts only a single-member plan.
- The resolved scene parameter snapshot is passed into the detector and returned by per-frame runtime authorization. Startup, restoration, YOLO enablement, and plan changes re-resolve the current scene plan.
- Direct `model_id`/`model_version` create/configuration requests are rejected. The existing stream model-selection endpoint now accepts only explicit scene-plan identity.
- The stream admin page lists only enabled, approved PC video single-member plans and pins the scene revision. Stale selections are reported and cannot be used to create or enable a stream.
- Added migration `20261102_32` for nullable scene-plan identity fields without backfill. Rows without an explicit selection cannot be restored into a running stream.

## Verification

- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_stream_config_persistence.py -v`: 11 passed.
- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_stream_restart_recovery.py -v`: 8 passed.
- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_project_scenes.py -v`: 19 passed, 5 PostgreSQL-only tests skipped because no isolated PostgreSQL schema was configured.
- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_scene_execution_parameters.py -v`: 53 passed, 8 PostgreSQL-only/row-lock tests skipped because no isolated PostgreSQL schema was configured.
- `admin-web`: `npm run test`: 24 files, 161 tests passed. Vitest printed two non-fatal `ECONNRESET` socket messages while all tests passed.
- `admin-web`: `npm run build`: typecheck and production bundle passed.
- `.venv/Scripts/python.exe -m alembic heads`: one head, `20261102_32`.

## Residual Risk

PostgreSQL row-locking and cross-worker revocation races were not exercised because an isolated PostgreSQL schema was unavailable. The runtime re-resolves authorization for each analysis frame; no server-side multi-model scheduling was added.
