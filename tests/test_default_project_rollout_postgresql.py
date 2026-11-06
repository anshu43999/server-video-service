import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from datetime import datetime, timezone

from alembic import command
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from app.config import settings
from app import project_migration as migration


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "requires isolated PostgreSQL schemas")
class PostgreSQLDefaultProjectRolloutTests(unittest.TestCase):
    def test_backup_fault_retry_reconcile_restore_sequences(self):
        source_schema = "m33_rollout_" + uuid4().hex
        restore_schema = "m33_restore_" + uuid4().hex
        base = make_url(settings.database_url)
        admin = sa.create_engine(base.update_query_dict({"options": "-csearch_path=pg_catalog"}))
        source = base.update_query_dict({"options": f"-csearch_path={source_schema}"})
        restored = base.update_query_dict({"options": f"-csearch_path={restore_schema}"})
        with tempfile.TemporaryDirectory(prefix="m33-t14-pg-") as directory:
            bundle = Path(directory) / "backup"
            try:
                with admin.begin() as connection:
                    connection.execute(sa.text(f'CREATE SCHEMA "{source_schema}"'))
                    connection.execute(sa.text(f'CREATE SCHEMA "{restore_schema}"'))
                with migration.database_connection(source, write=True) as connection:
                    command.upgrade(migration.config(connection), migration.LEGACY)
                    metadata, _ = migration.schema(connection)
                    now = datetime.now(timezone.utc)
                    connection.execute(metadata.tables["accounts"].insert(), [
                        dict(username="admin", password_hash="hash", role="admin", enabled=True, created_at=now, updated_at=now),
                        dict(username="user", password_hash="hash", role="operator", enabled=False, created_at=now, updated_at=now),
                    ])
                    connection.execute(metadata.tables["alert_events"].insert().values(
                        event_id="event-1", disposition_status="OPEN", payload={"evidence": {
                            "snapshotUri": "data:image/png;base64,aW1hZ2U="}}, created_at=now, updated_at=now))
                    connection.execute(metadata.tables["alert_disposition_actions"].insert().values(
                        id=40, event_id="event-1", status="ACKNOWLEDGED", actor="admin", acted_at_us=1, created_at=now))
                    connection.execute(sa.text("SELECT setval('alert_disposition_actions_id_seq', 75, true)"))
                migration.prepare(source, bundle)
                migration.restore(restored, bundle, maintenance=True)
                for point in ("after-schema", "before-commit"):
                    def fail(phase):
                        if phase == point:
                            raise RuntimeError("injected")
                    with self.assertRaisesRegex(RuntimeError, "injected"):
                        migration.apply(source, bundle, maintenance=True, fault=fail)
                    with migration.database_connection(source) as connection:
                        self.assertEqual(migration.LEGACY, migration.preflight(connection)["revision"])
                migration.apply(source, bundle, maintenance=True)
                self.assertEqual("already-applied", migration.apply(source, bundle, maintenance=True)["phase"])
                with migration.database_connection(source) as connection:
                    migration.reconcile(connection, bundle, migration.verify_bundle(bundle))
                    command.check(migration.config(connection))
                with migration.database_connection(restored, write=True) as connection:
                    self.assertEqual(migration.LEGACY, migration.preflight(connection)["revision"])
                    new_id = connection.scalar(sa.text(
                        "INSERT INTO alert_disposition_actions(event_id,status,actor,acted_at_us,created_at) "
                        "VALUES ('event-1','RESOLVED','admin',2,CURRENT_TIMESTAMP) RETURNING id"))
                    self.assertGreater(new_id, 75)
            finally:
                with admin.begin() as connection:
                    connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{source_schema}" CASCADE'))
                    connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{restore_schema}" CASCADE'))
                admin.dispose()

    def test_orphan_archive_rollback_and_restore_in_isolated_schemas(self):
        source_schema = "m33_orphans_" + uuid4().hex
        restore_schema = "m33_orphans_restore_" + uuid4().hex
        base = make_url(settings.database_url)
        admin = sa.create_engine(base.update_query_dict({"options": "-csearch_path=pg_catalog"}))
        source = base.update_query_dict({"options": f"-csearch_path={source_schema}"})
        restored = base.update_query_dict({"options": f"-csearch_path={restore_schema}"})
        with tempfile.TemporaryDirectory(prefix="m33-t14-pg-orphans-") as directory:
            bundle = Path(directory) / "backup"
            try:
                with admin.begin() as connection:
                    connection.execute(sa.text(f'CREATE SCHEMA "{source_schema}"'))
                    connection.execute(sa.text(f'CREATE SCHEMA "{restore_schema}"'))
                with migration.database_connection(source, write=True) as connection:
                    command.upgrade(migration.config(connection), migration.LEGACY)
                    metadata, _ = migration.schema(connection)
                    now = datetime.now(timezone.utc)
                    connection.execute(metadata.tables["accounts"].insert().values(
                        username="admin", password_hash="hash", role="admin", enabled=True,
                        created_at=now, updated_at=now))
                    connection.execute(metadata.tables["alert_events"].insert().values(
                        event_id="event-1", disposition_status="OPEN", payload={}, created_at=now, updated_at=now))
                    connection.execute(metadata.tables["alert_delivery_receipts"].insert(), [
                        dict(delivery_id="linked", event_id="event-1", channel="webhook", status="SENT",
                             attempts=1, payload={}, created_at=now, updated_at=now),
                        dict(delivery_id="orphan", event_id="missing", channel="webhook", status="SENT",
                             attempts=1, payload={}, created_at=now, updated_at=now),
                    ])
                prepared = migration.prepare(source, bundle)
                self.assertEqual(1, prepared["orphanArchive"]["count"])
                migration.restore(restored, bundle, maintenance=True)
                for phase in ("after-archive", "after-schema", "before-commit"):
                    def inject(current):
                        if current == phase:
                            raise RuntimeError("injected")
                    with self.assertRaisesRegex(RuntimeError, "injected"):
                        migration.apply(source, bundle, maintenance=True, archive_orphan_receipts=True, fault=inject)
                    with migration.database_connection(source) as connection:
                        self.assertEqual(migration.LEGACY, migration.preflight(connection)["revision"])
                        self.assertEqual(2, connection.scalar(sa.text("SELECT COUNT(*) FROM alert_delivery_receipts")))
                result = migration.apply(source, bundle, maintenance=True, archive_orphan_receipts=True)
                self.assertEqual(1, result["onlineDeliveryReceipts"])
                with migration.database_connection(source) as connection:
                    self.assertEqual("linked", connection.scalar(sa.text("SELECT delivery_id FROM alert_delivery_receipts")))
                    migration.reconcile(connection, bundle, migration.verify_bundle(bundle))
                with migration.database_connection(restored) as connection:
                    self.assertEqual(2, connection.scalar(sa.text("SELECT COUNT(*) FROM alert_delivery_receipts")))
            finally:
                with admin.begin() as connection:
                    connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{source_schema}" CASCADE'))
                    connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{restore_schema}" CASCADE'))
                admin.dispose()


if __name__ == "__main__":
    unittest.main()
