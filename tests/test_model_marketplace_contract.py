import json
import re
import unittest
from pathlib import Path


class ModelMarketplaceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(__file__).resolve().parents[1] / "docs" / "model-marketplace-api.md"
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_contract_covers_three_endpoint_families(self):
        for endpoint in (
            "GET /api/models",
            "GET /api/models/{modelId}",
            "GET /api/models/{modelId}/artifacts/{artifactId}/download",
        ):
            self.assertIn(endpoint, self.text)

    def test_contract_freezes_required_metadata_and_mvp_boundary(self):
        for field in ("modelId", "version", "scenario", "runtime", "labels", "sizeBytes", "sha256", "compatibleDevices"):
            self.assertIn(f"`{field}`", self.text)
        self.assertIn("MVP 不含数字签名", self.text)
        self.assertIn("X-Video-Service-Token", self.text)
        self.assertIn("不得放入 query、path、下载 URL 或日志", self.text)

    def test_example_payload_is_valid_json_and_has_android_aliases(self):
        fenced = re.search(r"```json\n(\{\n  \"models\".*?\n\})\n```", self.text, re.S)
        self.assertIsNotNone(fenced)
        payload = json.loads(fenced.group(1))
        model = payload["models"][0]
        for key in ("modelId", "version", "scenario", "artifacts", "format", "downloadUrl", "sizeBytes", "sha256"):
            self.assertIn(key, model)
        artifact = model["artifacts"][0]
        self.assertEqual(artifact["sha256"], model["sha256"])

    def test_error_table_includes_auth_not_found_rate_limit_and_retryability(self):
        for token in ("authentication_required", "model_not_found", "rate_limited", "retryable", "service_unavailable"):
            self.assertIn(f"`{token}`", self.text)


if __name__ == "__main__":
    unittest.main()
