"""M34-T05: durable alerts and notifications without any video consumer."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.alerts.delivery import AlertDeliveryService
from app.alerts.disposition import AlertDispositionStore
from app.alerts.runtime import ServerAlertRuntime
from app.database import Base, DatabaseManager
from app.detection import Detection, InferenceResult, NormalizedBox


class AnalysisAlertClosureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="m34-t05-")
        self.root = Path(self.temp.name)
        self.database = DatabaseManager("sqlite+pysqlite:///" + (self.root / "alerts.db").as_posix())
        Base.metadata.create_all(self.database.engine)
        self.store = AlertDispositionStore(self.database)
        self.delivery = AlertDeliveryService(retry_delay_seconds=0, database_manager=self.database)
        # Keep the channel policy independent of the production project registry.
        self.policy = patch.object(self.delivery.policy_store, "selected_channels",
                                   side_effect=lambda project, event, channels: tuple(channels))
        self.policy.start()
        self.profile = {"modelVersion": "1", "revision": 7, "alertRules": [{
            "enabled": True, "rawLabel": "person", "eventCode": "PERSON",
            "camera": {"minimumConfidence": .7, "minimumConsecutiveFrames": 2,
                       "minimumDwellTimeMs": 0, "cooldownMs": 1000}}]}
        self.runtime = self.new_runtime()
        self.result = InferenceResult(model_id="fixture", class_names=("person",), provides=("BOX",),
            detections=(Detection(0, "person", .9, NormalizedBox(.1, .1, .3, .5)),),
            frame_width=48, frame_height=32)
        self.empty = InferenceResult(model_id="fixture", class_names=("person",), provides=("BOX",))
        self.frame = np.zeros((32, 48, 3), dtype=np.uint8)

    async def asyncTearDown(self):
        await self.delivery.close()
        self.policy.stop()
        self.database.close()
        self.temp.cleanup()

    def new_runtime(self):
        return ServerAlertRuntime(model_provider=lambda *args: {"modelId": "fixture", "version": "1"},
            parameter_store=None, event_store=self.store, delivery_service=self.delivery,
            evidence_root=self.root / "evidence", profile_provider=lambda *args: self.profile)

    def process(self, timestamp, *, result=None, runtime=None, project="project-a"):
        return (runtime or self.runtime).process(project_id=project, source_id="camera-shared",
            captured_at_us=timestamp, result=result if result is not None else self.result, frame=self.frame)

    async def confirm(self):
        self.assertEqual([], self.process(1_000_000))
        event = self.process(1_100_000)[0]
        await self.delivery.drain()
        return event

    async def test_no_preview_or_subscriber_still_persists_one_event_and_jpeg(self):
        event = await self.confirm()
        self.process(1_200_000)
        self.assertEqual(1, len(self.store.list(project_id="project-a")))
        self.assertEqual("SERVER_STREAM", event["origin"])
        self.assertEqual("camera-shared", event["streamId"])
        self.assertTrue(self.runtime.evidence_path(event["eventId"], "project-a").read_bytes().startswith(b"\xff\xd8"))
        for name in ("management", "app"):
            self.assertEqual(0, self.delivery.channels[name].subscriber_count)
        reopened = DatabaseManager(self.database.url)
        try:
            self.assertEqual(event["eventId"], AlertDispositionStore(reopened).list(project_id="project-a")[0]["eventId"])
        finally:
            reopened.close()

    async def test_end_commit_failure_retries_without_losing_active_event(self):
        event = await self.confirm()
        with patch.object(self.store, "register", side_effect=RuntimeError("database unavailable")):
            with self.assertRaises(RuntimeError):
                self.process(1_300_000, result=self.empty)
        self.process(1_400_000, result=self.empty)
        self.assertEqual("ENDED", self.store.get(event["eventId"], "project-a")["state"])
        self.process(1_500_000)
        self.assertEqual([], self.process(1_600_000))
        self.assertEqual(1, len(self.store.list(project_id="project-a")))

    async def test_evidence_snapshot_survives_sqlite_reopen_and_does_not_follow_later_detections(self):
        import cv2
        event = await self.confirm()
        snapshot = event["evidence"]["displayOverlay"]
        self.assertEqual(1_100_000, snapshot["capturedAtUs"])
        self.assertIs(snapshot["bakedIn"], False)
        self.assertEqual(event["detectionResults"], snapshot["detections"])
        path = self.runtime.evidence_path(event["eventId"], "project-a")
        expected = cv2.imencode(".jpg", self.frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])[1].tobytes()
        self.assertEqual(expected, path.read_bytes())
        later = InferenceResult(model_id="fixture", detections=(Detection(0, "person", .95,
            NormalizedBox(.5, .5, .2, .2)),), frame_width=48, frame_height=32)
        self.process(1_200_000, result=later)
        reopened = DatabaseManager(self.database.url)
        try:
            saved = AlertDispositionStore(reopened).get(event["eventId"], "project-a")
            self.assertEqual(snapshot, saved["evidence"]["displayOverlay"])
            self.assertEqual(expected, path.read_bytes())
        finally:
            reopened.close()

    async def test_local_compatibility_path_remains_single_level_without_fabricating_original(self):
        event = await self.confirm()
        evidence = event["evidence"]
        self.assertIn("snapshotUri", evidence)
        self.assertNotIn("thumbnail", evidence)
        self.assertNotIn("original", evidence)

    async def test_acknowledged_active_event_does_not_duplicate_after_restart(self):
        event = await self.confirm()
        self.store.dispose(event["eventId"], "ACKNOWLEDGED", "test-operator", project_id="project-a")
        restarted = self.new_runtime()
        self.process(1_200_000, runtime=restarted)
        self.assertEqual([], self.process(1_300_000, runtime=restarted))
        self.assertEqual(1, len(self.store.list(project_id="project-a")))

    async def test_confirmation_commit_failure_has_no_notification_then_recovers(self):
        self.process(1_000_000)
        with patch.object(self.store, "register", side_effect=RuntimeError("database unavailable")):
            with self.assertRaises(RuntimeError):
                self.process(1_100_000)
        self.assertEqual([], self.delivery.last_receipts)
        self.assertEqual([], self.store.list(project_id="project-a"))
        event = self.process(1_200_000)[0]
        await self.delivery.drain()
        self.process(1_300_000)
        self.assertEqual(1, len(self.store.list(project_id="project-a")))
        self.assertEqual(1_000_000, event["startedAtUs"])

    async def test_receipt_database_failure_never_resends_successful_notification(self):
        channel = self.delivery.channels["management"]
        queue = await channel.subscribe("project-a")
        try:
            with patch.object(self.delivery, "_persist_receipt", side_effect=RuntimeError("secret db failure")):
                self.delivery.dispatch({"eventId": "receipt-failure"}, ["management"], project_id="project-a")
                await self.delivery.drain()
            self.assertEqual(1, queue.qsize())
            self.assertEqual("delivered", self.delivery.last_receipts[-1].status)
            self.assertEqual("receipt_persistence_failure", self.delivery.last_receipts[-1].error_code)
            self.assertNotIn("secret", str(self.delivery.last_receipts))
            self.assertEqual("receipt_persistence_failure",
                self.delivery.recent_receipts(project_id="project-a")[0]["error_code"])
            self.assertEqual([], self.delivery.recent_receipts(project_id="project-b"))
        finally:
            await channel.unsubscribe(queue)

    async def test_evidence_write_failure_never_sends_a_premature_notification(self):
        self.process(1_000_000)
        with patch.object(self.runtime, "_save_evidence", side_effect=OSError("storage unavailable")):
            with self.assertRaises(OSError):
                self.process(1_100_000)
        self.assertEqual([], self.store.list(project_id="project-a"))
        self.assertEqual([], self.delivery.last_receipts)
        event = self.process(1_200_000)[0]
        await self.delivery.drain()
        self.assertTrue(self.runtime.evidence_path(event["eventId"], "project-a").is_file())

    async def test_cooldown_survives_restart_and_new_episode_has_a_new_id(self):
        original = await self.confirm()
        self.process(1_200_000, result=self.empty)
        restarted = self.new_runtime()
        self.process(1_300_000, runtime=restarted)
        self.assertEqual([], self.process(1_400_000, runtime=restarted))
        self.process(2_300_000, runtime=restarted)
        new = self.process(2_400_000, runtime=restarted)[0]
        await self.delivery.drain()
        self.assertNotEqual(original["eventId"], new["eventId"])
        self.assertEqual(2, len(self.store.list(project_id="project-a")))

    async def test_failed_mobile_channel_does_not_rollback_or_repeat_the_alert(self):
        from unittest.mock import AsyncMock
        channel = self.delivery.channels["app"]
        with patch.object(channel, "send", new=AsyncMock(side_effect=RuntimeError("private provider URL"))) as send:
            event = await self.confirm()
            self.assertEqual(3, send.await_count)
            receipts = {receipt.channel: receipt for receipt in self.delivery.last_receipts}
            self.assertEqual("failed", receipts["app"].status)
            self.assertEqual("delivered", receipts["management"].status)
            self.assertEqual("adapter_failure", receipts["app"].error_code)
            self.assertEqual(event["eventId"], self.store.list(project_id="project-a")[0]["eventId"])
            self.process(1_200_000)
            await self.delivery.drain()
            self.assertEqual(3, send.await_count)

    async def test_receipt_persistence_recovers_without_resending_and_preserves_one_receipt(self):
        persist = self.delivery._persist_receipt
        attempts = 0
        def fail_once(receipt, event):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary db failure")
            return persist(receipt, event)
        channel = self.delivery.channels["app"]
        queue = await channel.subscribe("project-a")
        try:
            with patch.object(self.delivery, "_persist_receipt", side_effect=fail_once):
                self.delivery.dispatch({"eventId": "receipt-recovery"}, ["app"], project_id="project-a")
                await self.delivery.drain()
            self.assertEqual(1, queue.qsize())
            self.assertEqual(2, attempts)
            self.assertEqual(1, len(self.delivery.recent_receipts(project_id="project-a")))
            self.assertIsNone(self.delivery.last_receipts[0].error_code)
        finally:
            await channel.unsubscribe(queue)


if __name__ == "__main__":
    unittest.main()
