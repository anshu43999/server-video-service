"""Small-artifact end-to-end regression tests for the M09 model marketplace.

These tests deliberately use the checked-in 187-byte business placeholder.  No
real or large model weights are downloaded; the assertions exercise the same
FastAPI routes and catalog validation used in production.
"""

import hashlib
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.main import _download_rate_events, app, model_catalog


class ModelMarketplaceAutomationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model = next(item for item in model_catalog.list_models() if item["modelId"] == "site-intrusion-v1")
        cls.model_id = model["modelId"]
        cls.artifact = model["artifacts"][0]
        cls.download_path = (
            f"/api/models/{cls.model_id}/artifacts/{cls.artifact['artifactId']}/download"
        )

    def setUp(self):
        self.original_admin = settings.admin_token
        self.original_mobile = settings.mobile_token
        self.original_rate = settings.model_download_rate_limit
        settings.admin_token = None
        settings.mobile_token = None
        settings.model_download_rate_limit = 100
        _download_rate_events.clear()

    def tearDown(self):
        settings.admin_token = self.original_admin
        settings.mobile_token = self.original_mobile
        settings.model_download_rate_limit = self.original_rate
        _download_rate_events.clear()

    def test_directory_query_and_scenario_filter(self):
        with TestClient(app) as client:
            listing = client.get("/api/models", params={"scenario": "intrusion"})
            detail = client.get(f"/api/models/{self.model_id}")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([item["modelId"] for item in listing.json()["models"]], [self.model_id])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["modelId"], self.model_id)
        self.assertNotIn("path", detail.json())

    def test_catalog_authentication_failure(self):
        settings.mobile_token = "m09-mobile-secret"
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/models").status_code, 401)
            self.assertEqual(client.get("/api/models", headers={"X-Video-Service-Token": "wrong"}).status_code, 401)

    def test_download_hash_and_size_match_catalog(self):
        with TestClient(app) as client:
            response = client.get(self.download_path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.content), self.artifact["sizeBytes"])
        self.assertEqual(
            hashlib.sha256(response.content).hexdigest().lower(),
            self.artifact["sha256"].lower(),
        )
        self.assertEqual(response.headers["x-model-sha256"].lower(), self.artifact["sha256"].lower())

    def test_download_integrity_mismatch_is_rejected_without_bytes(self):
        with patch.object(model_catalog, "get_artifact", side_effect=ValueError("artifact integrity check failed")):
            with TestClient(app) as client:
                response = client.get(self.download_path)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["error"]["code"], "model_not_available")
        self.assertIn(b"model_not_available", response.content)

    def test_download_rate_limit_returns_retryable_429(self):
        settings.model_download_rate_limit = 1
        with TestClient(app) as client:
            first = client.get(self.download_path)
            second = client.get(self.download_path)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["detail"]["error"]["code"], "rate_limited")
        self.assertTrue(second.json()["detail"]["error"]["retryable"])
        self.assertIn("retry-after", second.headers)


if __name__ == "__main__":
    unittest.main()
