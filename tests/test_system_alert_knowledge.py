import copy
import unittest
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.alert_advice_knowledge import ACTIVE, INACTIVE, KnowledgeConflict
from app.alert_advice_service import MockAdviceGenerator, MockKnowledgeRetriever, AlertAdviceService
from app.alert_advice_knowledge import AlertAdviceKnowledgeStore
from app.system_alert_knowledge import SystemKnowledgeStore
from app.database import DatabaseManager, ProjectRecord
from unittest.mock import patch
from project_api_support import ProjectApiSupport
import app.main as main_module


class SystemAlertKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.system = SystemKnowledgeStore()
        self.projects = AlertAdviceKnowledgeStore(system=self.system)
        self.project_a = "project-a"
        self.project_b = "project-b"
        self.system.pin_new_memory_project(self.project_a)
        self.system.pin_new_memory_project(self.project_b)

    def test_published_release_is_immutable_and_upgrade_is_explicit(self):
        original = self.system.release(1)
        item = self.system.catalog()["entries"][0]
        payload = copy.deepcopy(item)
        self.system.mutate("replace", "admin", entry_id=item["entryId"], payload={key: payload[key] for key in (
            "title", "riskDescription", "adviceTemplate", "references", "applicability", "sourceType")},
            expected_revision=item["revision"])
        release = self.system.publish(self.system.catalog()["revision"], "Updated base", "admin")
        self.assertEqual(2, release["version"])
        self.assertEqual(original, self.system.release(1))
        self.assertEqual(1, self.system.binding(self.project_a)["version"])
        self.system.adopt(self.project_a, 2, 1, "owner")
        self.assertEqual(2, self.system.binding(self.project_a)["version"])
        self.assertEqual(1, self.system.binding(self.project_b)["version"])
        with self.assertRaises(KnowledgeConflict):
            self.system.adopt(self.project_a, 2, 1, "owner")

    def test_project_override_and_inactive_tombstone_never_fall_back(self):
        inherited = self.projects.find_active_exact(self.project_a, "PPE_NO_HELMET", "HEAD")
        self.assertEqual("SYSTEM", inherited["origin"])
        payload = {key: inherited[key] for key in ("title", "riskDescription", "adviceTemplate", "references", "applicability", "sourceType")}
        payload["title"] = "Project-only override"
        override = self.projects.override(self.project_a, inherited["entryId"], payload, ACTIVE, "owner", inherited["baseRevision"])
        self.assertEqual("PROJECT_OVERRIDE", self.projects.find_active_exact(self.project_a, "PPE_NO_HELMET", "HEAD")["origin"])
        self.projects.set_status(self.project_a, override["entryId"], INACTIVE, "owner", 1)
        self.assertIsNone(self.projects.find_active_exact(self.project_a, "PPE_NO_HELMET", "HEAD"))
        other = self.projects.find_active_exact(self.project_b, "PPE_NO_HELMET", "HEAD")
        self.assertEqual("SYSTEM", other["origin"])
        self.assertEqual("PPE_NO_HELMET", other["matchKey"]["alertTypeId"])

    def test_advice_records_system_source_and_version(self):
        service = AlertAdviceService(MockKnowledgeRetriever(self.projects), MockAdviceGenerator())
        result = service.generate(self.project_a, {"eventId": "event-1", "ruleId": "PPE_NO_HELMET", "label": "head"})
        self.assertEqual("GENERATED", result["status"])
        self.assertEqual("SYSTEM", result["knowledgeOrigin"])
        self.assertEqual(1, result["systemKnowledgeVersion"])

    def test_project_entry_id_with_system_prefix_remains_a_local_entry(self):
        seed = self.projects.system.release(1)["entries"][0]
        local = self.projects.create(self.project_a, "system:local-custom", "CUSTOM_ALERT", "CUSTOM_CATEGORY",
                                     {key: copy.deepcopy(seed[key]) for key in (
                                         "title", "riskDescription", "adviceTemplate", "references", "applicability", "sourceType")},
                                     "owner")
        self.assertEqual(local["entryId"], self.projects.get(self.project_a, local["entryId"])["entryId"])
        history = self.projects.revisions(self.project_a, local["entryId"])
        self.assertEqual("CREATE", history[0]["action"])

    def test_persistent_store_pins_existing_projects_and_migration_protects_releases(self):
        root = Path(__file__).resolve().parents[1]
        (root / ".test-db").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root / ".test-db") as folder:
            url = f"sqlite+pysqlite:///{Path(folder, 'system-knowledge.db').as_posix()}"
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
            command.upgrade(config, "head")
            database = DatabaseManager(url)
            try:
                with database.session() as session:
                    project = session.scalar(select(ProjectRecord).where(ProjectRecord.project_code == "legacy-default"))
                    self.assertIsNotNone(project)
                    binding = self.system.__class__(database).binding(project.project_id)
                    self.assertEqual({"version": 1, "revision": 1}, binding)
            finally:
                database.close()
            with self.assertRaisesRegex(RuntimeError, "immutable releases"):
                command.downgrade(config, "20261104_33")


class SystemAlertKnowledgeApiTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        self.start_project_api("system-advice-api")
        self.system = SystemKnowledgeStore()
        self.system.pin_new_memory_project(self.project_id)
        self.store = AlertAdviceKnowledgeStore(system=self.system)
        self._project_isolation.enter_context(patch.object(main_module, "alert_advice_knowledge_store", self.store))
        self.project_base = f"{self.project_path}/alert-advice"
        self.platform_base = "/aiyoloapi/platform/alert-advice"

    def test_platform_publish_project_upgrade_override_and_inactive_mask(self):
        system_headers = self.client.get(self.platform_base + "/knowledge-entries", headers=self.headers)
        self.assertEqual(200, system_headers.status_code, system_headers.text)
        entries = system_headers.json()["entries"]
        self.assertEqual(5, len(entries))
        self.assertEqual(201, self.client.post(self.platform_base + "/publish", headers=self.headers,
                         json={"expectedRevision": system_headers.json()["revision"], "notes": "API V2"}).status_code)
        current = self.client.get(self.project_base + "/base", headers=self.headers).json()
        self.assertEqual(1, current["version"])
        upgraded = self.client.post(self.project_base + "/base/upgrade", headers=self.headers,
                                    json={"version": 2, "expectedRevision": current["revision"]})
        self.assertEqual(200, upgraded.status_code, upgraded.text)
        inherited = next(item for item in self.client.get(self.project_base + "/knowledge-entries", headers=self.headers).json()["entries"]
                         if item["matchKey"] == {"alertTypeId": "PPE_NO_HELMET", "recognitionCategoryId": "HEAD"})
        masked = self.client.post(self.project_base + "/knowledge-overrides", headers=self.headers, json={
            **{key: inherited[key] for key in ("title", "riskDescription", "adviceTemplate", "references", "applicability", "sourceType")},
            "inheritedEntryId": inherited["entryId"], "expectedBaseRevision": upgraded.json()["revision"], "status": "INACTIVE",
        })
        self.assertEqual(201, masked.status_code, masked.text)
        preview = self.client.post(self.project_base + "/knowledge-entries/match-preview", headers=self.headers,
                                   json={"alertTypeId": "PPE_NO_HELMET", "recognitionCategoryId": "HEAD"})
        self.assertFalse(preview.json()["matched"])
        self.assertEqual("SYSTEM", self.client.get(self.platform_base + "/knowledge-entries", headers=self.headers).json()["entries"][0]["origin"])

    def test_system_catalog_requires_platform_admin(self):
        account = self.client.post("/aiyoloapi/platform/accounts", headers=self.headers,
                                   json={"username": "system-knowledge-user", "password": "temporary-user-password", "platformRole": "NORMAL_USER"})
        self.assertEqual(201, account.status_code, account.text)
        login = self.client.post("/aiyoloapi/auth/login", json={"username": "system-knowledge-user", "password": "temporary-user-password"})
        self.assertEqual(200, login.status_code, login.text)
        user_headers = {"Authorization": "Bearer " + login.json()["accessToken"]}
        denied = self.client.get(self.platform_base + "/knowledge-entries", headers=user_headers)
        self.assertEqual(403, denied.status_code, denied.text)


if __name__ == "__main__":
    unittest.main()
