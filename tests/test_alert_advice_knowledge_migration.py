import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


ROOT = Path(__file__).resolve().parents[1]


class AlertAdviceKnowledgeMigrationTest(unittest.TestCase):
    def setUp(self):
        (ROOT / ".test-db").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".test-db")
        self.path = Path(self.temp.name) / "migration.db"
        self.url = f"sqlite+pysqlite:///{self.path.as_posix()}"
        self.config = Config(str(ROOT / "alembic.ini"))
        self.config.set_main_option("sqlalchemy.url", self.url.replace("%", "%%"))

    def tearDown(self):
        self.temp.cleanup()

    def test_upgrade_is_rerunnable_and_empty_downgrade_succeeds(self):
        command.upgrade(self.config, "20261027_25")
        command.upgrade(self.config, "20261027_25")
        engine = create_engine(self.url)
        try:
            tables = set(inspect(engine).get_table_names())
            self.assertIn("alert_advice_knowledge_entries", tables)
            self.assertIn("alert_advice_knowledge_revisions", tables)
        finally:
            engine.dispose()
        command.downgrade(self.config, "20261026_24")
        engine = create_engine(self.url)
        try:
            self.assertNotIn("alert_advice_knowledge_entries", inspect(engine).get_table_names())
        finally:
            engine.dispose()

    def test_durable_knowledge_refuses_downgrade(self):
        command.upgrade(self.config, "20261027_25")
        engine = create_engine(self.url)
        try:
            project_id = "00000000-0000-0000-0000-000000000099"
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO projects (project_id, project_code, display_name, lifecycle_state, revision) "
                    "VALUES (:id, 'migration-advice', 'Migration Advice', 'ACTIVE', 1)"
                ), {"id": project_id})
                connection.execute(text(
                    "INSERT INTO alert_advice_knowledge_entries "
                    "(project_id, entry_id, alert_type_id, recognition_category_id, status, revision, payload, created_by, updated_by) "
                    "VALUES (:project, 'entry', 'PPE_NO_HELMET', 'HEAD', 'ACTIVE', 1, '{}', 'test', 'test')"
                ), {"project": project_id})
        finally:
            engine.dispose()
        with self.assertRaisesRegex(RuntimeError, "durable knowledge"):
            command.downgrade(self.config, "20261026_24")


if __name__ == "__main__":
    unittest.main()
