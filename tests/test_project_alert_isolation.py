import asyncio
import base64
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from starlette.websockets import WebSocketDisconnect

from app.alerts.delivery import AlertDeliveryService, ManagementPageChannel
from app.alerts.disposition import AlertDispositionStore, alert_disposition_store
from app.alerts.verification import alert_verification_store
from app.database import Base, DatabaseManager, ProjectRecord
from app.main import alert_delivery
from app.stream_config import StreamConfigStore
from project_api_support import ProjectApiSupport


def event_payload(event_id: str = "shared-event", *, image: bytes = b"project-image") -> dict:
    return {
        "eventId": event_id,
        "ruleId": "helmet",
        "sourceId": "camera-1",
        "origin": "MOBILE_CAMERA",
        "subjectKey": "frame:1",
        "label": "head",
        "state": "CONFIRMED",
        "severity": "IMPORTANT",
        "notifySeverity": "IMPORTANT",
        "startedAtUs": 1_000,
        "confirmedAtUs": 1_000,
        "lastSeenAtUs": 1_000,
        "effectiveThresholds": {"minimumConfidence": 0.8},
        "detectionResults": [{"label": "head", "confidence": 0.91}],
        "evidence": {
            "snapshotDataUrl": "data:image/png;base64,"
            + base64.b64encode(image).decode("ascii")
        },
    }


class ProjectAlertApiIsolationTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        # This API regression must not restore streams from the configured business DB.
        self.enterContext(patch("app.main.stream_config_store", StreamConfigStore(None)))
        self.old_disposition_database = alert_disposition_store.database_manager
        self.old_verification_database = alert_verification_store.database_manager
        self.old_delivery_database = alert_delivery.database_manager
        alert_disposition_store.configure_database(None)
        alert_verification_store.configure_database(None)
        alert_delivery.configure_database(None)
        alert_disposition_store.reset()
        alert_verification_store.reset()
        alert_delivery.last_receipts.clear()
        self.start_project_api("alert-alpha")
        self.project_a = self.project_id

        user_a = self.client.post(
            "/aiyoloapi/platform/accounts",
            headers=self.headers,
            json={
                "username": "alert-user-a",
                "password": "temporary-test-password",
                "platformRole": "NORMAL_USER",
            },
        ).json()
        owner_b = self.client.post(
            "/aiyoloapi/platform/accounts",
            headers=self.headers,
            json={
                "username": "alert-owner-b",
                "password": "temporary-test-password",
                "platformRole": "NORMAL_USER",
            },
        ).json()
        project_b = self.client.post(
            "/aiyoloapi/projects",
            headers=self.headers,
            json={
                "projectCode": "alert-beta",
                "displayName": "Alert Beta",
                "ownerAccountId": owner_b["accountId"],
            },
        ).json()
        self.project_b = project_b["projectId"]
        self.client.post(
            f"/aiyoloapi/projects/{self.project_a}/members",
            headers=self.headers,
            json={"accountId": user_a["accountId"], "projectRole": "PROJECT_USER"},
        )
        login_a = self.client.post(
            "/aiyoloapi/auth/login",
            json={"username": "alert-user-a", "password": "temporary-test-password"},
        ).json()
        login_b = self.client.post(
            "/aiyoloapi/auth/login",
            json={"username": "alert-owner-b", "password": "temporary-test-password"},
        ).json()
        self.user_a_id = user_a["accountId"]
        self.user_a_headers = {"Authorization": f"Bearer {login_a['accessToken']}"}
        self.owner_b_headers = {"Authorization": f"Bearer {login_b['accessToken']}"}
        self.alerts_a = f"/aiyoloapi/projects/{self.project_a}/alerts"
        self.alerts_b = f"/aiyoloapi/projects/{self.project_b}/alerts"

    def tearDown(self):
        alert_disposition_store.reset()
        alert_verification_store.reset()
        alert_delivery.last_receipts.clear()
        alert_disposition_store.configure_database(self.old_disposition_database)
        alert_verification_store.configure_database(self.old_verification_database)
        alert_delivery.configure_database(self.old_delivery_database)
        self.stop_project_api()

    def test_events_evidence_actor_verification_export_and_delivery_are_isolated(self):
        first = self.client.post(
            f"{self.alerts_a}/mobile-ingest",
            headers=self.user_a_headers,
            json=event_payload(image=b"project-a"),
        )
        second = self.client.post(
            f"{self.alerts_b}/mobile-ingest",
            headers=self.owner_b_headers,
            json=event_payload(image=b"project-b"),
        )
        self.assertEqual(202, first.status_code, first.text)
        self.assertEqual(202, second.status_code, second.text)
        self.assertEqual(self.project_a, first.json()["event"]["projectId"])
        self.assertEqual(self.project_b, second.json()["event"]["projectId"])

        listed_a = self.client.get(self.alerts_a, headers=self.user_a_headers).json()
        listed_b = self.client.get(self.alerts_b, headers=self.owner_b_headers).json()
        self.assertEqual([self.project_a], [item["projectId"] for item in listed_a["events"]])
        self.assertEqual([self.project_b], [item["projectId"] for item in listed_b["events"]])
        self.assertEqual(
            404, self.client.get(self.alerts_b, headers=self.user_a_headers).status_code
        )
        self.assertEqual(
            400, self.client.get("/aiyoloapi/alerts", headers=self.user_a_headers).status_code
        )

        evidence_a = self.client.get(
            f"{self.alerts_a}/shared-event/evidence", headers=self.user_a_headers
        )
        evidence_b = self.client.get(
            f"{self.alerts_b}/shared-event/evidence", headers=self.owner_b_headers
        )
        self.assertEqual(b"project-a", evidence_a.content)
        self.assertEqual(b"project-b", evidence_b.content)

        disposed = self.client.post(
            f"{self.alerts_a}/shared-event/false-positive",
            headers={**self.user_a_headers, "X-Actor": "forged-actor"},
            json={"actedAtUs": 2_000},
        )
        self.assertEqual(200, disposed.status_code, disposed.text)
        self.assertEqual(self.user_a_id, disposed.json()["disposition"]["actor"])
        untouched_b = self.client.get(
            f"{self.alerts_b}/shared-event", headers=self.owner_b_headers
        ).json()
        self.assertEqual("OPEN", untouched_b["disposition"]["status"])
        self.assertEqual(
            403,
            self.client.get(
                f"{self.alerts_a}/false-positives/export",
                headers=self.user_a_headers,
            ).status_code,
        )
        exported = self.client.get(
            f"{self.alerts_a}/false-positives/export", headers=self.headers
        )
        self.assertEqual(200, exported.status_code)
        self.assertEqual(self.project_a, exported.json()["entries"][0]["projectId"])

        config_a = self.client.post(
            f"/aiyoloapi/projects/{self.project_a}/verification/config",
            headers=self.headers,
            json={
                "enabled": True,
                "imageEgressAuthorized": False,
                "dailyLimit": 1,
                "modelId": "review-a",
                "expectedRevision": 0,
                "providerConfigured": False,
            },
        )
        config_b = self.client.post(
            f"/aiyoloapi/projects/{self.project_b}/verification/config",
            headers=self.owner_b_headers,
            json={
                "enabled": False,
                "imageEgressAuthorized": False,
                "dailyLimit": 9,
                "modelId": "review-b",
                "expectedRevision": 0,
                "providerConfigured": False,
            },
        )
        self.assertEqual(1, config_a.json()["dailyLimit"])
        self.assertEqual(9, config_b.json()["dailyLimit"])
        read_a = self.client.get(
            f"/aiyoloapi/projects/{self.project_a}/verification/config",
            headers=self.user_a_headers,
        ).json()
        read_b = self.client.get(
            f"/aiyoloapi/projects/{self.project_b}/verification/config",
            headers=self.owner_b_headers,
        ).json()
        self.assertEqual("review-a", read_a["modelId"])
        self.assertEqual("review-b", read_b["modelId"])

        review = self.client.post(
            f"{self.alerts_a}/shared-event/verification",
            headers={**self.user_a_headers, "X-Operator-Id": "forged"},
            json={},
        )
        self.assertEqual(202, review.status_code, review.text)
        self.assertEqual(self.user_a_id, review.json()["actor"])
        self.assertEqual(self.project_a, review.json()["projectId"])
        self.assertEqual(
            404,
            self.client.get(
                f"{self.alerts_b}/shared-event/verification",
                headers=self.user_a_headers,
            ).status_code,
        )

        async def delivery_isolation():
            service = AlertDeliveryService(
                channels={"management": ManagementPageChannel()}
            )
            channel = service.channels["management"]
            queue_a = await channel.subscribe(self.project_a)
            queue_b = await channel.subscribe(self.project_b)
            try:
                service.dispatch(
                    {"eventId": "delivery-a"}, ["management"], project_id=self.project_a
                )
                await service.drain()
                self.assertEqual(self.project_a, (await queue_a.get())["projectId"])
                self.assertTrue(queue_b.empty())
                self.assertEqual(1, len(service.recent_receipts(10, self.project_a)))
                self.assertEqual([], service.recent_receipts(10, self.project_b))
            finally:
                await channel.unsubscribe(queue_a)
                await channel.unsubscribe(queue_b)

        asyncio.run(delivery_isolation())

        with self.assertRaises(WebSocketDisconnect) as caught:
            with self.client.websocket_connect(
                f"{self.alerts_b}/ws", headers=self.user_a_headers
            ):
                pass
        self.assertEqual(4404, caught.exception.code)


class ProjectAlertDatabaseIsolationTests(unittest.TestCase):
    def test_same_event_id_and_related_records_are_project_scoped(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root / ".test-db") as temp:
            database = DatabaseManager(f"sqlite+pysqlite:///{Path(temp) / 'alerts.db'}")
            try:
                Base.metadata.create_all(database.engine)
                with database.session() as session:
                    session.add_all([
                        ProjectRecord(project_id="project-a", project_code="db-alert-a", display_name="A"),
                        ProjectRecord(project_id="project-b", project_code="db-alert-b", display_name="B"),
                    ])
                store = AlertDispositionStore(database)
                store.register({"eventId": "same", "disposition": {"status": "OPEN"}}, project_id="project-a")
                store.register({"eventId": "same", "disposition": {"status": "OPEN"}}, project_id="project-b")
                store.dispose("same", "FALSE_POSITIVE", "account-a", acted_at_us=1, project_id="project-a")

                self.assertEqual("FALSE_POSITIVE", store.get("same", "project-a")["disposition"]["status"])
                self.assertEqual("OPEN", store.get("same", "project-b")["disposition"]["status"])
                self.assertEqual(1, len(store.feedback("project-a")))
                self.assertEqual([], store.feedback("project-b"))

                async def persist_receipts():
                    service = AlertDeliveryService(
                        channels={"management": ManagementPageChannel()},
                        database_manager=database,
                    )
                    service.dispatch(
                        store.get("same", "project-a"), ["management"], project_id="project-a"
                    )
                    service.dispatch(
                        store.get("same", "project-b"), ["management"], project_id="project-b"
                    )
                    await service.drain()
                    self.assertEqual(1, len(service.recent_receipts(10, "project-a")))
                    self.assertEqual(1, len(service.recent_receipts(10, "project-b")))

                asyncio.run(persist_receipts())
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
