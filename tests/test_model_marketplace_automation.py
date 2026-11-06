"""Small-artifact end-to-end regression tests for the M09 model marketplace."""

import hashlib
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.main import _download_rate_events, app
import app.main as main
from test_project_model_assignments import ModelApiFixture


class ModelMarketplaceAutomationTests(ModelApiFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.original_rate = settings.model_download_rate_limit
        self.addCleanup(setattr, settings, "model_download_rate_limit", self.original_rate)
        self.addCleanup(_download_rate_events.clear)
        settings.model_download_rate_limit = 100
        _download_rate_events.clear()
        self.assertEqual(self._assign().status_code, 200)
        self.model_id = "helmet"
        self.artifact = main.model_catalog.get(self.model_id, "1.0.0")["artifacts"][0]
        self.download_path = (
            f"{self.project_path}/models/{self.model_id}/versions/1.0.0/"
            f"artifacts/{self.artifact['artifactId']}/download"
        )
        self.client.headers.update(self.user)

    def test_directory_query_and_scenario_filter(self):
        listing = self.client.get(self.project_path + "/models", params={"scenario": "ppe"})
        detail = self.client.get(self.project_path + f"/models/{self.model_id}")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([item["modelId"] for item in listing.json()["models"]], [self.model_id])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["modelId"], self.model_id)
        self.assertNotIn("path", detail.json())

    def test_catalog_authentication_failure(self):
        anonymous = TestClient(app)
        try:
            self.assertEqual(anonymous.get("/aiyoloapi/models").status_code, 401)
            self.assertEqual(anonymous.get("/aiyoloapi/models", headers={"X-Video-Service-Token": "wrong"}).status_code, 401)
        finally:
            anonymous.close()

    def test_download_hash_and_size_match_catalog(self):
        response = self.client.get(self.download_path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.content), self.artifact["sizeBytes"])
        self.assertEqual(
            hashlib.sha256(response.content).hexdigest().lower(),
            self.artifact["sha256"].lower(),
        )
        self.assertEqual(response.headers["x-model-sha256"].lower(), self.artifact["sha256"].lower())

    def test_download_integrity_mismatch_is_rejected_without_bytes(self):
        with patch.object(main.model_catalog, "get_artifact", side_effect=ValueError("artifact integrity check failed")):
            response = self.client.get(self.download_path)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["error"]["code"], "model_not_available")
        self.assertIn(b"model_not_available", response.content)

    def test_download_rate_limit_returns_retryable_429(self):
        settings.model_download_rate_limit = 1
        first = self.client.get(self.download_path)
        second = self.client.get(self.download_path)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["detail"]["error"]["code"], "rate_limited")
        self.assertTrue(second.json()["detail"]["error"]["retryable"])
        self.assertIn("retry-after", second.headers)


if __name__ == "__main__":
    unittest.main()
