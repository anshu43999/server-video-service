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
                "accounts", "account_sessions", "projects", "project_memberships",
                "service_principals", "service_request_nonces",
                "project_model_assignments", "project_audit_events", "platform_audit_events",
                "project_scenes", "project_scene_members",
                "project_scene_plans", "project_scene_plan_members", "project_scene_installations",
                "project_scene_runtime_grants",
                "resource_lifecycle_operations", "resource_lifecycle_events",
                "model_update_installations", "model_update_devices", "model_update_targets",
                "model_update_inbox", "model_update_changes", "model_update_reports",
                "model_update_tickets", "model_update_snapshots", "model_update_push_outbox",
                "model_update_domain_outbox", "model_update_rate_buckets", "model_update_metrics",
                "alert_events", "alert_disposition_actions", "false_positive_feedback",
                "alert_rules", "alert_rule_bindings", "alert_rule_audits",
                "model_parameter_profiles", "model_parameter_audits",
                "alert_verification_config", "alert_verifications", "alert_delivery_receipts",
                "alert_advice_knowledge_entries", "alert_advice_knowledge_revisions",
                "alert_advice_generations",
                "app_update_identities", "app_artifacts", "app_artifact_sources",
                "app_update_policies", "app_releases", "app_update_policy_revisions",
                "app_rollback_operations", "app_update_device_states", "app_update_receipts",
                "app_update_audit_events", "app_apk_uploads",
                "conversion_config", "conversion_jobs", "calibration_datasets", "stream_configs", "project_business_config",
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
