import json
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from test_project_model_assignments import ModelApiFixture


class ModelMarketplaceApiTests(ModelApiFixture, unittest.TestCase):

    def test_list_and_detail_follow_contract_without_local_paths(self):
        with TestClient(app, headers=self.headers) as client:
            response = client.get("/aiyoloapi/models")
            self.assertEqual(response.status_code, 200)
            models = response.json()["models"]
            self.assertEqual(len(models), 3)
            model = models[0]
            for key in ("modelId", "version", "scenario", "runtime", "labels", "artifacts", "releaseEligible"):
                self.assertIn(key, model)
            self.assertIn("downloadUrl", model)
            self.assertNotIn("path", model)
            self.assertNotIn("path", model["artifacts"][0])
            payload = json.dumps(model)
            self.assertNotIn(str(Path.cwd()), payload)
            detail = client.get(f"/aiyoloapi/models/{model['modelId']}")
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["modelId"], model["modelId"])

    def test_scenario_filter_is_exact_and_unknown_is_empty(self):
        with TestClient(app, headers=self.headers) as client:
            response = client.get("/aiyoloapi/models", params={"scenario": "ppe"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["models"])
            self.assertTrue(all(item["scenario"] == "ppe" for item in response.json()["models"]))
            self.assertEqual(client.get("/aiyoloapi/models", params={"scenario": "does-not-exist"}).json(), {"models": []})

    def test_catalog_reads_require_a_configured_token(self):
        settings.admin_token = "admin-secret"
        with TestClient(app) as client:
            self.assertEqual(client.get("/aiyoloapi/models").status_code, 401)
            self.assertEqual(client.get("/aiyoloapi/models", headers={"X-Admin-Token": "wrong"}).status_code, 401)
            self.assertEqual(client.get("/aiyoloapi/models", headers={"X-Admin-Token": "admin-secret"}).status_code, 401)
            self.assertEqual(client.get("/aiyoloapi/models", headers=self.headers).status_code, 200)

    def test_mobile_session_requires_project_and_missing_model_is_404(self):
        self.assertEqual(200, self._assign().status_code)
        with TestClient(app) as client:
            headers = {"X-Video-Service-Token": self.user["Authorization"].split(" ", 1)[1]}
            self.assertEqual(client.get("/aiyoloapi/models", headers=headers).status_code, 400)
            headers["X-Project-Id"] = self.project_id
            self.assertEqual(client.get("/aiyoloapi/models", headers=headers).status_code, 200)
            self.assertEqual(client.get("/aiyoloapi/models/missing-model", headers=headers).status_code, 404)
            self.assertEqual(client.get("/aiyoloapi/models/missing-model").status_code, 401)


if __name__ == "__main__":
    unittest.main()
