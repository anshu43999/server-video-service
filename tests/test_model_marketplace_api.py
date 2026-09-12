import json
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


class ModelMarketplaceApiTests(unittest.TestCase):
    def setUp(self):
        self.original_admin = settings.admin_token
        self.original_mobile = settings.mobile_token
        settings.admin_token = None
        settings.mobile_token = None

    def tearDown(self):
        settings.admin_token = self.original_admin
        settings.mobile_token = self.original_mobile

    def test_list_and_detail_follow_contract_without_local_paths(self):
        with TestClient(app) as client:
            response = client.get("/api/models")
            self.assertEqual(response.status_code, 200)
            models = response.json()["models"]
            self.assertGreaterEqual(len(models), 4)
            model = models[0]
            for key in ("modelId", "version", "scenario", "runtime", "labels", "artifacts", "releaseEligible"):
                self.assertIn(key, model)
            self.assertIn("downloadUrl", model)
            self.assertNotIn("path", model)
            self.assertNotIn("path", model["artifacts"][0])
            payload = json.dumps(model)
            self.assertNotIn(str(Path.cwd()), payload)
            detail = client.get(f"/api/models/{model['modelId']}")
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["modelId"], model["modelId"])

    def test_scenario_filter_is_exact_and_unknown_is_empty(self):
        with TestClient(app) as client:
            response = client.get("/api/models", params={"scenario": "general-detection"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["models"])
            self.assertTrue(all(item["scenario"] == "general-detection" for item in response.json()["models"]))
            self.assertEqual(client.get("/api/models", params={"scenario": "does-not-exist"}).json(), {"models": []})

    def test_catalog_reads_require_a_configured_token(self):
        settings.admin_token = "admin-secret"
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/models").status_code, 401)
            self.assertEqual(client.get("/api/models", headers={"X-Admin-Token": "wrong"}).status_code, 401)
            self.assertEqual(client.get("/api/models", headers={"X-Admin-Token": "admin-secret"}).status_code, 200)
            self.assertEqual(client.get("/api/models", headers={"Authorization": "Bearer admin-secret"}).status_code, 200)

    def test_mobile_token_is_accepted_and_missing_model_is_404(self):
        settings.mobile_token = "mobile-secret"
        with TestClient(app) as client:
            headers = {"X-Video-Service-Token": "mobile-secret"}
            self.assertEqual(client.get("/api/models", headers=headers).status_code, 200)
            self.assertEqual(client.get("/api/models/missing-model", headers=headers).status_code, 404)
            self.assertEqual(client.get("/api/models/missing-model").status_code, 401)


if __name__ == "__main__":
    unittest.main()
