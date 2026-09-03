import unittest

from fastapi.testclient import TestClient

from app.main import app, streams


class MetricsApiTests(unittest.TestCase):
    def setUp(self):
        streams.clear()

    def test_metrics_endpoint_returns_system_and_streams(self):
        with TestClient(app) as client:
            response = client.get("/api/metrics")
            self.assertEqual(response.status_code, 200)
            self.assertIn("system", response.json())
            self.assertIn("streams", response.json())


if __name__ == "__main__":
    unittest.main()
