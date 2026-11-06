import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


class LegacyApprovalRemovalMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.NamedTemporaryFile(suffix=".db", dir=Path(__file__).parent, delete=False)
        temporary.close()
        self.path = Path(temporary.name)
        self.url = f"sqlite:///{self.path.as_posix()}"
        self.config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        self.config.set_main_option("sqlalchemy.url", self.url)

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def test_upgrade_drops_legacy_data_and_downgrade_refuses_to_recreate_it(self):
        command.upgrade(self.config, "20261014_12")
        engine = create_engine(self.url)
        try:
            with engine.connect() as connection:
                self.assertEqual(
                    connection.scalar(text("SELECT COUNT(*) FROM legacy_approval_service")), 1
                )
        finally:
            engine.dispose()

        command.upgrade(self.config, "head")
        engine = create_engine(self.url)
        try:
            tables = set(inspect(engine).get_table_names())
            self.assertFalse(any(name.startswith("legacy_") for name in tables))
            self.assertIn("projects", tables)
            self.assertIn("alert_events", tables)
        finally:
            engine.dispose()

        with self.assertRaisesRegex(RuntimeError, "permanently removed"):
            command.downgrade(self.config, "20261014_12")


if __name__ == "__main__":
    unittest.main()
