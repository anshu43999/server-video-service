import os
import unittest
from copy import deepcopy
from datetime import datetime, timezone

from app.alerts.delivery import AlertDeliveryService, ManagementPageChannel
from app.alerts.verification import AlertVerificationStore
from app.alerts.verification_provider import VerificationProviderResult
from app.config import settings
from app.database import (
    AlertDeliveryReceiptRecord,
    AlertEventRecord,
    AlertVerificationConfigRecord,
    AlertVerificationRecord,
    DEFAULT_PROJECT_ID,
    DatabaseManager,
    ProjectRecord,
)
from app.alerts.disposition import AlertDispositionStore
from sqlalchemy import delete
from postgresql_support import isolated_postgresql_url


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "set RUN_POSTGRES_TESTS=1 for PostgreSQL integration")
class VerificationDeliveryPostgreSqlTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls._postgres = isolated_postgresql_url("m33_verification_delivery")
        cls.database_url = cls._postgres.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._postgres.__exit__(None, None, None)

    async def test_project_quota_and_same_event_results_remain_isolated_after_reopen(self):
        database = DatabaseManager(self.database_url)
        projects = ["quota-a-" + os.urandom(4).hex(), "quota-b-" + os.urandom(4).hex()]
        try:
            now = datetime.now(timezone.utc)
            with database.session() as session:
                for project in projects:
                    session.add(ProjectRecord(project_id=project, project_code=project,
                                              display_name=project, created_at=now, updated_at=now))
            alerts = AlertDispositionStore(database)
            class Provider:
                def review(self, **kwargs):
                    return VerificationProviderResult("CONFIRMED", "fixture")
            provider = Provider()
            store = AlertVerificationStore(database_manager=database, provider=provider)
            for project in projects:
                store.configure(enabled=True, image_egress_authorized=True, daily_limit=1,
                                model_id=project, provider_configured=True, project_id=project)
                for event_id in ("same-event", "next-event"):
                    alerts.register({"eventId": event_id}, project_id=project)
            for project in projects:
                event = alerts.get("same-event", project)
                result = store.request(event, actor=project, image_ref="evidence",
                                       image_data="data:image/jpeg;base64,aW1hZ2U=", project_id=project)
                self.assertEqual(result["status"], "CONFIRMED")
                self.assertEqual(result["projectId"], project)
                self.assertEqual(result["modelId"], project)
                self.assertEqual(store.request(event, actor="retry", image_ref="evidence",
                                              project_id=project), result)
                self.assertEqual(store.config(project)["callsToday"], 1)
            database.close()
            database = DatabaseManager(self.database_url)
            store = AlertVerificationStore(database_manager=database, provider=provider)
            alerts = AlertDispositionStore(database)
            for project in projects:
                self.assertEqual(store.get("same-event", project)["actor"], project)
                self.assertEqual(store.config(project)["callsToday"], 1)
                result = store.request(alerts.get("next-event", project), actor=project,
                                       image_ref="evidence", project_id=project)
                self.assertEqual(result["failureKind"], "QUOTA_EXHAUSTED")
                self.assertEqual(store.config(project)["callsToday"], 1)
        finally:
            database.close()

    async def test_verification_config_result_and_receipt_survive_reopen(self):
        event_id = "evt-vd-pg-" + os.urandom(8).hex()
        delivery_id = None
        database = DatabaseManager(self.database_url)
        with database.session() as session:
            previous_config = session.get(AlertVerificationConfigRecord, (DEFAULT_PROJECT_ID, "default"))
            previous_config_state = None if previous_config is None else {
                "calls_day": previous_config.calls_day,
                "calls_today": previous_config.calls_today,
                "payload": deepcopy(previous_config.payload),
            }
        try:
            alerts = AlertDispositionStore(database)
            alerts.register({
                "eventId": event_id,
                "ruleId": "helmet",
                "sourceId": "camera:pg",
                "evidence": {"snapshotUri": "evidence/frame.jpg"},
            })
            verification = AlertVerificationStore(database_manager=database)
            verification.configure(
                enabled=True,
                image_egress_authorized=True,
                daily_limit=4,
                model_id="review-model",
                provider_configured=False,
            )
            result = verification.request(
                alerts.get(event_id), actor="reviewer", image_ref="evidence/frame.jpg"
            )
            self.assertEqual(result["failureKind"], "NOT_CONFIGURED")

            channel = ManagementPageChannel()
            service = AlertDeliveryService(
                channels={"management": channel}, database_manager=database, retry_delay_seconds=0
            )
            delivery_id = service.dispatch({"eventId": event_id, "severity": "MAJOR"}, ["management"])[0]
            await service.drain()

            reopened = DatabaseManager(self.database_url)
            try:
                self.assertEqual(AlertVerificationStore(database_manager=reopened).get(event_id)["status"], "FAILED")
                config = AlertVerificationStore(database_manager=reopened).config()
                self.assertEqual(config["dailyLimit"], 4)
                self.assertEqual(config["callsToday"], 0)
                with reopened.session() as session:
                    receipt = session.get(AlertDeliveryReceiptRecord, (DEFAULT_PROJECT_ID, delivery_id))
                self.assertEqual(receipt.event_id, event_id)
            finally:
                reopened.close()
        finally:
            with database.session() as session:
                if delivery_id:
                    session.execute(delete(AlertDeliveryReceiptRecord).where(
                        AlertDeliveryReceiptRecord.delivery_id == delivery_id
                    ))
                session.execute(delete(AlertVerificationRecord).where(
                    AlertVerificationRecord.event_id == event_id
                ))
                config = session.get(AlertVerificationConfigRecord, (DEFAULT_PROJECT_ID, "default"))
                if previous_config_state is None:
                    if config is not None:
                        session.delete(config)
                elif config is not None:
                    config.calls_day = previous_config_state["calls_day"]
                    config.calls_today = previous_config_state["calls_today"]
                    config.payload = previous_config_state["payload"]
                session.execute(delete(AlertEventRecord).where(AlertEventRecord.event_id == event_id))
            database.close()


if __name__ == "__main__":
    unittest.main()
