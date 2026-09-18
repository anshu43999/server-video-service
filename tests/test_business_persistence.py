import json
import tempfile
import unittest
import uuid
from pathlib import Path

from app.alerts.rules import RuleRegistry
from app.database import Base, DatabaseManager
from app.model_parameters import ModelParameterConflict, ModelParameterStore


ROOT = Path(__file__).resolve().parents[1]
MODEL = {"modelId": "helmet-db", "name": "helmet", "version": "1.0.0", "labels": ["head", "helmet"]}


class BusinessPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".test-db")
        self.path = Path(self.temp.name) / "business.db"
        self.database = DatabaseManager(f"sqlite+pysqlite:///{self.path.as_posix()}")
        Base.metadata.create_all(self.database.engine)

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def test_rules_bindings_and_audits_survive_recreation(self):
        registry = RuleRegistry(self.database)
        rule = {"ruleId": "ppe-head", "name": "未佩戴安全帽", "operator": "PRESENCE",
                "subjectKind": "frame", "requires": ["BOX"]}
        self.assertEqual(registry.upsert(rule, actor="one")["ruleVersion"], 1)
        self.assertTrue(registry.bind("ppe-head", "camera:1", ["BOX"], actor="two")["accepted"])
        self.assertEqual(registry.upsert({**rule, "enabled": False}, actor="three")["ruleVersion"], 2)

        reopened = RuleRegistry(DatabaseManager(self.database.url))
        self.assertFalse(reopened.get("ppe-head")["enabled"])
        self.assertEqual(len(reopened.bindings("ppe-head")), 1)
        self.assertEqual([item["action"] for item in reopened.audits("ppe-head")], ["create", "bind", "update"])
        reopened._database.close()

    def test_model_profile_revision_and_audit_survive_recreation(self):
        store = ModelParameterStore(Path(self.temp.name) / "missing.json", self.database)
        profile = store.default_profile(MODEL, "android")
        values = {"detection": profile["detection"], "alertRules": profile["alertRules"]}
        saved = store.save(MODEL, "android", values, "operator", 0)
        self.assertEqual(saved["revision"], 1)
        with self.assertRaises(ModelParameterConflict):
            store.save(MODEL, "android", values, "stale", 0)

        reopened_database = DatabaseManager(self.database.url)
        reopened = ModelParameterStore(Path(self.temp.name) / "missing.json", reopened_database)
        loaded = reopened.get(MODEL, "android")
        self.assertEqual(loaded["revision"], 1)
        self.assertEqual(loaded["audit"][0]["actor"], "operator")
        reopened_database.close()

    def test_legacy_json_import_is_idempotent(self):
        path = Path(self.temp.name) / "legacy.json"
        file_store = ModelParameterStore(path)
        default = file_store.default_profile(MODEL, "android")
        values = {"detection": default["detection"], "alertRules": default["alertRules"]}
        file_store.save(MODEL, "android", values, "legacy", 0)

        first = ModelParameterStore(path, self.database)
        self.assertEqual(first.get(MODEL, "android")["revision"], 1)
        second = ModelParameterStore(path, self.database)
        self.assertEqual(second.get(MODEL, "android")["revision"], 1)


if __name__ == "__main__":
    unittest.main()
