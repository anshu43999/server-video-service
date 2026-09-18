import hashlib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.main import _acquire_model_download, _download_rate_events, _release_model_download, app, model_catalog


class ModelDownloadTests(unittest.TestCase):
    def setUp(self):
        self.original_registry_path = model_catalog.registry_path
        model_catalog.registry_path = Path(__file__).resolve().parents[1] / "models" / "registry.test.json"
        self.original_admin = settings.admin_token
        self.original_mobile = settings.mobile_token
        self.original_rate = settings.model_download_rate_limit
        self.original_concurrent = settings.model_download_max_concurrent
        settings.admin_token = "catalog-test-admin"
        settings.mobile_token = None
        settings.model_download_rate_limit = 100
        settings.model_download_max_concurrent = 2
        _download_rate_events.clear()
        self.client = TestClient(app, headers={"X-Admin-Token": "catalog-test-admin"})

    def tearDown(self):
        self.client.close()
        model_catalog.registry_path = self.original_registry_path
        settings.admin_token = self.original_admin
        settings.mobile_token = self.original_mobile
        settings.model_download_rate_limit = self.original_rate
        settings.model_download_max_concurrent = self.original_concurrent
        _download_rate_events.clear()

    def _target(self):
        # Use the isolated test registry so production model entries never exist
        # solely to keep this download test small and deterministic.
        model = next(item for item in model_catalog.list_models() if item["modelId"] == "catalog-download-fixture")
        return model["modelId"], model["artifacts"][0]

    def test_download_returns_bytes_size_hash_and_safe_headers(self):
        model_id, artifact = self._target()
        response = self.client.get(f"/api/models/{model_id}/artifacts/{artifact['artifactId']}/download")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(int(response.headers["content-length"]), artifact["sizeBytes"])
        self.assertEqual(response.headers["x-model-sha256"].lower(), artifact["sha256"].lower())
        self.assertEqual(hashlib.sha256(response.content).hexdigest().lower(), artifact["sha256"].lower())
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertNotIn(str(Path.cwd()), response.headers["content-disposition"])

    def test_download_requires_catalog_token_when_configured(self):
        model_id, artifact = self._target()
        settings.mobile_token = "mobile-secret"
        anonymous = TestClient(app)
        try:
            self.assertEqual(anonymous.get(f"/api/models/{model_id}/artifacts/{artifact['artifactId']}/download").status_code, 401)
            response = anonymous.get(
                f"/api/models/{model_id}/artifacts/{artifact['artifactId']}/download",
                headers={"X-Video-Service-Token": "mobile-secret"},
            )
        finally:
            anonymous.close()
        self.assertEqual(response.status_code, 200)

    def test_missing_model_or_artifact_is_not_found(self):
        self.assertEqual(self.client.get("/api/models/missing/artifacts/nope/download").status_code, 404)
        model_id, _ = self._target()
        response = self.client.get(f"/api/models/{model_id}/artifacts/missing/download")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["error"]["code"], "model_not_found")

    def test_integrity_failure_is_not_streamed(self):
        with patch.object(model_catalog, "get_artifact", side_effect=ValueError("artifact integrity check failed")):
            response = self.client.get("/api/models/any/artifacts/any/download")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["error"]["code"], "model_not_available")

    def test_rate_limit_returns_retryable_error(self):
        model_id, artifact = self._target()
        settings.model_download_rate_limit = 1
        first = self.client.get(f"/api/models/{model_id}/artifacts/{artifact['artifactId']}/download")
        second = self.client.get(f"/api/models/{model_id}/artifacts/{artifact['artifactId']}/download")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["detail"]["error"]["code"], "rate_limited")
        self.assertEqual(second.json()["detail"]["error"]["retryable"], True)

    def test_concurrency_guard_is_bounded(self):
        settings.model_download_max_concurrent = 1
        request = SimpleNamespace(client=SimpleNamespace(host="test-client"))
        _acquire_model_download(request)
        try:
            with self.assertRaisesRegex(Exception, "") as context:
                _acquire_model_download(request)
            self.assertEqual(getattr(context.exception, "status_code", None), 429)
        finally:
            _release_model_download()


if __name__ == "__main__":
    unittest.main()
