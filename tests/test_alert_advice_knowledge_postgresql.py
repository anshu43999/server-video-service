from knowledge_support import helmet_mock_seed
import os
import unittest

from sqlalchemy import inspect

from app.alert_advice_knowledge import AlertAdviceKnowledgeStore, KnowledgeConflict
from app.database import Base, DatabaseManager
from app.system_alert_knowledge import SystemKnowledgeStore
from postgresql_support import isolated_postgresql_url


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "requires isolated PostgreSQL")
class KnowledgeWithoutLegacyTablesPostgresqlTest(unittest.TestCase):
    def test_health_and_system_draft_publication_do_not_require_legacy_tables(self):
        # Deliberately remove ONLY disposable test-schema tables; production migrations/data stay untouched.
        with isolated_postgresql_url("m41_no_legacy") as url:
            database = DatabaseManager(url)
            try:
                for name in ("alert_advice_knowledge_revisions", "alert_advice_knowledge_entries", "project_knowledge_bases"):
                    Base.metadata.tables[name].drop(database.engine)
                self.assertEqual("ready", database.verify_schema()["schema"])
                self.assertEqual("ok", database.health()["status"])
                self.assertNotIn("project_knowledge_bases", inspect(database.engine).get_table_names())
                system = SystemKnowledgeStore(database)
                reader = AlertAdviceKnowledgeStore(system=system)
                original = system.release(1)
                seed = helmet_mock_seed()
                created = system.mutate("create", "admin", entry_id="custom", alert_type_id="CUSTOM",
                                        recognition_category_id="HEAD", payload=seed["payload"])
                self.assertIsNone(reader.find_active_exact("a", "CUSTOM", "HEAD"))
                system.mutate("replace", "admin", entry_id=created["entryId"],
                              payload={**seed["payload"], "title": "System draft only"}, expected_revision=1)
                with self.assertRaises(KnowledgeConflict):
                    system.mutate("set_status", "admin", entry_id=created["entryId"], status="INACTIVE", expected_revision=1)
                system.publish(system.catalog()["revision"], "Publish without old tables", "admin")
                for project in ("a", "b"):
                    self.assertEqual("System draft only", reader.find_active_exact(project, "CUSTOM", "HEAD")["title"])
                system.mutate("set_status", "admin", entry_id="custom", status="INACTIVE", expected_revision=2)
                system.publish(system.catalog()["revision"], "Disable without old tables", "admin")
                self.assertIsNone(reader.find_active_exact("a", "CUSTOM", "HEAD"))
                self.assertEqual(original, system.release(1))
                self.assertEqual(["CREATE", "UPDATE", "DEACTIVATE"],
                                 [row["action"] for row in system.catalog()["history"]["custom"]])
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
