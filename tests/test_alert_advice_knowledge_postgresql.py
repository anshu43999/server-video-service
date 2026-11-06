import copy
import os
import unittest
import uuid

from sqlalchemy import inspect

from app.alert_advice_knowledge import (
    INACTIVE,
    AlertAdviceKnowledgeStore,
    KnowledgeConflict,
    helmet_mock_seed,
)
from app.database import DatabaseManager, ProjectRecord
from postgresql_support import isolated_postgresql_url


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "set RUN_POSTGRES_TESTS=1 for PostgreSQL integration")
class AlertAdviceKnowledgePostgresqlTest(unittest.TestCase):
    def test_migration_cas_revision_and_project_isolation(self):
        with isolated_postgresql_url("m41_advice") as url:
            database = DatabaseManager(url)
            try:
                tables = set(inspect(database.engine).get_table_names())
                self.assertIn("alert_advice_knowledge_entries", tables)
                self.assertIn("alert_advice_knowledge_revisions", tables)
                project_a = str(uuid.uuid4())
                project_b = str(uuid.uuid4())
                with database.session() as session:
                    session.add_all([
                        ProjectRecord(project_id=project_a, project_code="m41-a", display_name="M41 A"),
                        ProjectRecord(project_id=project_b, project_code="m41-b", display_name="M41 B"),
                    ])
                store = AlertAdviceKnowledgeStore(database)
                first, created = store.ensure_mock_seed(project_a)
                self.assertTrue(created)
                other, other_created = store.ensure_mock_seed(project_b)
                self.assertTrue(other_created)
                self.assertNotEqual(first["projectId"], other["projectId"])

                stale_store = AlertAdviceKnowledgeStore(DatabaseManager(url))
                try:
                    stale = stale_store.get(project_a, first["entryId"])
                    changed = store.set_status(project_a, first["entryId"], INACTIVE, "owner", first["revision"])
                    self.assertEqual(2, changed["revision"])
                    payload = copy.deepcopy(helmet_mock_seed()["payload"])
                    with self.assertRaises(KnowledgeConflict):
                        stale_store.replace(project_a, first["entryId"], payload, "stale", stale["revision"])
                finally:
                    stale_store.database.close()

                revisions = store.revisions(project_a, first["entryId"])
                self.assertEqual([1, 2], [row["revision"] for row in revisions])
                self.assertEqual(["CREATE", "DEACTIVATE"], [row["action"] for row in revisions])
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
