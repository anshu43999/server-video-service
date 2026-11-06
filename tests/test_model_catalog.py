import unittest
import json
import hashlib
from pathlib import Path

import app.main as main
from test_project_model_assignments import ModelApiFixture


class ModelCatalogTests(ModelApiFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.client.headers.update(self.headers)

    def test_list_models_reports_migrated_assets(self):
        models = main.model_catalog.list_models()
        self.assertGreaterEqual(len(models), 2)
        pt = next(model for model in models if model["format"] == "pt")
        self.assertTrue(pt["exists"])
        self.assertTrue(pt["hashValid"])

    def test_legacy_manifest_derives_targets_only_from_valid_artifacts(self):
        registry = main.model_catalog._load()
        legacy = registry["models"][0]
        legacy.pop("supportedTargets", None)
        legacy.pop("publishedTargets", None)
        main.model_catalog._save(registry)
        model = main.model_catalog.get(legacy["modelId"], legacy["version"])
        self.assertEqual("legacy-derived", model["supportedTargetsSource"])
        self.assertEqual(["pc", "mobile"], model["supportedTargets"])
        self.assertTrue(model["targetReadiness"]["pc"]["ready"])
        self.assertTrue(model["targetReadiness"]["mobile"]["ready"])

        android = next(a for a in legacy["artifacts"] if a["format"] == "tflite")
        Path(main.model_catalog.project_root, android["path"]).unlink()
        model = main.model_catalog.get(legacy["modelId"], legacy["version"])
        self.assertEqual(["pc"], model["supportedTargets"])
        self.assertFalse(model["targetReadiness"]["mobile"]["ready"])
        Path(main.model_catalog.project_root, legacy["path"]).unlink()
        model = main.model_catalog.get(legacy["modelId"], legacy["version"])
        self.assertEqual([], model["supportedTargets"])
        self.assertEqual("target_not_supported", model["targetReadiness"]["pc"]["reason"])

    def test_activate_requires_valid_server_format(self):
        registry = main.model_catalog._load()
        registry["models"][2]["format"] = "tflite"
        main.model_catalog._save(registry)
        response = self.client.post("/aiyoloapi/models/secret/activate")
        self.assertEqual(response.status_code, 409)

    def test_activate_migrated_pt_model(self):
        response = self.client.post("/aiyoloapi/models/secret/activate")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["active_model"]["hashValid"])

    def test_pc_runtime_validation_endpoint_is_authenticated_and_persists_result(self):
        model = next(row for row in main.model_catalog.list_models() if row.get("format") == "pt")
        self.assertEqual(401, self.client.post(
            f"/aiyoloapi/models/{model['modelId']}/versions/{model['version']}/validate-pc-runtime",
            headers={"Authorization": "Bearer invalid"}).status_code)
        original_runner = main.conversion_service.runner

        class PassingRunner:
            def run_worker(self, config, action, directory, stopping):
                self.action = action
                return {"ok": True, "warmup": "passed", "ultralytics": "test"}

        runner = PassingRunner()
        main.conversion_service.runner = runner
        try:
            response = self.client.post(
                f"/aiyoloapi/models/{model['modelId']}/versions/{model['version']}/validate-pc-runtime")
        finally:
            main.conversion_service.runner = original_runner
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("inspect", runner.action)
        self.assertTrue(response.json()["serverValidated"])
        self.assertEqual(response.json()["sha256"].lower(), response.json()["serverValidationSha256"].lower())

    def test_register_conversion_manifest_validates_artifact_hash(self):
        models = Path(self.temp.name) / "models"
        artifact = models / "fixture.onnx"
        artifact.write_bytes(b"isolated conversion fixture")
        manifest = models / "manifest.json"
        payload = {"artifacts": [{"format": "onnx", "path": "models/fixture.onnx",
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}]}
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        response = self.client.post("/aiyoloapi/models/register", json={"manifest_path": "models/manifest.json"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(item["format"] == "onnx" for item in response.json()["models"]))
        artifact.write_bytes(b"tampered")
        response = self.client.post("/aiyoloapi/models/register", json={"manifest_path": "models/manifest.json"})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
