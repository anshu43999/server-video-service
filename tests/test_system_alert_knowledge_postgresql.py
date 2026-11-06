import copy
import unittest
import uuid

from sqlalchemy import select

from app.alert_advice_knowledge import AlertAdviceKnowledgeStore
from app.database import DatabaseManager, ProjectRecord
from app.system_alert_knowledge import SystemKnowledgeStore, pin_new_project
from postgresql_support import isolated_postgresql_url


class SystemAlertKnowledgePostgreSQLTests(unittest.TestCase):
    def test_migrated_project_inheritance_publication_and_masking(self):
        with isolated_postgresql_url("system_knowledge") as url:
            database = DatabaseManager(url)
            try:
                project_id = str(uuid.uuid4())
                with database.session() as session:
                    session.add(ProjectRecord(project_id=project_id, project_code="system-pg-test", display_name="System PG Test"))
                    session.flush()
                    pin_new_project(session, project_id)
                system = SystemKnowledgeStore(database)
                projects = AlertAdviceKnowledgeStore(database, system=system)
                binding = system.binding(project_id)
                self.assertEqual({"version": 1, "revision": 1}, binding)
                item = projects.find_active_exact(project_id, "PPE_NO_HELMET", "HEAD")
                self.assertEqual("SYSTEM", item["origin"])
                payload = {key: copy.deepcopy(item[key]) for key in (
                    "title", "riskDescription", "adviceTemplate", "references", "applicability", "sourceType")}
                payload["title"] = "PG project override"
                override = projects.override(project_id, item["entryId"], payload, "INACTIVE", "pg-owner", 1)
                self.assertEqual("INACTIVE", override["status"])
                self.assertIsNone(projects.find_active_exact(project_id, "PPE_NO_HELMET", "HEAD"))
                catalog = system.catalog()
                system.publish(catalog["revision"], "PG publish", "pg-admin")
                self.assertEqual(1, system.binding(project_id)["version"])
                self.assertEqual("PG project override", projects.get(project_id, override["entryId"])["title"])
                next_project = str(uuid.uuid4())
                with database.session() as session:
                    session.add(ProjectRecord(project_id=next_project, project_code="system-pg-new", display_name="System PG New"))
                    session.flush()
                    pin_new_project(session, next_project)
                self.assertEqual({"version": 2, "revision": 1}, system.binding(next_project))
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
