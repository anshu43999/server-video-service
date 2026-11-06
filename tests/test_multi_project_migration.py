import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.database import DEFAULT_PROJECT_ID


TEST_DIRECTORY = Path(__file__).resolve().parent
PREVIOUS_REVISION = "20260920_05"

PROJECT_OWNED_TABLES = (
    "alert_events",
    "alert_disposition_actions",
    "false_positive_feedback",
    "alert_rules",
    "alert_rule_bindings",
    "alert_rule_audits",
    "model_parameter_profiles",
    "model_parameter_audits",
    "alert_verification_config",
    "alert_verifications",
    "alert_delivery_receipts",
    "stream_configs",
)


class MultiProjectMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.NamedTemporaryFile(suffix=".db", dir=TEST_DIRECTORY, delete=False)
        temporary.close()
        self.path = Path(temporary.name)
        self.url = f"sqlite:///{self.path.as_posix()}"
        self.config = Config(str(TEST_DIRECTORY.parent / "alembic.ini"))
        self.config.set_main_option("sqlalchemy.url", self.url)

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def test_empty_database_upgrade_is_repeatable_and_reversible(self):
        command.upgrade(self.config, "20261014_12")
        command.upgrade(self.config, "20261014_12")

        engine = create_engine(self.url)
        try:
            schema = inspect(engine)
            self.assertIn("projects", schema.get_table_names())
            self.assertIn("project_memberships", schema.get_table_names())
            self.assertIn("project_model_assignments", schema.get_table_names())
            self.assertIn("project_audit_events", schema.get_table_names())
            for table_name in ("projects", "project_memberships"):
                columns = {column["name"]: column for column in schema.get_columns(table_name)}
                for name in ("created_at", "updated_at"):
                    self.assertIsNotNone(columns[name]["default"], f"{table_name}.{name}")
            with engine.connect() as connection:
                self.assertEqual(
                    connection.scalar(text("SELECT COUNT(*) FROM projects WHERE project_id = :project_id"),
                                      {"project_id": DEFAULT_PROJECT_ID}),
                    1,
                )
        finally:
            engine.dispose()

        command.downgrade(self.config, PREVIOUS_REVISION)
        engine = create_engine(self.url)
        try:
            schema = inspect(engine)
            self.assertNotIn("projects", schema.get_table_names())
            self.assertNotIn("account_id", {column["name"] for column in schema.get_columns("accounts")})
        finally:
            engine.dispose()
        command.upgrade(self.config, "20261014_12")

    def test_existing_rows_are_backfilled_and_external_ids_are_project_qualified(self):
        command.upgrade(self.config, PREVIOUS_REVISION)
        self._seed_legacy_rows()
        command.upgrade(self.config, "20261014_12")

        engine = create_engine(self.url)
        try:
            schema = inspect(engine)
            self.assertEqual(schema.get_pk_constraint("accounts")["constrained_columns"], ["account_id"])
            account_foreign_keys = schema.get_foreign_keys("account_sessions")
            self.assertTrue(any(
                key["constrained_columns"] == ["account_id"] and key["referred_table"] == "accounts"
                for key in account_foreign_keys
            ))
            self.assertFalse(any(key["constrained_columns"] == ["username"] for key in account_foreign_keys))
            self.assertEqual(
                schema.get_pk_constraint("alert_events")["constrained_columns"],
                ["project_id", "event_id"],
            )
            self.assertEqual(
                schema.get_pk_constraint("stream_configs")["constrained_columns"],
                ["project_id", "stream_id"],
            )
            with engine.begin() as connection:
                accounts = connection.execute(text(
                    "SELECT username, account_id, platform_role FROM accounts ORDER BY username"
                )).mappings().all()
                self.assertEqual([row["platform_role"] for row in accounts], ["PLATFORM_ADMIN", "NORMAL_USER"])
                self.assertEqual(len({row["account_id"] for row in accounts}), 2)

                memberships = connection.execute(text(
                    "SELECT project_role FROM project_memberships ORDER BY project_role"
                )).scalars().all()
                self.assertEqual(memberships, ["PROJECT_OWNER", "PROJECT_USER"])
                for table_name in PROJECT_OWNED_TABLES:
                    self.assertEqual(
                        connection.scalar(text(
                            f'SELECT COUNT(*) FROM "{table_name}" WHERE project_id IS NULL'
                        )),
                        0,
                    )
                    self.assertEqual(connection.scalar(text(f'SELECT COUNT(*) FROM "{table_name}"')), 1)

                second_project = "11111111-1111-1111-1111-111111111111"
                admin_id = accounts[0]["account_id"]
                connection.execute(text(
                    "INSERT INTO projects "
                    "(project_id, project_code, display_name, lifecycle_state, revision, "
                    "created_by_account_id, created_at, updated_at) "
                    "VALUES (:project_id, 'second', 'Second', 'ACTIVE', 1, :admin_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ), {"project_id": second_project, "admin_id": admin_id})
                connection.execute(text(
                    "INSERT INTO stream_configs "
                    "(project_id, stream_id, display_name, source_type, confidence, max_fps, "
                    "yolo_enabled, overlay_enabled, enabled, revision, created_at, updated_at) "
                    "VALUES (:project_id, 'stream-1', 'Duplicate ID', 'rtsp', 0.5, 5, 0, 1, 1, 1, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ), {"project_id": second_project})
                connection.execute(text(
                    "INSERT INTO alert_events "
                    "(project_id, event_id, disposition_status, payload, created_at, updated_at) "
                    "VALUES (:project_id, 'event-1', 'OPEN', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ), {"project_id": second_project})
        finally:
            engine.dispose()

        with self.assertRaisesRegex(RuntimeError, "downgrade refused"):
            command.downgrade(self.config, PREVIOUS_REVISION)

        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "DELETE FROM alert_events WHERE project_id <> :project_id"
                ), {"project_id": DEFAULT_PROJECT_ID})
                connection.execute(text(
                    "DELETE FROM stream_configs WHERE project_id <> :project_id"
                ), {"project_id": DEFAULT_PROJECT_ID})
                connection.execute(text(
                    "DELETE FROM projects WHERE project_id <> :project_id"
                ), {"project_id": DEFAULT_PROJECT_ID})
        finally:
            engine.dispose()
        command.downgrade(self.config, PREVIOUS_REVISION)

        engine = create_engine(self.url)
        try:
            with engine.connect() as connection:
                self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM alert_events")), 1)
                self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM accounts")), 2)
        finally:
            engine.dispose()

    def test_legacy_accounts_without_an_enabled_admin_fail_before_schema_changes(self):
        command.upgrade(self.config, PREVIOUS_REVISION)
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO accounts (username, password_hash, role, enabled, created_at, updated_at) "
                    "VALUES ('operator', 'hash', 'operator', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ))
        finally:
            engine.dispose()

        with self.assertRaisesRegex(RuntimeError, "no enabled administrator owner"):
            command.upgrade(self.config, "head")

        engine = create_engine(self.url)
        try:
            schema = inspect(engine)
            self.assertNotIn("account_id", {column["name"] for column in schema.get_columns("accounts")})
            self.assertNotIn("projects", schema.get_table_names())
        finally:
            engine.dispose()

    def _seed_legacy_rows(self):
        engine = create_engine(self.url)
        now = datetime.now(timezone.utc)
        payload = json.dumps({})
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO accounts (username, password_hash, role, enabled, created_at, updated_at) VALUES "
                    "('admin', 'hash', 'admin', 1, :now, :now), "
                    "('operator', 'hash', 'operator', 1, :now, :now)"
                ), {"now": now})
                connection.execute(text(
                    "INSERT INTO account_sessions "
                    "(session_hash, username, role, expires_at, created_at) "
                    "VALUES ('session', 'admin', 'admin', :now, :now)"
                ), {"now": now})
                connection.execute(text(
                    "INSERT INTO alert_events "
                    "(event_id, disposition_status, payload, created_at, updated_at) "
                    "VALUES ('event-1', 'OPEN', :payload, :now, :now)"
                ), {"payload": payload, "now": now})
                connection.execute(text(
                    "INSERT INTO alert_disposition_actions "
                    "(id, event_id, status, actor, acted_at_us, created_at) "
                    "VALUES (1, 'event-1', 'ACKNOWLEDGED', 'admin', 1, :now)"
                ), {"now": now})
                connection.execute(text(
                    "INSERT INTO false_positive_feedback (entry_id, event_id, action_id, payload, created_at) "
                    "VALUES ('feedback-1', 'event-1', 1, :payload, :now)"
                ), {"payload": payload, "now": now})
                connection.execute(text(
                    "INSERT INTO alert_rules "
                    "(rule_id, rule_version, enabled, payload, created_at, updated_at) "
                    "VALUES ('rule-1', 1, 1, :payload, :now, :now)"
                ), {"payload": payload, "now": now})
                connection.execute(text(
                    "INSERT INTO alert_rule_bindings (rule_id, source_id, accepted, payload, updated_at) "
                    "VALUES ('rule-1', 'source-1', 1, :payload, :now)"
                ), {"payload": payload, "now": now})
                connection.execute(text(
                    "INSERT INTO alert_rule_audits "
                    "(id, rule_id, action, rule_version, actor, payload, created_at) "
                    "VALUES (1, 'rule-1', 'CREATE', 1, 'admin', :payload, :now)"
                ), {"payload": payload, "now": now})
                connection.execute(text(
                    "INSERT INTO model_parameter_profiles "
                    "(profile_key, model_id, model_version, platform, revision, payload, created_at, updated_at) "
                    "VALUES ('profile-1', 'model-1', '1', 'server', 1, :payload, :now, :now)"
                ), {"payload": payload, "now": now})
                connection.execute(text(
                    "INSERT INTO model_parameter_audits "
                    "(id, profile_key, action, revision, actor, payload, created_at) "
                    "VALUES (1, 'profile-1', 'CREATE', 1, 'admin', :payload, :now)"
                ), {"payload": payload, "now": now})
                connection.execute(text(
                    "INSERT INTO alert_verification_config "
                    "(config_key, calls_day, calls_today, payload, updated_at) "
                    "VALUES ('default', 10, 0, :payload, :now)"
                ), {"payload": payload, "now": now})
                connection.execute(text(
                    "INSERT INTO alert_verifications "
                    "(event_id, status, payload, created_at, updated_at) "
                    "VALUES ('event-1', 'DONE', :payload, :now, :now)"
                ), {"payload": payload, "now": now})
                connection.execute(text(
                    "INSERT INTO alert_delivery_receipts "
                    "(delivery_id, event_id, channel, status, attempts, payload, created_at, updated_at) "
                    "VALUES ('delivery-1', 'event-1', 'webhook', 'SENT', 1, :payload, :now, :now)"
                ), {"payload": payload, "now": now})
                connection.execute(text(
                    "INSERT INTO stream_configs "
                    "(stream_id, display_name, source_type, confidence, max_fps, yolo_enabled, "
                    "overlay_enabled, enabled, revision, created_at, updated_at) "
                    "VALUES ('stream-1', 'Legacy', 'rtsp', 0.5, 5, 0, 1, 1, 1, :now, :now)"
                ), {"now": now})
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
