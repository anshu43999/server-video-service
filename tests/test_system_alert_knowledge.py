import copy
import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.alert_advice_knowledge import AlertAdviceKnowledgeStore, KnowledgeConflict, KnowledgeNotFound
from app.alert_advice_service import AlertAdviceService, MockAdviceGenerator, MockKnowledgeRetriever
from app.database import DatabaseManager, ProjectRecord, ProjectKnowledgeBaseRecord
from app.system_alert_knowledge import SystemKnowledgeStore


def payload(entry):
    return {key: copy.deepcopy(entry[key]) for key in (
        "title", "riskDescription", "adviceTemplate", "references", "applicability", "sourceType")}


class SystemAlertKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.system = SystemKnowledgeStore()
        self.projects = AlertAdviceKnowledgeStore(system=self.system)

    def test_one_publication_updates_every_project_without_a_binding(self):
        original = self.system.release(1)
        first = self.projects.find_active_exact("project-a", "PPE_NO_HELMET", "HEAD")
        item = self.system.catalog()["entries"][0]
        replacement = payload(item)
        replacement["title"] = "System revision shared by every project"
        self.system.mutate("replace", "admin", entry_id=item["entryId"], payload=replacement, expected_revision=1)
        self.assertEqual(first, self.projects.find_active_exact("project-a", "PPE_NO_HELMET", "HEAD"))
        self.system.publish(self.system.catalog()["revision"], "Publish globally", "admin")
        for project_id in ("project-a", "project-b", "new-project"):
            rows = self.projects.list(project_id)
            self.assertTrue(all(row["systemVersion"] == 2 and row["projectId"] == project_id for row in rows))
            changed = self.projects.get(project_id, "system:" + item["entryId"])
            self.assertEqual(replacement["title"], changed["title"])
            self.assertNotIn("baseRevision", changed)
        self.assertEqual(original, self.system.release(1))
        with self.assertRaises(KnowledgeConflict):
            self.system.publish(1, "Stale publication", "admin")

    def test_old_project_material_never_masks_or_leaks_into_system_results(self):
        original = self.projects.find_active_exact("project-a", "PPE_NO_HELMET", "HEAD")
        with self.assertRaises(KnowledgeNotFound):
            self.projects.get("project-a", "legacy-private")
        source_id = original["sourceEntryId"]
        self.system.mutate("set_status", "admin", entry_id=source_id, status="INACTIVE", expected_revision=1)
        self.assertIsNotNone(self.projects.find_active_exact("project-a", "PPE_NO_HELMET", "HEAD"))
        self.system.publish(self.system.catalog()["revision"], "Disable globally", "admin")
        for project_id in ("project-a", "project-b"):
            self.assertIsNone(self.projects.find_active_exact(project_id, "PPE_NO_HELMET", "HEAD"))

    def test_project_store_rejects_writes_and_published_history_hides_drafts(self):
        entry = self.projects.list("project-a")[0]
        for name in ("create", "replace", "set_status", "local_list", "ensure_mock_seed"):
            self.assertFalse(hasattr(self.projects, name))
        changed = payload(entry)
        changed["title"] = "Unpublished confidential draft"
        self.system.mutate("replace", "admin", entry_id=entry["sourceEntryId"], payload=changed, expected_revision=1)
        history = self.projects.revisions("project-a", entry["entryId"])
        self.assertEqual("PUBLISHED", history[0]["action"])
        self.assertEqual(1, history[0]["revision"])
        self.assertNotIn(changed["title"], str(history))

    def test_new_advice_uses_shared_version_without_changing_an_old_snapshot(self):
        service = AlertAdviceService(MockKnowledgeRetriever(self.projects), MockAdviceGenerator())
        event = {"eventId": "event-1", "ruleId": "PPE_NO_HELMET", "label": "head"}
        old = service.generate("project-a", event)
        frozen = copy.deepcopy(old)
        self.system.publish(self.system.catalog()["revision"], "Next system release", "admin")
        new = service.generate("project-b", event)
        self.assertEqual("SYSTEM", new["knowledgeOrigin"])
        self.assertEqual(2, new["systemKnowledgeVersion"])
        self.assertEqual(frozen, old)
        self.assertEqual(1, old["systemKnowledgeVersion"])

    def test_persistent_reads_ignore_legacy_pin_without_deleting_history(self):
        root = Path(__file__).resolve().parents[1]
        (root / ".test-db").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root / ".test-db") as folder:
            url = "sqlite+pysqlite:///" + Path(folder, "knowledge.db").as_posix()
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
            command.upgrade(config, "head")
            database = DatabaseManager(url)
            try:
                with database.session() as session:
                    project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_code == "legacy-default"))
                    project_id = project.project_id
                    self.assertEqual(1, session.get(ProjectKnowledgeBaseRecord, project_id).version)
                system = SystemKnowledgeStore(database)
                store = AlertAdviceKnowledgeStore(system=system)
                system.publish(system.catalog()["revision"], "All projects share V2", "admin")
                self.assertEqual(2, store.list(project_id)[0]["systemVersion"])
                with database.session() as session:
                    self.assertEqual(1, session.get(ProjectKnowledgeBaseRecord, project_id).version)
                self.assertEqual(1, system.release(1)["version"])
            finally:
                database.close()
            with self.assertRaisesRegex(RuntimeError, "immutable releases"):
                command.downgrade(config, "20261104_33")
