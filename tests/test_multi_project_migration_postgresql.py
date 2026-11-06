import os
import unittest
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.config import settings
from app.database import DEFAULT_PROJECT_ID


@unittest.skipUnless(
    os.environ.get("RUN_POSTGRES_MIGRATION_TESTS") == "1",
    "set RUN_POSTGRES_MIGRATION_TESTS=1 for isolated-schema PostgreSQL migration integration",
)
class MultiProjectPostgreSqlMigrationTests(unittest.TestCase):
    def test_upgrade_repeat_and_downgrade_in_isolated_schema(self):
        self.assertIsNotNone(settings.database_url)
        schema_name = "m33_migration_" + uuid.uuid4().hex
        admin_engine = create_engine(settings.database_url)
        migration_url = make_url(settings.database_url).update_query_dict({
            "options": f"-csearch_path={schema_name}",
        })
        config = Config("alembic.ini")
        config.set_main_option(
            "sqlalchemy.url",
            migration_url.render_as_string(hide_password=False).replace("%", "%%"),
        )

        try:
            with admin_engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
            command.upgrade(config, "20260920_05")
            seed_engine = create_engine(migration_url)
            try:
                with seed_engine.begin() as connection:
                    connection.execute(text(
                        "INSERT INTO accounts "
                        "(username, password_hash, role, enabled, created_at, updated_at) "
                        "VALUES ('legacy-admin', 'hash', 'admin', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ))
                    connection.execute(text(
                        "INSERT INTO alert_events "
                        "(event_id, disposition_status, payload, created_at, updated_at) "
                        "VALUES ('legacy-event', 'OPEN', '{}'::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ))
            finally:
                seed_engine.dispose()
            command.upgrade(config, "head")
            command.upgrade(config, "head")
            command.check(config)

            isolated_engine = create_engine(migration_url)
            try:
                schema = inspect(isolated_engine)
                self.assertIn("project_memberships", schema.get_table_names())
                for table_name in ("projects", "project_memberships"):
                    for name in ("created_at", "updated_at"):
                        column = next(column for column in schema.get_columns(table_name) if column["name"] == name)
                        self.assertIsNotNone(column["default"], f"{table_name}.{name} must be set by the migrated schema")
                with isolated_engine.connect() as connection:
                    self.assertEqual(
                        connection.scalar(text(
                            "SELECT COUNT(*) FROM projects WHERE project_id = :project_id"
                        ), {"project_id": DEFAULT_PROJECT_ID}),
                        1,
                    )
                    # The legacy-backfilled schema must support normal API inserts:
                    # membership handlers intentionally omit timestamp columns.
                    connection.rollback()
                    transaction = connection.begin()
                    try:
                        account_id = str(uuid.uuid4())
                        connection.execute(text(
                            "INSERT INTO accounts (account_id, username, password_hash, role, platform_role, enabled, "
                            "created_at, updated_at) VALUES (:id, :username, 'hash', 'operator', 'NORMAL_USER', "
                            "true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                        ), {"id": account_id, "username": "migration-member-" + uuid.uuid4().hex[:8]})
                        connection.execute(text(
                            "INSERT INTO project_memberships (project_id, account_id, project_role, enabled, revision) "
                            "VALUES (:project, :account, 'PROJECT_USER', true, 1)"
                        ), {"project": DEFAULT_PROJECT_ID, "account": account_id})
                        self.assertEqual(1, connection.scalar(text(
                            "SELECT count(*) FROM project_memberships WHERE account_id=:account "
                            "AND created_at IS NOT NULL AND updated_at IS NOT NULL"
                        ), {"account": account_id}))
                    finally:
                        transaction.rollback()
                    self.assertEqual(
                        connection.scalar(text(
                            "SELECT COUNT(*) FROM alert_events "
                            "WHERE project_id = :project_id AND event_id = 'legacy-event'"
                        ), {"project_id": DEFAULT_PROJECT_ID}),
                        1,
                    )
            finally:
                isolated_engine.dispose()

            with self.assertRaisesRegex(RuntimeError, "permanently removed"):
                command.downgrade(config, "20260920_05")
        finally:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
            admin_engine.dispose()


if __name__ == "__main__":
    unittest.main()
