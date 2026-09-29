import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.alert_evidence import EvidenceBody, EvidenceStorageError
from app.alerts.disposition import alert_disposition_store
from app.main import alert_evidence_store, app, settings


class MobileAlertIngestApiTests(unittest.TestCase):
    def setUp(self):
        self.old_database = alert_disposition_store.database_manager
        alert_disposition_store.configure_database(None)
        self.old_admin, self.old_mobile = settings.admin_token, settings.mobile_token
        settings.admin_token, settings.mobile_token = "admin-secret", "mobile-secret"
        alert_disposition_store.reset()
        self.client = TestClient(app)

    def tearDown(self):
        settings.admin_token, settings.mobile_token = self.old_admin, self.old_mobile
        alert_disposition_store.reset()
        alert_disposition_store.configure_database(self.old_database)

    def payload(self, **overrides):
        value = {
            "eventId": "local:uploaded-helmet:PPE_NO_HELMET:123",
            "ruleId": "PPE_NO_HELMET",
            "sourceId": "image:现场拍照",
            "origin": "MOBILE_IMAGE",
            "subjectKey": "frame:123",
            "label": "head",
            "state": "CONFIRMED",
            "severity": "IMPORTANT",
            "notifySeverity": "IMPORTANT",
            "startedAtUs": 1000,
            "confirmedAtUs": 1000,
            "lastSeenAtUs": 1000,
            "effectiveThresholds": {"minimumConfidence": 0.8},
            "detectionResults": [{"label": "head", "confidence": 0.91}],
            "evidence": {"snapshotDataUrl": "data:image/png;base64,AAAA"},
        }
        value.update(overrides)
        return value

    @patch.object(alert_evidence_store, "store_data_url")
    def test_mobile_ingest_requires_mobile_token_and_accepts_colon_id(self, store_data_url):
        self.addCleanup(setattr, alert_evidence_store, "enabled", alert_evidence_store.enabled)
        alert_evidence_store.enabled = True
        store_data_url.return_value = {
            "snapshotUri": "/aiyoloapi/alerts/local%3Auploaded-helmet%3APPE_NO_HELMET%3A123/evidence",
            "objectStorage": {
                "provider": "minio",
                "bucket": "aiyolo-alerts",
                "objectKey": "alerts/ab/event.png",
                "contentType": "image/png",
                "sizeBytes": 3,
                "sha256": "abc",
            },
        }
        denied = self.client.post("/aiyoloapi/alerts/mobile-ingest", json=self.payload())
        self.assertEqual(denied.status_code, 401)
        response = self.client.post(
            "/aiyoloapi/alerts/mobile-ingest",
            headers={"X-Video-Service-Token": "mobile-secret"},
            json=self.payload(),
        )
        self.assertEqual(response.status_code, 202)
        event = response.json()["event"]
        self.assertEqual(event["eventId"], "local:uploaded-helmet:PPE_NO_HELMET:123")
        self.assertEqual(event["origin"], "MOBILE_IMAGE")
        self.assertTrue(event["evidence"]["snapshotUri"].endswith("/evidence"))
        self.assertEqual(event["evidence"]["objectStorage"]["provider"], "minio")
        self.assertNotIn("snapshotDataUrl", event["evidence"])
        self.assertNotIn("data:image", str(event))
        store_data_url.assert_called_once()
        with patch.object(
            alert_evidence_store, "read", return_value=EvidenceBody(b"png-bytes", "image/png")
        ) as read:
            image = self.client.get(
                event["evidence"]["snapshotUri"],
                headers={"X-Admin-Token": "admin-secret"},
            )
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.content, b"png-bytes")
        self.assertEqual(image.headers["content-type"], "image/png")
        read.assert_called_once()

    @patch.object(
        alert_evidence_store,
        "store_data_url",
        side_effect=EvidenceStorageError("MinIO unavailable"),
    )
    def test_mobile_ingest_does_not_fall_back_to_database_when_minio_fails(self, _):
        self.addCleanup(setattr, alert_evidence_store, "enabled", alert_evidence_store.enabled)
        alert_evidence_store.enabled = True
        response = self.client.post(
            "/aiyoloapi/alerts/mobile-ingest",
            headers={"X-Video-Service-Token": "mobile-secret"},
            json=self.payload(),
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(alert_disposition_store.list(), [])

    def test_legacy_mobile_payload_infers_origin_from_source(self):
        payload = self.payload(sourceId="camera:back")
        payload.pop("origin")
        response = self.client.post(
            "/aiyoloapi/alerts/mobile-ingest",
            headers={"X-Video-Service-Token": "mobile-secret"},
            json=payload,
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["event"]["origin"], "MOBILE_CAMERA")

    def test_ingest_is_idempotent_and_preserves_disposition_history(self):
        headers = {"X-Video-Service-Token": "mobile-secret"}
        first = self.client.post("/aiyoloapi/alerts/mobile-ingest", headers=headers, json=self.payload(
            disposition={"status": "ACKNOWLEDGED", "actor": "local-operator", "actedAtUs": 2000},
        ))
        self.assertEqual(first.status_code, 202)
        second = self.client.post("/aiyoloapi/alerts/mobile-ingest", headers=headers, json=self.payload(
            detectionResults=[{"label": "head", "confidence": 0.95}],
            disposition={"status": "ACKNOWLEDGED", "actor": "local-operator", "actedAtUs": 2000},
        ))
        self.assertEqual(second.status_code, 202)
        event = second.json()["event"]
        self.assertEqual(event["disposition"]["status"], "ACKNOWLEDGED")
        self.assertEqual(len(event["disposition"]["history"]), 1)
        listed = self.client.get("/aiyoloapi/alerts", headers={"X-Admin-Token": "admin-secret"})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["events"]), 1)

    def test_mobile_token_cannot_use_admin_disposition_endpoint(self):
        response = self.client.post(
            "/aiyoloapi/alerts/mobile-ingest",
            headers={"X-Video-Service-Token": "mobile-secret"},
            json=self.payload(),
        )
        self.assertEqual(response.status_code, 202)
        denied = self.client.post(
            "/aiyoloapi/alerts/local:uploaded-helmet:PPE_NO_HELMET:123/acknowledge",
            headers={"X-Video-Service-Token": "mobile-secret"},
            json={},
        )
        self.assertEqual(denied.status_code, 403)


if __name__ == "__main__":
    unittest.main()
