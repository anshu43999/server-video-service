from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.alerts.disposition import AlertDispositionStore
from app.alerts.verification import AlertVerificationStore
from app.dashboard import DashboardStatsService
from app.database import Base, DatabaseManager
from app.main import app


class DashboardStatsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = DatabaseManager(f"sqlite+pysqlite:///{Path(self.temp.name) / 'dashboard.db'}")
        Base.metadata.create_all(self.database.engine)
        self.events = AlertDispositionStore(self.database)

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def test_empty_database_returns_real_zero_values(self):
        result = DashboardStatsService(self.database, self.events).build("today", {}, {})
        self.assertEqual(result["dataSource"], "sqlite")
        self.assertEqual(result["summary"]["totalEvents"], 0)
        self.assertEqual(result["summary"]["resolutionRate"], 0)
        self.assertEqual(result["categories"], [])
        self.assertEqual(result["streams"], {"total": 0, "online": 0, "waiting": 0, "errors": 0})

    def test_event_categories_dispositions_and_verification_are_aggregated(self):
        now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        event = {
            "eventId": "dashboard-event-1",
            "ruleId": "PPE_NO_HELMET",
            "sourceId": "camera-1",
            "subjectKey": "person-1",
            "label": "head",
            "displayName": "未佩戴安全帽",
            "state": "CONFIRMED",
            "severity": "MAJOR",
            "notifySeverity": "MAJOR",
            "startedAtUs": now_us,
            "confirmedAtUs": now_us,
            "evidence": {"snapshotUri": "evidence/frame.jpg"},
        }
        self.events.register(event)
        self.events.dispose("dashboard-event-1", "ACKNOWLEDGED", "operator", acted_at_us=now_us + 60_000_000)
        verification = AlertVerificationStore(database_manager=self.database)
        verification.configure(
            enabled=True,
            image_egress_authorized=True,
            daily_limit=5,
            model_id="review-model",
            provider_configured=False,
        )
        verification.request(self.events.get("dashboard-event-1"), actor="operator", image_ref="evidence/frame.jpg")

        result = DashboardStatsService(self.database, self.events).build(
            "today",
            {"camera-1": SimpleNamespace(frames_received=1, last_error=None, alert_error=None, publisher=None)},
            {"cpu_percent": 12.0, "memory_percent": 35.0, "disk_percent": 44.0},
        )
        self.assertEqual(result["summary"]["totalEvents"], 1)
        self.assertEqual(result["summary"]["handledEvents"], 1)
        self.assertEqual(result["summary"]["resolutionRate"], 100.0)
        self.assertEqual(result["severity"]["total"]["MAJOR"], 1)
        self.assertEqual(result["severity"]["handled"]["MAJOR"], 1)
        self.assertEqual(result["categories"][0]["label"], "未佩戴安全帽")
        self.assertEqual(result["verification"]["used"], 1)
        self.assertEqual(result["streams"]["online"], 1)
        self.assertEqual(result["system"]["cpu_percent"], 12.0)

    def test_api_requires_admin_token_and_returns_database_stats(self):
        service = DashboardStatsService(self.database, self.events)
        with patch("app.main.dashboard_stats", service):
            from app.main import settings
            old_token = settings.admin_token
            settings.admin_token = "dashboard-admin"
            try:
                client = TestClient(app)
                denied = client.get("/api/dashboard/stats")
                accepted = client.get("/api/dashboard/stats", headers={"X-Admin-Token": "dashboard-admin"})
                self.assertEqual(denied.status_code, 401)
                self.assertEqual(accepted.status_code, 200)
                self.assertEqual(accepted.json()["summary"]["totalEvents"], 0)
            finally:
                settings.admin_token = old_token


if __name__ == "__main__":
    unittest.main()
