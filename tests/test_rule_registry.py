import unittest

from app.alerts.rules import RuleRegistry, RuleValidationError


class RuleRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = RuleRegistry()

    def rule(self, **extra):
        value = {"ruleId": "r-1", "name": "区域入侵", "operator": "IN_REGION", "subjectKind": "track", "requires": ["BOX"], "thresholds": {"minConfidence": .5}}
        value.update(extra)
        return value

    def test_runtime_crud_versions_and_audit(self):
        self.assertEqual(self.registry.upsert(self.rule())["ruleVersion"], 1)
        self.assertEqual(self.registry.upsert(self.rule(thresholds={"minConfidence": .7}))["ruleVersion"], 2)
        self.registry.delete("r-1")
        self.assertEqual([row["action"] for row in self.registry.audits()], ["create", "update", "delete"])

    def test_binding_rejects_missing_capability_explicitly(self):
        self.registry.upsert(self.rule())
        result = self.registry.bind("r-1", "camera-1", ["TRACK"])
        self.assertFalse(result["accepted"])
        self.assertEqual(result["code"], "CAPABILITY_UNSATISFIED")
        self.assertEqual(result["missing"], ["BOX"])
        self.assertEqual(self.registry.bindings("r-1")[0]["accepted"], False)

    def test_validate_is_dry_run_and_success_bind_is_audited(self):
        self.registry.upsert(self.rule())
        result = self.registry.check("r-1", "camera-1", ["BOX"])
        self.assertTrue(result["accepted"])
        self.assertEqual(len(self.registry.audits()), 1)
        result = self.registry.bind("r-1", "camera-1", ["BOX"], model_id="model-a")
        self.assertTrue(result["accepted"])
        self.assertEqual(len(self.registry.audits()), 2)

    def test_unknown_capability_is_rejected(self):
        with self.assertRaises(RuleValidationError):
            self.registry.upsert(self.rule(requires=["DEPTH"]))


if __name__ == "__main__":
    unittest.main()
