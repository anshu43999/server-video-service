import unittest
from contextlib import ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app, streams
from app.stream_config import StreamConfigStore
from app.database import DatabaseManager
from app.model_updates.service import ModelUpdateService
import app.auth as auth_module


class MetricsApiTests(unittest.TestCase):
    def setUp(self):
        streams.clear()
        self.isolation = ExitStack()
        self.addCleanup(self.isolation.close)
        self.isolation.enter_context(patch('app.main.conversion_service.start'))
        self.isolation.enter_context(patch('app.main.conversion_service.close'))
        self.isolation.enter_context(patch('app.main.database.verify_schema', return_value={"status": "ok"}))
        self.isolation.enter_context(patch('app.main.stream_config_store', StreamConfigStore(None)))
        self.isolation.enter_context(patch('app.auth.database', DatabaseManager(None)))
        self.isolation.enter_context(patch('app.main.model_updates',
            ModelUpdateService(DatabaseManager(None), None, None)))
        self.isolation.enter_context(patch.dict(auth_module._memory_accounts, {}, clear=True))
        self.isolation.enter_context(patch.dict(auth_module._memory_sessions, {}, clear=True))

    def test_metrics_endpoint_returns_system_and_streams(self):
        with TestClient(app) as client:
            response = client.post('/aiyoloapi/auth/setup', json={
                'username': 'metrics-admin', 'password': 'temporary-test-password',
            })
            self.assertEqual(response.status_code, 200)
            response = client.get("/aiyoloapi/metrics")
            self.assertEqual(response.status_code, 200)
            self.assertIn("system", response.json())
            self.assertIn("streams", response.json())
            self.assertEqual(response.json()['modelUpdates']['status'], 'database_not_configured')


if __name__ == "__main__":
    unittest.main()
