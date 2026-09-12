import hashlib
import json
import unittest
from pathlib import Path


class SceneModelRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.registry = json.loads((cls.root / "models" / "registry.json").read_text(encoding="utf-8"))
        cls.manifest = json.loads((cls.root / "models" / "site-intrusion-v1-manifest.json").read_text(encoding="utf-8"))

    def test_first_business_scene_has_frozen_five_label_order(self):
        self.assertEqual(self.manifest["modelId"], "site-intrusion-v1")
        self.assertEqual(self.manifest["labels"], ["bottle", "bag", "box", "tool", "person"])
        self.assertEqual(self.manifest["input"]["width"], 640)
        self.assertEqual(self.manifest["input"]["height"], 640)

    def test_registry_exposes_server_and_android_artifacts_as_a_pair(self):
        item = next(model for model in self.registry["models"] if model["modelId"] == "site-intrusion-v1")
        self.assertEqual(item["labels"], self.manifest["labels"])
        self.assertEqual({artifact["platform"] for artifact in item["artifacts"]}, {"server", "android"})
        self.assertTrue(all(artifact.get("placeholder") is True for artifact in item["artifacts"]))
        self.assertFalse(item["releaseEligible"])
        self.assertFalse(item["businessAccuracyValidated"])

    def test_placeholder_artifacts_match_registered_size_and_sha256(self):
        item = next(model for model in self.registry["models"] if model["modelId"] == "site-intrusion-v1")
        for artifact in item["artifacts"]:
            path = self.root / artifact["path"]
            self.assertTrue(path.is_file(), artifact["path"])
            self.assertEqual(path.stat().st_size, artifact["sizeBytes"])
            digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
            self.assertEqual(digest, artifact["sha256"])

    def test_android_manifest_keeps_same_identity_and_explicit_freeze(self):
        path = self.root.parent / "mobile-app" / "docs" / "models" / "site-intrusion-v1-business-placeholder-manifest.json"
        android = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(android["modelId"], self.manifest["modelId"])
        self.assertEqual(android["version"], self.manifest["version"])
        self.assertEqual(android["labels"], self.manifest["labels"])
        self.assertEqual(android["input"]["width"], self.manifest["input"]["width"])
        self.assertFalse(android["releaseEligible"])
        self.assertIn("占位", android["freezeReason"])
        android_artifact = self.root.parent / "mobile-app" / "local-models" / "android-assets" / "models" / "site-intrusion-v1-android.tflite"
        self.assertEqual(android_artifact.stat().st_size, android["modelFile"]["sizeBytes"])
        self.assertEqual(hashlib.sha256(android_artifact.read_bytes()).hexdigest().upper(), android["modelFile"]["sha256"])


if __name__ == "__main__":
    unittest.main()
