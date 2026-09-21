import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Base, DatabaseManager
from app.main import app


class DatabaseConfigurationTests(unittest.TestCase):
    def test_missing_url_is_an_explicit_memory_fallback(self):
        database = DatabaseManager(None)
        self.assertFalse(database.enabled)
        self.assertEqual(database.connect(), {"configured": False, "backend": "memory", "status": "fallback"})

    def test_database_url_rejects_non_postgresql_backends(self):
        with self.assertRaisesRegex(ValueError, "PostgreSQL"):
            Settings(database_url="sqlite:///unexpected.db", _env_file=None)

    def test_schema_and_health_use_isolated_in_memory_database(self):
        database = DatabaseManager("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(database.engine)
        self.assertEqual(database.connect()["status"], "ok")
        self.assertEqual(
            set(Base.metadata.tables),
            {
                "accounts", "account_sessions",
                "alert_events", "alert_disposition_actions", "false_positive_feedback",
                "alert_rules", "alert_rule_bindings", "alert_rule_audits",
                "model_parameter_profiles", "model_parameter_audits",
                "alert_verification_config", "alert_verifications", "alert_delivery_receipts",
                "conversion_config", "conversion_jobs", "calibration_datasets", "stream_configs",
            },
        )
        database.close()

    def test_missing_migration_is_reported_without_exposing_the_url(self):
        database = DatabaseManager("sqlite+pysqlite:///:memory:")
        state = database.health()
        self.assertEqual(state["status"], "unavailable")
        self.assertEqual(state["error"], "RuntimeError")
        self.assertNotIn("url", state)
        database.close()

    def test_unreachable_postgresql_is_unavailable_without_credentials(self):
        database = DatabaseManager(
            "postgresql+psycopg://secret-user:secret-password@127.0.0.1:1/missing",
            connect_timeout_seconds=1,
        )
        state = database.health()
        self.assertEqual(state["configured"], True)
        self.assertEqual(state["backend"], "postgresql")
        self.assertEqual(state["status"], "unavailable")
        self.assertNotIn("secret-user", str(state))
        self.assertNotIn("secret-password", str(state))
        database.close()

    def test_health_endpoint_is_degraded_when_database_is_unavailable(self):
        with patch("app.main.database.health", return_value={
            "configured": True,
            "backend": "postgresql",
            "status": "unavailable",
            "error": "OperationalError",
        }):
            response = TestClient(app).get("/healthz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertEqual(response.json()["database"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
