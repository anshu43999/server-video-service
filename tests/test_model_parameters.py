import copy
import copy
import json
import tempfile
import unittest
from pathlib import Path

from app.model_parameters import ModelParameterConflict, ModelParameterError, ModelParameterStore


ROOT = Path(__file__).resolve().parents[1]
MODEL = {
    "modelId": "helmet-test",
    "name": "helmet",
    "version": "1.0.0",
    "labels": ["head", "helmet", "person"],
}


class ModelParameterStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".test-convert")
        self.store = ModelParameterStore(Path(self.temp.name) / "parameter-profiles.json")

    def tearDown(self):
        self.temp.cleanup()

    def values(self):
        profile = self.store.default_profile(MODEL, "android")
        return {"detection": profile["detection"], "alertRules": profile["alertRules"]}

    def test_default_profile_maps_head_to_no_helmet_presence_alert(self):
        profile = self.store.get(MODEL, "android")
        head = next(rule for rule in profile["alertRules"] if rule["rawLabel"] == "head")
        self.assertEqual(profile["schemaVersion"], 2)
        self.assertEqual(profile["source"], "default")
        self.assertEqual(profile["revision"], 0)
        self.assertFalse(self.store.path.exists())
        self.assertEqual(head["displayName"], "未佩戴安全帽")
        self.assertEqual(head["eventCode"], "PPE_NO_HELMET")
        self.assertEqual(head["operator"], "PRESENCE")
        self.assertTrue(head["enabled"])
        self.assertEqual(head["image"], {"minimumConfidence": 0.55, "cooldownMs": 60000})
        self.assertEqual(head["camera"]["minimumConsecutiveFrames"], 4)
        self.assertEqual(head["minimumConfidence"], 0.55)

    def test_save_is_versioned_audited_and_persistent(self):
        values = self.values()
        values["detection"]["confidenceThreshold"] = 0.4
        values["alertRules"][0]["minimumConfidence"] = 0.6
        saved = self.store.save(MODEL, "android", values, "operator-1", 0)
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(saved["source"], "custom")
        self.assertEqual(saved["audit"][0]["action"], "UPDATED")
        loaded = ModelParameterStore(self.store.path).get(MODEL, "android")
        self.assertEqual(loaded["detection"]["confidenceThreshold"], 0.4)
        self.assertEqual(loaded["updatedBy"], "operator-1")
        with self.assertRaises(ModelParameterConflict):
            self.store.save(MODEL, "android", values, "operator-2", 0)

    def test_reset_restores_defaults_without_losing_revision_history(self):
        saved = self.store.save(MODEL, "server", self.values(), "operator-1", 0)
        reset = self.store.reset(MODEL, "server", "operator-2")
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(reset["revision"], 2)
        self.assertEqual(reset["source"], "default")
        self.assertEqual([item["action"] for item in reset["audit"]], ["UPDATED", "RESET"])

    def test_rejects_missing_labels_and_alert_confidence_below_detection(self):
        missing = self.values()
        missing["alertRules"].pop()
        with self.assertRaisesRegex(ModelParameterError, "every model label"):
            self.store.save(MODEL, "android", missing, "operator", 0)

        too_low = copy.deepcopy(self.values())
        too_low["detection"]["confidenceThreshold"] = 0.7
        with self.assertRaisesRegex(ModelParameterError, "cannot be lower"):
            self.store.save(MODEL, "android", too_low, "operator", 0)

    def test_v1_values_are_migrated_to_scene_specific_v2_on_save(self):
        legacy = self.values()
        legacy_confidence = legacy["alertRules"][0]["image"]["minimumConfidence"]
        saved = self.store.save(MODEL, "android", copy.deepcopy(legacy), "operator", 0)
        stored = self.store._load()["profiles"][self.store._profile_key(MODEL, "android")]
        rule = stored["alertRules"][0]
        self.assertEqual(stored["schemaVersion"], 2)
        self.assertEqual(rule["image"]["minimumConfidence"], legacy_confidence)
        self.assertNotIn("minimumConfidence", rule)
        saved_rule = saved["alertRules"][0]
        self.assertEqual(saved_rule["minimumConfidence"], rule["camera"]["minimumConfidence"])

    def test_existing_v1_profile_is_read_without_rewriting_the_file(self):
        payload = {
            "schemaVersion": 1,
            "profiles": {self.store._profile_key(MODEL, "android"): {
                **self.store.default_profile(MODEL, "android"),
                "schemaVersion": 1,
                "alertRules": [{
                    **self.store.default_profile(MODEL, "android")["alertRules"][0],
                    "minimumConfidence": 0.6,
                    "minimumConsecutiveFrames": 3,
                    "minimumDwellTimeMs": 500,
                    "cooldownMs": 1000,
                }],
            }},
            "audit": [],
        }
        for default_rule in self.store.default_profile(MODEL, "android")["alertRules"][1:]:
            payload["profiles"][self.store._profile_key(MODEL, "android")]["alertRules"].append({
                **{key: value for key, value in default_rule.items() if key not in {"image", "camera"}},
                "minimumConfidence": 0.55,
                "minimumConsecutiveFrames": 4,
                "minimumDwellTimeMs": 800,
                "cooldownMs": 60000,
            })
        self.store.path.write_text(json.dumps(payload), encoding="utf-8")
        before = self.store.path.read_text(encoding="utf-8")
        profile = self.store.get(MODEL, "android")
        self.assertEqual(profile["schemaVersion"], 2)
        self.assertEqual(profile["alertRules"][0]["image"]["cooldownMs"], 1000)
        self.assertEqual(profile["alertRules"][0]["camera"]["minimumConsecutiveFrames"], 3)
        self.assertEqual(self.store.path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
