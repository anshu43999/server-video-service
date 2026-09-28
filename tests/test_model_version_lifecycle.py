import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.model_catalog import ModelCatalog


def _artifact(path: Path, artifact_id: str) -> dict:
    return {
        "artifactId": artifact_id,
        "format": "pt",
        "platform": "server",
        "path": f"models/{path.parent.name}/{path.name}",
        "sizeBytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
    }


def _release(model_id: str, version: str, path: Path, *, status: str = "PUBLISHED") -> dict:
    return {
        "modelId": model_id,
        "name": f"{model_id} {version}",
        "version": version,
        "scenario": "intrusion",
        "purpose": "business",
        "runtime": "server-pt",
        "format": "pt",
        "path": f"models/{path.parent.name}/{path.name}",
        "sizeBytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
        "labels": ["person"],
        "releaseEligible": status == "PUBLISHED",
        "status": status,
        "artifacts": [_artifact(path, "server-pt")],
    }


class ModelVersionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        models = root / "models"
        (models / "v1").mkdir(parents=True)
        (models / "v2").mkdir(parents=True)
        self.v1 = models / "v1" / "model.pt"
        self.v2 = models / "v2" / "model.pt"
        self.v1.write_bytes(b"version-one")
        self.v2.write_bytes(b"version-two")
        self.registry = models / "registry.json"
        self.registry.write_text(json.dumps({
            "activeServerModel": "vision",
            "models": [
                _release("vision", "1.0.0", self.v1),
                _release("vision", "2.0.0", self.v2),
            ],
        }), encoding="utf-8")
        self.catalog = ModelCatalog(self.registry)

    def tearDown(self):
        self.temp.cleanup()

    def test_multiple_versions_choose_highest_published_and_expose_history(self):
        versions = self.catalog.versions("vision")
        self.assertEqual([item["version"] for item in versions], ["2.0.0", "1.0.0"])
        self.assertEqual(self.catalog.get("vision")["version"], "2.0.0")
        self.assertEqual(self.catalog.get("vision")["latestVersion"], "2.0.0")
        self.assertTrue(self.catalog.get("vision", "2.0.0")["isLatest"])

    def test_version_level_uninstall_keeps_other_release_and_writes_tombstone(self):
        result = self.catalog.uninstall("vision", "1.0.0")
        self.assertEqual(result["version"], "1.0.0")
        self.assertFalse(self.v1.exists())
        self.assertTrue(self.v2.exists())
        payload = json.loads(self.registry.read_text(encoding="utf-8"))
        self.assertEqual([item["version"] for item in payload["models"]], ["2.0.0"])
        self.assertEqual(payload["modelHistory"][-1]["status"], "UNINSTALLED")

    def test_legacy_uninstall_requires_version_for_multiple_releases(self):
        with self.assertRaisesRegex(ValueError, "version required"):
            self.catalog.uninstall("vision")

    def test_active_release_is_protected_but_deprecation_is_audited(self):
        with self.assertRaisesRegex(ValueError, "active model release"):
            self.catalog.uninstall("vision", "2.0.0")
        result = self.catalog.set_release_status("vision", "2.0.0", "DEPRECATED", "newer release")
        self.assertEqual(result["status"], "DEPRECATED")
        self.assertEqual(result["latestVersion"], "1.0.0")
        payload = json.loads(self.registry.read_text(encoding="utf-8"))
        self.assertEqual(payload["modelHistory"][-1]["status"], "DEPRECATED")

    def test_duplicate_release_is_rejected_by_startup_validation(self):
        payload = json.loads(self.registry.read_text(encoding="utf-8"))
        payload["models"].append(dict(payload["models"][0]))
        self.registry.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate release"):
            self.catalog.validate_startup()

    def test_explicit_migration_moves_one_release_and_keeps_audit_history(self):
        migrated = self.catalog.migrate_release("vision", "helmet-family", "1.0.0", "confirmed upgrade", "operator-1")
        self.assertEqual("helmet-family", migrated["modelId"])
        self.assertEqual("vision", migrated["migratedFromModelId"])
        self.assertEqual({"1.0.0"}, {item["version"] for item in self.catalog.versions("helmet-family")})
        self.assertEqual({"2.0.0"}, {item["version"] for item in self.catalog.versions("vision")})
        history = json.loads(self.registry.read_text(encoding="utf-8"))["modelHistory"]
        self.assertEqual("MIGRATED", history[-1]["status"])
        self.assertEqual("operator-1", history[-1]["actor"])

    def test_explicit_migration_rejects_existing_target_release(self):
        self.catalog.migrate_release("vision", "helmet-family", "1.0.0")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.catalog.migrate_release("vision", "helmet-family", "1.0.0")
        # The failed request must not mutate the remaining source release.
        self.assertEqual("vision", self.catalog.get("vision", "2.0.0")["modelId"])


if __name__ == "__main__":
    unittest.main()
