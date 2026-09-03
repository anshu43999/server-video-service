import unittest

from fastapi.testclient import TestClient

from app.main import app, model_catalog
from app.config import settings


class ModelCatalogTests(unittest.TestCase):
    def setUp(self):
        self.original_admin = settings.admin_token
        settings.admin_token = None

    def tearDown(self):
        settings.admin_token = self.original_admin

    def test_list_models_reports_migrated_assets(self):
        models = model_catalog.list_models()
        self.assertGreaterEqual(len(models), 4)
        pt = next(model for model in models if model["format"] == "pt")
        self.assertTrue(pt["exists"])
        self.assertTrue(pt["hashValid"])

    def test_activate_requires_valid_server_format(self):
        with TestClient(app) as client:
            response = client.post("/api/models/ultralytics-yolo11n-coco-dev-640-int8/activate")
            self.assertEqual(response.status_code, 409)

    def test_activate_migrated_pt_model(self):
        original = __import__("json").loads((model_catalog.registry_path).read_text(encoding="utf-8"))["activeServerModel"]
        try:
            with TestClient(app) as client:
                response = client.post("/api/models/ultralytics-yolo11n-coco-dev-pt/activate")
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["active_model"]["hashValid"])
        finally:
            registry = __import__("json").loads(model_catalog.registry_path.read_text(encoding="utf-8"))
            registry["activeServerModel"] = original
            model_catalog.registry_path.write_text(__import__("json").dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_register_conversion_manifest_validates_artifact_hash(self):
        registry_path = model_catalog.registry_path
        original = registry_path.read_text(encoding="utf-8")
        try:
            with TestClient(app) as client:
                response = client.post(
                    "/api/models/register",
                    json={"manifest_path": "models/converted/yolo11n_640_manifest.json"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(any(item["format"] == "onnx" for item in response.json()["models"]))
                self.assertTrue(any(item["modelId"] == "converted-yolo11n-640-onnx" for item in model_catalog.list_models()))
        finally:
            registry_path.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
