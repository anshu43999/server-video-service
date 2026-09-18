import os
import unittest
from copy import deepcopy

from app.alerts.delivery import AlertDeliveryService, ManagementPageChannel
from app.alerts.verification import AlertVerificationStore
from app.config import settings
from app.database import (
    AlertDeliveryReceiptRecord,
    AlertEventRecord,
    AlertVerificationConfigRecord,
    AlertVerificationRecord,
    DatabaseManager,
)
from app.alerts.disposition import AlertDispositionStore
from sqlalchemy import delete


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "set RUN_POSTGRES_TESTS=1 for PostgreSQL integration")
class VerificationDeliveryPostgreSqlTests(unittest.IsolatedAsyncioTestCase):
    async def test_verification_config_result_and_receipt_survive_reopen(self):
        event_id = "evt-vd-pg-" + os.urandom(8).hex()
        delivery_id = None
        database = DatabaseManager(settings.database_url)
        with database.session() as session:
            previous_config = session.get(AlertVerificationConfigRecord, "default")
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

            reopened = DatabaseManager(settings.database_url)
            try:
                self.assertEqual(AlertVerificationStore(database_manager=reopened).get(event_id)["status"], "FAILED")
                config = AlertVerificationStore(database_manager=reopened).config()
                self.assertEqual(config["dailyLimit"], 4)
                self.assertEqual(config["callsToday"], 1)
                with reopened.session() as session:
                    receipt = session.get(AlertDeliveryReceiptRecord, delivery_id)
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
                config = session.get(AlertVerificationConfigRecord, "default")
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
