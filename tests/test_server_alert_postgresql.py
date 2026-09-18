import os
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import delete

from app.alerts.disposition import AlertDispositionStore
from app.alerts.runtime import ServerAlertRuntime
from app.config import settings
from app.database import AlertDeliveryReceiptRecord, AlertEventRecord, DatabaseManager
from app.detection import Detection, InferenceResult
from app.model_parameters import ModelParameterStore


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "set RUN_POSTGRES_TESTS=1 for PostgreSQL integration")
class ServerAlertPostgreSqlTests(unittest.TestCase):
    def test_server_event_and_end_state_survive_new_connection(self):
        model = {"modelId": "server-alert-pg", "name": "Server alert", "version": "1.0.0", "labels": ["head"]}
        event_store = None
        event_id = None
        database = DatabaseManager(settings.database_url)
        with tempfile.TemporaryDirectory() as temp:
            try:
                event_store = AlertDispositionStore(database)
                delivery_ids = []
                class Delivery:
                    def dispatch(self, event):
                        delivery_ids.append(event["eventId"])
                        return ["test"]
                runtime = ServerAlertRuntime(
                    model_provider=lambda model_id: model,
                    parameter_store=ModelParameterStore(Path(temp) / "legacy.json", database),
                    event_store=event_store,
                    delivery_service=Delivery(),
                    evidence_root=Path(temp) / "evidence",
                )
                result = InferenceResult(
                    detections=(Detection(0, "head", 0.9),), model_id=model["modelId"],
                    class_names=("head",), provides=("BOX",),
                )
                for timestamp in (3_000_000_000_000, 3_000_200_000_000, 3_000_400_000_000, 3_000_800_000_000):
                    emitted = runtime.process(source_id="server-camera", captured_at_us=timestamp, result=result)
                self.assertEqual(len(emitted), 1)
                event_id = emitted[0]["eventId"]
                self.assertEqual(delivery_ids, [event_id])
                reopened_database = DatabaseManager(settings.database_url)
                try:
                    reopened = AlertDispositionStore(reopened_database)
                    self.assertEqual(reopened.get(event_id)["origin"], "server")
                finally:
                    reopened_database.close()
                runtime.process(
                    source_id="server-camera", captured_at_us=3_001_000_000_000,
                    result=InferenceResult(model_id=model["modelId"], class_names=("head",), provides=("BOX",)),
                )
                reopened_database = DatabaseManager(settings.database_url)
                try:
                    self.assertEqual(AlertDispositionStore(reopened_database).get(event_id)["state"], "ENDED")
                finally:
                    reopened_database.close()
            finally:
                with database.session() as session:
                    if event_id:
                        session.execute(delete(AlertDeliveryReceiptRecord).where(
                            AlertDeliveryReceiptRecord.event_id == event_id
                        ))
                        session.execute(delete(AlertEventRecord).where(
                            AlertEventRecord.event_id == event_id
                        ))
                database.close()


if __name__ == "__main__":
    unittest.main()
