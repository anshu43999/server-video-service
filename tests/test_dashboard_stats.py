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
from app.stream_config import StreamConfigStore
from project_api_support import ProjectApiSupport


class DashboardStatsTests(ProjectApiSupport, unittest.TestCase):
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
        self.assertEqual(result["verification"]["used"], 0)
        self.assertEqual(result["streams"]["online"], 1)
        self.assertEqual(result["system"]["cpu_percent"], 12.0)

    def test_source_groups_have_independent_denominators_and_include_open(self):
        now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        for event_id, origin in (("mobile-open", "MOBILE_CAMERA"),
                                 ("mobile-handled", "MOBILE_IMAGE"),
                                 ("server-open", "SERVER_STREAM")):
            self.events.register({
                "eventId": event_id, "origin": origin, "ruleId": "r", "sourceId": "s",
                "subjectKey": event_id, "label": "x", "state": "CONFIRMED",
                "startedAtUs": now_us, "confirmedAtUs": now_us,
            })
        self.events.dispose("mobile-handled", "ACKNOWLEDGED", "operator", acted_at_us=now_us + 1)
        result = DashboardStatsService(self.database, self.events).build("today", {}, {})
        self.assertEqual({"totalEvents": 1, "openEvents": 1, "handledEvents": 0, "resolutionRate": 0.0},
                         result["sources"]["MOBILE_CAMERA"])
        self.assertEqual(100.0, result["sources"]["MOBILE_IMAGE"]["resolutionRate"])
        self.assertEqual(0.0, result["sources"]["SERVER_STREAM"]["resolutionRate"])

    def test_api_requires_project_session_and_returns_database_stats(self):
        service = DashboardStatsService(self.database, self.events)
        # Lifespan must not restore streams from a developer's configured DB.
        with patch("app.main.dashboard_stats", service), patch("app.main.stream_config_store", StreamConfigStore(None)):
            self.start_project_api("dashboard-project")
            try:
                client = TestClient(app)
                self.addCleanup(client.close)
                denied = client.get(f"{self.project_path}/dashboard/stats")
                accepted = self.client.get(f"{self.project_path}/dashboard/stats", headers=self.headers)
                self.assertEqual(denied.status_code, 401)
                self.assertEqual(accepted.status_code, 200)
                self.assertEqual(accepted.json()["summary"]["totalEvents"], 0)
                self.assertEqual(accepted.json()["projectId"], self.project_id)
                self.assertEqual(accepted.json()["system"], {})
                self.assertEqual(self.client.get('/aiyoloapi/dashboard/stats', headers=self.headers).status_code, 400)
            finally:
                self.stop_project_api()


if __name__ == "__main__":
    unittest.main()
