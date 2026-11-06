import base64
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.alerts.disposition import alert_disposition_store
from app.alerts.verification import alert_verification_store
from app.alerts.verification_provider import VerificationProviderError
from app.main import app
from project_api_support import ProjectApiSupport


class FakeProvider:
    def __init__(self):
        self.calls = []

    def review(self, **kwargs):
        self.calls.append(kwargs)
        return type("Result", (), {
            "verdict": "CONFIRMED", "reason": "provider fixture matched", "source": "TEST_PROVIDER"
        })()


class AlertVerificationProviderApiTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        self.old_database = alert_disposition_store.database_manager
        alert_disposition_store.configure_database(None)
        alert_disposition_store.reset()
        self.old_verification_database = alert_verification_store.database_manager
        alert_verification_store.configure_database(None)
        alert_verification_store.reset()
        self.provider = FakeProvider()
        self.old_provider = alert_verification_store._provider
        alert_verification_store.configure_provider(self.provider)
        self.start_project_api("verification-provider-project")
        alert_disposition_store.register({
            "eventId": "provider-event", "ruleId": "helmet", "sourceId": "cam",
            "subjectKey": "track:1", "label": "helmet",
            "evidence": {"snapshotUri": "data:image/jpeg;base64," + base64.b64encode(b"image").decode("ascii")},
            "disposition": {"status": "OPEN"},
        }, project_id=self.project_id)

    def tearDown(self):
        alert_verification_store.configure_provider(self.old_provider)
        alert_verification_store.reset()
        alert_verification_store.configure_database(self.old_verification_database)
        alert_disposition_store.reset()
        alert_disposition_store.configure_database(self.old_database)
        self.stop_project_api()

    def test_retired_endpoints_never_call_the_configured_provider(self):
        configured = self.client.post(
            f"{self.project_path}/verification/config", headers=self.headers,
            json={"expectedRevision": 0, "enabled": True, "imageEgressAuthorized": True,
                  "dailyLimit": 2, "modelId": "provider-model", "providerConfigured": False},
        )
        self.assertEqual(410, configured.status_code, configured.text)
        result = self.client.post(
            f"{self.project_path}/alerts/provider-event/verification", headers=self.headers, json={},
        )
        self.assertEqual(410, result.status_code, result.text)
        self.assertEqual("verification_retired", result.json()["detail"]["code"])
        self.assertEqual([], self.provider.calls)


if __name__ == "__main__":
    unittest.main()
