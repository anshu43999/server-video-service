import copy
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import select

from app.alert_advice_knowledge import AlertAdviceKnowledgeStore, KnowledgeConflict
from app.alert_advice_generation import AlertAdviceGenerationStore
from app.alert_advice_service import AlertAdviceService, MockKnowledgeRetriever, MockAdviceGenerator
from app.alerts.disposition import AlertDispositionStore
from app.database import DatabaseManager, ProjectRecord, ProjectKnowledgeBaseRecord
from app.system_alert_knowledge import SystemKnowledgeStore
from postgresql_support import isolated_postgresql_url
from knowledge_support import add_legacy_knowledge, assert_legacy_knowledge


@unittest.skipUnless(os.getenv("RUN_POSTGRES_TESTS") == "1", "requires isolated PostgreSQL")
class SystemAlertKnowledgePostgreSQLTests(unittest.TestCase):
    def test_global_publication_preserves_legacy_rows_and_serializes_cas(self):
        with isolated_postgresql_url("system_knowledge") as url:
            database = DatabaseManager(url)
            try:
                with database.session() as session:
                    legacy = session.scalar(select(ProjectRecord).where(ProjectRecord.project_code == "legacy-default"))
                    legacy_id = legacy.project_id
                    self.assertEqual(1, session.get(ProjectKnowledgeBaseRecord, legacy_id).version)
                    new_id = str(uuid.uuid4())
                    session.add(ProjectRecord(project_id=new_id, project_code="global-pg-new", display_name="Global PG New"))
                system = SystemKnowledgeStore(database)
                projects = AlertAdviceKnowledgeStore(system=system)
                original = system.release(1)
                events = AlertDispositionStore(database)
                event = {"eventId": "shared-knowledge-event", "projectId": legacy_id,
                         "alertTypeId": "PPE_NO_HELMET", "recognitionCategoryId": "HEAD"}
                events.register(event, project_id=legacy_id)
                generated = AlertAdviceService(MockKnowledgeRetriever(projects), MockAdviceGenerator()).generate(legacy_id, event)
                frozen, _ = AlertAdviceGenerationStore(database).create(
                    legacy_id, event["eventId"], "admin", str(uuid.uuid4()), None, generated)
                source = projects.find_active_exact(legacy_id, "PPE_NO_HELMET", "HEAD")
                payload = {key: copy.deepcopy(source[key]) for key in (
                    "title", "riskDescription", "adviceTemplate", "references", "applicability", "sourceType")}
                legacy_snapshot = add_legacy_knowledge(database, legacy_id, payload)
                payload["title"] = "Shared system change"
                system.mutate("replace", "admin", entry_id=source["sourceEntryId"], payload=payload, expected_revision=1)
                self.assertEqual(source, projects.find_active_exact(legacy_id, "PPE_NO_HELMET", "HEAD"))
                revision = system.catalog()["revision"]
                barrier = Barrier(2)
                def publish():
                    peer = SystemKnowledgeStore(database)
                    barrier.wait(timeout=10)
                    try:
                        return peer.publish(revision, "Concurrent global publish", "admin")["version"]
                    except KnowledgeConflict:
                        return "conflict"
                with ThreadPoolExecutor(max_workers=2) as pool:
                    outcomes = list(pool.map(lambda _: publish(), range(2)))
                self.assertCountEqual([2, "conflict"], outcomes)
                for project_id in (legacy_id, new_id):
                    entry = projects.find_active_exact(project_id, "PPE_NO_HELMET", "HEAD")
                    self.assertEqual(("SYSTEM", 2, "Shared system change"),
                                     (entry["origin"], entry["systemVersion"], entry["title"]))
                    self.assertFalse(hasattr(projects, "replace"))
                with database.session() as session:
                    self.assertEqual(1, session.get(ProjectKnowledgeBaseRecord, legacy_id).version)
                    self.assertIsNone(session.get(ProjectKnowledgeBaseRecord, new_id))
                assert_legacy_knowledge(self, database, legacy_id, legacy_snapshot)
                self.assertEqual(original, system.release(1))
                system.mutate("set_status", "admin", entry_id=source["sourceEntryId"], status="INACTIVE", expected_revision=2)
                self.assertIsNotNone(projects.find_active_exact(new_id, "PPE_NO_HELMET", "HEAD"))
                system.publish(system.catalog()["revision"], "Disable globally", "admin")
                reopened_db = DatabaseManager(url)
                try:
                    reopened_system = SystemKnowledgeStore(reopened_db)
                    reopened = AlertAdviceKnowledgeStore(system=reopened_system)
                    for project_id in (legacy_id, new_id):
                        self.assertIsNone(reopened.find_active_exact(project_id, "PPE_NO_HELMET", "HEAD"))
                        self.assertEqual(3, reopened.list(project_id)[0]["systemVersion"])
                    self.assertEqual(original, reopened_system.release(1))
                    saved = AlertAdviceGenerationStore(reopened_db).get(legacy_id, event["eventId"], frozen["generationId"])
                    self.assertEqual(frozen, saved)
                    self.assertEqual(1, saved["systemKnowledgeVersion"])
                    assert_legacy_knowledge(self, reopened_db, legacy_id, legacy_snapshot)
                finally:
                    reopened_db.close()
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
