import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


class ProjectLifecycleMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.NamedTemporaryFile(suffix=".db", dir=Path(__file__).parent, delete=False)
        temporary.close()
        self.path = Path(temporary.name)
        self.url = f"sqlite:///{self.path.as_posix()}"
        self.config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        self.config.set_main_option("sqlalchemy.url", self.url)

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def test_account_revision_platform_audit_and_metadata_are_reversible(self):
        command.upgrade(self.config, "20261010_06")
        engine = create_engine(self.url)
        try:
            self.assertNotIn("revision", {item["name"] for item in inspect(engine).get_columns("accounts")})
            self.assertNotIn("platform_audit_events", inspect(engine).get_table_names())
        finally:
            engine.dispose()

        command.upgrade(self.config, "20261014_12")
        engine = create_engine(self.url)
        try:
            schema = inspect(engine)
            self.assertIn("revision", {item["name"] for item in schema.get_columns("accounts")})
            self.assertIn("platform_audit_events", schema.get_table_names())
        finally:
            engine.dispose()

        command.downgrade(self.config, "20261010_06")
        engine = create_engine(self.url)
        try:
            schema = inspect(engine)
            self.assertNotIn("revision", {item["name"] for item in schema.get_columns("accounts")})
            self.assertNotIn("platform_audit_events", schema.get_table_names())
        finally:
            engine.dispose()

    def test_downgrade_refuses_to_discard_platform_audit_history(self):
        command.upgrade(self.config, "20261014_12")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO platform_audit_events "
                    "(audit_id, action, target_type, target_id, change_summary, outcome) "
                    "VALUES ('audit-1', 'account.update', 'account', 'account-1', '{}', 'SUCCESS')"
                ))
        finally:
            engine.dispose()

        with self.assertRaisesRegex(RuntimeError, "discard platform audit history"):
            command.downgrade(self.config, "20261010_06")


if __name__ == "__main__":
    unittest.main()
