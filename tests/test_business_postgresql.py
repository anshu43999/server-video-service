import os
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import delete

from app.alerts.rules import RuleRegistry
from app.config import settings
from app.database import (
    AlertRuleAuditRecord,
    AlertRuleRecord,
    DatabaseManager,
    ModelParameterProfileRecord,
)
from app.model_parameters import ModelParameterConflict, ModelParameterStore


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "set RUN_POSTGRES_TESTS=1 for PostgreSQL integration")
class BusinessPostgreSqlTests(unittest.TestCase):
    def test_rules_and_model_parameters_survive_and_serialize_revision_updates(self):
        suffix = uuid.uuid4().hex
        rule_id = f"rule-{suffix}"
        model = {"modelId": f"model-{suffix}", "name": "test", "version": "1", "labels": ["head"]}
        profile_key = ModelParameterStore._database_key_for_model(model, "android")
        database = DatabaseManager(settings.database_url)
        try:
            registry = RuleRegistry(database)
            registry.upsert({"ruleId": rule_id, "operator": "PRESENCE", "subjectKind": "frame"})
            registry.bind(rule_id, "camera:test", ["BOX"])
            database.close()

            reopened = DatabaseManager(settings.database_url)
            self.assertEqual(RuleRegistry(reopened).get(rule_id)["bindings"]["camera:test"]["accepted"], True)
            store = ModelParameterStore(Path("missing-legacy.json"), reopened)
            default = store.default_profile(model, "android")
            values = {"detection": default["detection"], "alertRules": default["alertRules"]}
            store.save(model, "android", values, "seed", 0)
            reopened.close()

            def update(actor):
                manager = DatabaseManager(settings.database_url)
                try:
                    candidate = ModelParameterStore(Path("missing-legacy.json"), manager)
                    return candidate.save(model, "android", values, actor, 1)["revision"]
                except ModelParameterConflict:
                    return "conflict"
                finally:
                    manager.close()

            with ThreadPoolExecutor(max_workers=2) as workers:
                outcomes = list(workers.map(update, ["one", "two"]))
            self.assertEqual(sorted(outcomes, key=str), [2, "conflict"])
        finally:
            cleanup = DatabaseManager(settings.database_url)
            with cleanup.session() as session:
                session.execute(delete(ModelParameterProfileRecord).where(
                    ModelParameterProfileRecord.profile_key == profile_key
                ))
                session.execute(delete(AlertRuleRecord).where(AlertRuleRecord.rule_id == rule_id))
                session.execute(delete(AlertRuleAuditRecord).where(AlertRuleAuditRecord.rule_id == rule_id))
            cleanup.close()


if __name__ == "__main__":
    unittest.main()
