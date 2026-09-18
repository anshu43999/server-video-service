import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app, model_catalog, streams
from app.model_catalog import ModelCatalog


def artifact(path: Path, artifact_id: str) -> dict:
    return {
        "artifactId": artifact_id,
        "format": "bin",
        "platform": "test",
        "path": path.as_posix(),
        "sizeBytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
    }


class ModelCatalogUninstallTests(unittest.TestCase):
    def test_legacy_basename_marks_only_first_matching_server_model_active(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root) as temp:
            project = Path(temp)
            models = project / "models"
            models.mkdir()
            first = models / "one" / "source.pt"
            second = models / "two" / "source.pt"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            registry = models / "registry.json"
            entries = [
                {"modelId": "first-model", "format": "pt", "path": "models/one/source.pt", "artifacts": [artifact(first, "first")]},
                {"modelId": "second-model", "format": "pt", "path": "models/two/source.pt", "artifacts": [artifact(second, "second")]},
            ]
            registry.write_text(json.dumps({"activeServerModel": "source.pt", "models": entries}), encoding="utf-8")

            catalog = ModelCatalog(registry)
            models_view = catalog.list_models()

            self.assertEqual([item["modelId"] for item in models_view if item["active"]], ["first-model"])
            result = catalog.uninstall("second-model")
            self.assertTrue(result["uninstalled"])
            self.assertFalse(second.exists())
            self.assertTrue(first.exists())

    def test_new_active_model_id_does_not_collide_on_same_basename(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root) as temp:
            project = Path(temp)
            models = project / "models"
            models.mkdir()
            first = models / "one" / "source.pt"
            second = models / "two" / "source.pt"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            registry = models / "registry.json"
            entries = [
                {"modelId": "first-model", "format": "pt", "path": "models/one/source.pt", "artifacts": [artifact(first, "first")]},
                {"modelId": "second-model", "format": "pt", "path": "models/two/source.pt", "artifacts": [artifact(second, "second")]},
            ]
            registry.write_text(json.dumps({"activeServerModel": "second-model", "models": entries}), encoding="utf-8")

            catalog = ModelCatalog(registry)
            self.assertEqual([item["modelId"] for item in catalog.list_models() if item["active"]], ["second-model"])
            with self.assertRaisesRegex(ValueError, "active model"):
                catalog.uninstall("second-model")
            self.assertTrue(second.exists())
            result = catalog.uninstall("first-model")
            self.assertTrue(result["uninstalled"])
            self.assertFalse(first.exists())

    def test_activate_persists_model_id_and_resolves_exact_server_path(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root) as temp:
            project = Path(temp)
            models = project / "models"
            models.mkdir()
            first = models / "one" / "source.pt"
            second = models / "two" / "source.pt"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            registry = models / "registry.json"
            entries = [
                {"modelId": "first-model", "format": "pt", "path": "models/one/source.pt", "sizeBytes": 5, "sha256": hashlib.sha256(b"first").hexdigest().upper(), "artifacts": [artifact(first, "first")]},
                {"modelId": "second-model", "format": "pt", "path": "models/two/source.pt", "sizeBytes": 6, "sha256": hashlib.sha256(b"second").hexdigest().upper(), "artifacts": [artifact(second, "second")]},
            ]
            registry.write_text(json.dumps({"activeServerModel": "source.pt", "models": entries}), encoding="utf-8")

            catalog = ModelCatalog(registry)
            activated = catalog.activate("second-model")
            payload = json.loads(registry.read_text(encoding="utf-8"))

            self.assertEqual(payload["activeServerModel"], "second-model")
            self.assertTrue(activated["active"])
            self.assertEqual([item["modelId"] for item in catalog.list_models() if item["active"]], ["second-model"])
            self.assertEqual(Path(catalog.active_server_path()), second.resolve())

    def test_uninstall_deletes_unique_files_and_retains_shared_files(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root) as temp:
            project = Path(temp)
            models = project / "models"
            models.mkdir()
            unique = models / "unique.bin"
            shared = models / "shared.bin"
            unique.write_bytes(b"unique")
            shared.write_bytes(b"shared")
            registry = models / "registry.json"
            registry.write_text(json.dumps({
                "activeServerModel": "other.bin",
                "models": [
                    {
                        "modelId": "remove-me",
                        "path": "models/unique.bin",
                        "artifacts": [artifact(unique, "unique"), artifact(shared, "shared")],
                    },
                    {
                        "modelId": "keep-me",
                        "path": "models/shared.bin",
                        "artifacts": [artifact(shared, "shared")],
                    },
                ],
            }), encoding="utf-8")

            result = ModelCatalog(registry).uninstall("remove-me")

            self.assertTrue(result["uninstalled"])
            self.assertEqual(result["deletedFiles"], 1)
            self.assertEqual(result["retainedSharedFiles"], 1)
            self.assertFalse(unique.exists())
            self.assertTrue(shared.exists())
            payload = json.loads(registry.read_text(encoding="utf-8"))
            self.assertEqual([item["modelId"] for item in payload["models"]], ["keep-me"])

    def test_uninstall_ignores_external_label_and_manifest_paths(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root) as temp:
            project = Path(temp)
            models = project / "models"
            models.mkdir()
            artifact_path = models / "owned.bin"
            artifact_path.write_bytes(b"owned")
            external_dir = project / "docs" / "models"
            external_dir.mkdir(parents=True)
            labels = external_dir / "labels.txt"
            manifest = external_dir / "manifest.json"
            labels.write_text("person\n", encoding="utf-8")
            manifest.write_text("{}", encoding="utf-8")
            registry = models / "registry.json"
            registry.write_text(json.dumps({
                "models": [{
                    "modelId": "external-metadata",
                    "format": "pt",
                    "path": "models/owned.bin",
                    "labelsPath": "docs/models/labels.txt",
                    "manifestPath": "docs/models/manifest.json",
                    "artifacts": [artifact(artifact_path, "owned")],
                }],
            }), encoding="utf-8")

            result = ModelCatalog(registry).uninstall("external-metadata")

            self.assertTrue(result["uninstalled"])
            self.assertFalse(artifact_path.exists())
            self.assertTrue(labels.exists())
            self.assertTrue(manifest.exists())

    def test_active_model_cannot_be_uninstalled(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root) as temp:
            project = Path(temp)
            models = project / "models"
            models.mkdir()
            active = models / "active.bin"
            active.write_bytes(b"active")
            registry = models / "registry.json"
            registry.write_text(json.dumps({
                "activeServerModel": "active",
                "models": [{"modelId": "active", "format": "pt", "path": "models/active.bin", "artifacts": [artifact(active, "active")]}],
            }), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "active model"):
                ModelCatalog(registry).uninstall("active")
            self.assertTrue(active.exists())


class ModelUninstallApiTests(unittest.TestCase):
    def setUp(self):
        self.original_admin = settings.admin_token
        settings.admin_token = "uninstall-admin"
        self.client = TestClient(app, headers={"X-Admin-Token": "uninstall-admin"})

    def tearDown(self):
        self.client.close()
        settings.admin_token = self.original_admin
        streams.pop("uninstall-bound-stream", None)

    def test_admin_can_uninstall_an_unbound_model(self):
        result = {"modelId": "demo", "uninstalled": True, "deletedFiles": 2, "cleanupFailures": []}
        with patch.object(model_catalog, "uninstall", return_value=result) as uninstall:
            response = self.client.delete("/api/models/demo")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), result)
        uninstall.assert_called_once_with("demo")

    def test_bound_model_is_rejected_before_catalog_mutation(self):
        streams["uninstall-bound-stream"] = SimpleNamespace(model_catalog_id="demo")
        with patch.object(model_catalog, "uninstall") as uninstall:
            response = self.client.delete("/api/models/demo")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "model_in_use")
        self.assertEqual(response.json()["detail"]["streamIds"], ["uninstall-bound-stream"])
        uninstall.assert_not_called()

    def test_uninstall_requires_admin_and_maps_missing_model(self):
        anonymous = TestClient(app)
        try:
            self.assertEqual(anonymous.delete("/api/models/demo").status_code, 401)
        finally:
            anonymous.close()
        with patch.object(model_catalog, "uninstall", side_effect=KeyError("missing")):
            response = self.client.delete("/api/models/missing")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "model_not_found")


if __name__ == "__main__":
    unittest.main()
