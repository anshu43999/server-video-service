"""Read-only source snapshot, restore only into a generated PostgreSQL schema.

Use only for an operator-requested rehearsal. MIGRATION_DATABASE_URL is required.
The source is never upgraded/cleaned; a blocked snapshot stays blocked. The random
restore schema is removed after verification, the private backup is retained.
"""
import argparse
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa
from sqlalchemy.engine import make_url
from app import project_migration as migration
from app.alert_evidence import AlertEvidenceStore
from app.config import settings


def rehearse(url, bundle, roots, *, evidence_bundle=None, upgrade_copy=False):
    if make_url(url).get_backend_name() != "postgresql":
        raise migration.MigrationError("this rehearsal requires PostgreSQL")
    prepared = migration.prepare(url, bundle, roots=roots, store=AlertEvidenceStore.from_settings(settings),
                                 evidence_bundle=evidence_bundle)
    manifest = migration.verify_bundle(bundle)
    schema_name = "m33_snapshot_restore_" + uuid4().hex
    rollback_schema = "m33_snapshot_rollback_" + uuid4().hex
    base = make_url(url)
    admin = sa.create_engine(base.update_query_dict({"options": "-csearch_path=pg_catalog"}))
    target = base.update_query_dict({"options": f"-csearch_path={schema_name}"})
    rollback = base.update_query_dict({"options": f"-csearch_path={rollback_schema}"})
    try:
        with admin.begin() as connection:
            connection.execute(sa.text(f'CREATE SCHEMA "{schema_name}"'))
            if upgrade_copy:
                connection.execute(sa.text(f'CREATE SCHEMA "{rollback_schema}"'))
        restored = migration.restore(target, bundle, maintenance=True)
        with migration.database_connection(target) as connection:
            after = migration.preflight(connection)
            if after["blockers"] != prepared["blockers"]:
                raise migration.MigrationError("restore changed preflight blockers")
        upgraded = None
        if upgrade_copy:
            copy_bundle = Path(bundle) / "isolated-upgrade"
            migration.prepare(target, copy_bundle)
            migration.restore(rollback, copy_bundle, maintenance=True)
            upgraded = migration.apply(target, copy_bundle, maintenance=True, archive_orphan_receipts=True)
            repeated = migration.apply(target, copy_bundle, maintenance=True, archive_orphan_receipts=True)
            if repeated["phase"] != "already-applied":
                raise migration.MigrationError("repeated snapshot migration was not idempotent")
            with migration.database_connection(target) as connection:
                migration.reconcile(connection, copy_bundle, migration.verify_bundle(copy_bundle))
            # Restore again AFTER migration to prove rollback still retains all orphans.
            with admin.begin() as connection:
                connection.execute(sa.text(f'DROP SCHEMA "{rollback_schema}" CASCADE'))
                connection.execute(sa.text(f'CREATE SCHEMA "{rollback_schema}"'))
            migration.restore(rollback, copy_bundle, maintenance=True)
            with migration.database_connection(rollback) as connection:
                if migration.preflight(connection)["blockers"] != prepared["blockers"]:
                    raise migration.MigrationError("rollback did not preserve original orphan receipts")
        with migration.database_connection(url) as connection:
            after_source = migration.preflight(connection)
            if (after_source["source"] != manifest["source"] or
                after_source["tables"] != manifest["tables"] or
                migration.schema_signature(connection) != manifest["schema"]):
                raise migration.MigrationError("source changed during isolated snapshot rehearsal")
        return {"snapshot": prepared, "restore": restored, "sourceModified": False,
                "upgradePerformed": bool(upgrade_copy), "upgradedIsolatedCopy": upgraded,
                "temporarySchemaRemoved": True}
    finally:
        with admin.begin() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
            if upgrade_copy:
                connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{rollback_schema}" CASCADE'))
        admin.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--evidence-root", action="append", type=Path, default=[])
    parser.add_argument("--evidence-bundle", type=Path)
    parser.add_argument("--upgrade-copy", action="store_true", help="archive orphans and migrate only the random isolated copy; verify rollback")
    args = parser.parse_args()
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        parser.error("set MIGRATION_DATABASE_URL explicitly")
    try:
        print(json.dumps(rehearse(url, args.bundle, args.evidence_root,
                                evidence_bundle=args.evidence_bundle, upgrade_copy=args.upgrade_copy), ensure_ascii=False))
    except migration.MigrationError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"error": "snapshot rehearsal failed", "type": type(exc).__name__}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
