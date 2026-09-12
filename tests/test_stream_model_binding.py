import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.detector import YoloDetector
from app.model_catalog import ModelCatalog
from app.stream import StreamSession


class StreamModelBindingTests(unittest.TestCase):
    def test_binding_replaces_only_target_stream_and_keeps_metadata(self):
        first = StreamSession("first")
        second = StreamSession("second")
        first.bind_model(model_id="model-a", model_path="models/a.pt", scenario="intrusion", purpose="business", labels=["person"], imgsz=416)
        second.bind_model(model_id="model-b", model_path="models/b.pt", scenario="safety", purpose="development", labels=["helmet"], imgsz=640)
        self.assertEqual(first.model_metadata()["catalog_model_id"], "model-a")
        self.assertEqual(first.model_metadata()["scenario"], "intrusion")
        self.assertEqual(second.model_metadata()["catalog_model_id"], "model-b")
        self.assertEqual(second.model_metadata()["scenario"], "safety")
        self.assertEqual(first.detector.imgsz, 416)
        self.assertEqual(second.detector.imgsz, 640)

    def test_detector_reports_catalog_id_inference_metadata(self):
        detector = YoloDetector("models/a.pt", model_id="catalog-a")
        self.assertEqual(detector.model_id, "catalog-a")
        self.assertEqual(detector.metadata()["model_id"], "catalog-a")

    def test_catalog_rejects_mobile_only_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            models = root / "models"
            models.mkdir()
            path = models / "mobile.tflite"
            path.write_bytes(b"mobile")
            registry = models / "registry.json"
            registry.write_text(json.dumps({"models": [{"modelId": "mobile", "format": "tflite", "path": "models/mobile.tflite", "sizeBytes": 6, "sha256": ""}] }))
            catalog = ModelCatalog(registry)
            with self.assertRaises(ValueError):
                catalog.resolve_server_model("mobile")


if __name__ == "__main__":
    unittest.main()
