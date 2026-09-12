import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.model_catalog import ModelCatalog, ModelCatalogValidationError


class ModelCatalogSourceTests(unittest.TestCase):
    def _catalog(self, *, content: bytes = b"model-bytes", sha256: str | None = None):
        # Reuse the checked-in small development artifact to avoid Windows
        # sandbox restrictions on creating nested temporary directories.
        root = Path(__file__).resolve().parents[1]
        artifact = root / "models" / "yolo11n.pt"
        digest = sha256 or hashlib.sha256(artifact.read_bytes()).hexdigest().upper()
        registry = {
            "schemaVersion": 1,
            "registryType": "server-video-service-models",
            "models": [{
                "modelId": "demo-v1",
                "name": "Demo",
                "version": "1.0.0",
                "scenario": "intrusion",
                "purpose": "business",
                "runtime": "server-onnx",
                "labels": ["person"],
                "compatibleDevices": [],
                "artifacts": [{
                    "artifactId": "server-onnx",
                    "format": "onnx",
                    "platform": "server",
                    "path": "models/yolo11n.pt",
                    "sizeBytes": artifact.stat().st_size,
                    "sha256": digest,
                }],
            }],
        }
        registry_path = root / "models" / "registry.test.json"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        return ModelCatalog(registry_path), root

    def test_startup_validation_accepts_complete_source(self):
        catalog, _ = self._catalog()
        self.assertIsNone(catalog.validate_startup())

    def test_startup_validation_rejects_missing_artifact(self):
        catalog, root = self._catalog()
        catalog.registry_path.write_text(catalog.registry_path.read_text(encoding="utf-8").replace("models/yolo11n.pt", "models/missing.pt"), encoding="utf-8")
        with self.assertRaisesRegex(ModelCatalogValidationError, "artifact missing"):
            catalog.validate_startup()

    def test_startup_validation_rejects_hash_mismatch(self):
        catalog, _ = self._catalog(sha256="0" * 64)
        with self.assertRaisesRegex(ModelCatalogValidationError, "SHA-256 mismatch"):
            catalog.validate_startup()

    def test_startup_validation_rejects_missing_required_metadata(self):
        catalog, _ = self._catalog()
        payload = json.loads(catalog.registry_path.read_text(encoding="utf-8"))
        del payload["models"][0]["scenario"]
        catalog.registry_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ModelCatalogValidationError, "scenario is required"):
            catalog.validate_startup()


if __name__ == "__main__":
    unittest.main()
