"""M34-T02 regressions: analysis and alerts must not depend on live distribution."""
import asyncio
import os
import threading
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import numpy as np
from fastapi import HTTPException
from app.config import settings
from app.detection import Detection, InferenceResult, NormalizedBox
from app.alerts.disposition import AlertDispositionStore
from app.alerts.runtime import ServerAlertRuntime
from app.database import Base, DatabaseManager
from app.media_authorization import MediaAuthorizationRequest, authorize_media_read
from app.protocol import StreamState
from app.stream import StreamSession

class AnalysisOnlyTests(unittest.IsolatedAsyncioTestCase):
    def session(self):
        stream = StreamSession("same-id", project_id="project-a", alert_runtime=Mock())
        stream.yolo_enabled = True
        stream.detector.infer = Mock(return_value=InferenceResult(frame_width=48, frame_height=32, provides=("BOX",)))
        stream.detector._load = Mock()
        return stream

    async def submit(self, stream):
        await stream.ingest_frame(np.zeros((32, 48, 3), dtype=np.uint8), enforce_rate_limit=False)
        if stream._processing_task:
            await asyncio.wait_for(stream._processing_task, timeout=2)

    async def test_no_publisher_encoder_or_preview_even_with_old_enabled_setting(self):
        with patch.dict(os.environ, {"MEDIAMTX_ENABLED": "true"}), patch("subprocess.Popen", side_effect=AssertionError("publisher created")), patch("app.stream.cv2.imencode", side_effect=AssertionError("preview encoded")):
            stream = self.session()
            await self.submit(stream)
            self.assertFalse(hasattr(stream, "publisher"))
            self.assertIsNone(stream.latest_jpeg)
            self.assertEqual("retired", stream.metrics()["publish_state"])
            self.assertEqual(0, stream.metrics()["viewers"])
            self.assertEqual(0, stream.output_fps)
            self.assertEqual(StreamState.ANALYZING, stream.state)
            self.assertEqual(1, stream.frames_processed)
            stream.alert_runtime.process.assert_called_once()
            args = stream.alert_runtime.process.call_args.kwargs
            self.assertEqual("project-a", args["project_id"])
            self.assertEqual("same-id", args["source_id"])
            await stream.close()

    async def test_yolo_off_never_relays_or_generates_alert(self):
        stream = self.session()
        await stream.set_yolo(False)
        await self.submit(stream)
        stream.detector.infer.assert_not_called()
        stream.alert_runtime.process.assert_not_called()
        self.assertIsNone(stream.latest_jpeg)
        self.assertEqual(StreamState.INGESTING, stream.state)
        await stream.close()

    async def test_evidence_annotation_flag_tracks_actual_frame_without_changing_overlay_policy(self):
        from app.overlay import draw_overlay
        for enabled in (False, True):
            stream = self.session()
            stream.overlay_enabled = enabled
            result = InferenceResult(model_id="fixture", frame_width=48, frame_height=32,
                provides=("BOX",), detections=(Detection(0, "person", .9, NormalizedBox(.1, .2, .3, .4)),))
            stream.detector.infer.return_value = result
            await self.submit(stream)
            args = stream.alert_runtime.process.call_args.kwargs
            self.assertIs(args["evidence_baked_in"], enabled)
            raw = np.zeros((32, 48, 3), dtype=np.uint8)
            expected = draw_overlay(raw, result.detections) if enabled else raw
            np.testing.assert_array_equal(expected, args["frame"])
            await stream.close()

    async def test_real_rule_persists_one_alert_and_evidence_without_live_consumers(self):
        with tempfile.TemporaryDirectory(prefix="m34-analysis-") as folder:
            root = Path(folder)
            url = "sqlite+pysqlite:///" + (root / "alerts.db").as_posix()
            database = DatabaseManager(url)
            Base.metadata.create_all(database.engine)
            events = AlertDispositionStore(database)
            delivered = []
            class Delivery:
                def dispatch(self, event):
                    # The notification must follow persistence, never a raw detection.
                    events.get(event["eventId"], event["projectId"])
                    delivered.append(event["eventId"])
                    return ["test-notification"]
            profile = {"modelVersion": "1", "revision": 1, "alertRules": [{
                "enabled": True, "rawLabel": "person", "eventCode": "PERSON",
                "camera": {"minimumConfidence": 0.5, "minimumConsecutiveFrames": 2,
                           "minimumDwellTimeMs": 0, "cooldownMs": 1000}}]}
            runtime = ServerAlertRuntime(
                model_provider=lambda *args: {"modelId": "fixture", "version": "1"},
                parameter_store=None, event_store=events, delivery_service=Delivery(),
                evidence_root=root / "evidence", profile_provider=lambda *args: profile)
            stream = self.session()
            stream.alert_runtime = runtime
            stream.detector.infer.return_value = InferenceResult(
                model_id="fixture", class_names=("person",), provides=("BOX",),
                detections=(Detection(0, "person", 0.9, NormalizedBox(0.1,0.1,0.2,0.3)),),
                frame_width=48, frame_height=32)
            try:
                await self.submit(stream)
                self.assertEqual([], events.list(project_id="project-a"))
                await self.submit(stream)
                await self.submit(stream)
                self.assertEqual(1, len(delivered))
                event_id = delivered[0]
                saved = events.get(event_id, "project-a")
                self.assertEqual("SERVER_STREAM", saved["origin"])
                self.assertEqual("same-id", saved["streamId"])
                self.assertEqual([], events.list(project_id="project-b"))
                evidence = runtime.evidence_path(event_id, "project-a")
                self.assertIsNotNone(evidence)
                self.assertTrue(evidence.read_bytes().startswith(b"\xff\xd8"))
                self.assertIsNone(runtime.evidence_path(event_id, "project-b"))
                self.assertIsNone(stream.latest_jpeg)
                self.assertEqual(0, stream.active_subscribers)
                reopened = DatabaseManager(url)
                try:
                    self.assertEqual("CONFIRMED", AlertDispositionStore(reopened).get(event_id, "project-a")["state"])
                finally:
                    reopened.close()
            finally:
                await stream.close()
                database.close()

    async def test_missing_or_fallback_model_never_relays_or_alerts(self):
        for unavailable in (True, False):
            stream = self.session()
            if unavailable:
                stream.detector._load_error = "missing"
            else:
                stream.detector.infer.return_value = InferenceResult(fallback_reason="unavailable")
            await self.submit(stream)
            self.assertEqual(1, stream.frames_fallback)
            self.assertEqual(StreamState.ERROR, stream.state)
            self.assertIsNone(stream.latest_jpeg)
            stream.alert_runtime.process.assert_not_called()
            await stream.close()

    async def test_alert_failure_is_visible_and_next_frame_can_recover(self):
        stream = self.session()
        stream.alert_runtime.process.side_effect = RuntimeError("secret connection string")
        await self.submit(stream)
        self.assertEqual("alert persistence or delivery failed", stream.alert_error)
        self.assertNotIn("secret", str(stream.metrics()))
        stream.alert_runtime.process.side_effect = None
        await self.submit(stream)
        self.assertIsNone(stream.alert_error)
        self.assertEqual(2, stream.frames_processed)
        await stream.close()

    async def test_inflight_results_are_discarded_after_disable_reenable_rebind_or_revoke(self):
        for change in ("disable", "reenable", "rebind", "revoke", "close"):
            with self.subTest(change=change):
                stream = self.session()
                entered, release = threading.Event(), threading.Event()
                result = stream.detector.infer.return_value
                def infer(frame):
                    entered.set()
                    if not release.wait(2):
                        raise TimeoutError("test did not release inference")
                    return result
                stream.detector.infer.side_effect = infer
                await stream.ingest_frame(np.zeros((32,48,3), dtype=np.uint8))
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                try:
                    if change in ("disable", "reenable"):
                        await stream.set_yolo(False)
                        if change == "reenable":
                            await stream.set_yolo(True)
                    elif change == "rebind":
                        stream.bind_model(model_id="new", model_path="absent.onnx")
                    elif change == "revoke":
                        stream.model_authorizer = lambda: False
                    else:
                        await stream.close()
                finally:
                    release.set()
                await asyncio.gather(stream._processing_task, return_exceptions=True)
                stream.alert_runtime.process.assert_not_called()
                self.assertIsNone(stream.latest_detections)
                self.assertEqual(0, stream.frames_processed)
                await stream.close()

    async def test_unauthorized_model_skips_inference(self):
        stream = self.session()
        stream.model_authorizer = lambda: False
        await self.submit(stream)
        stream.detector.infer.assert_not_called()
        stream.alert_runtime.process.assert_not_called()
        await stream.close()

    async def test_latest_only_keeps_newest_pending_frame_at_analysis_limit(self):
        stream = self.session()
        await stream.set_max_fps(10)
        gate = asyncio.Event()
        async def wait_slot():
            await gate.wait()
        stream._wait_for_analysis_slot = wait_slot
        for value in (1, 2, 3):
            await stream.ingest_frame(np.full((32,48,3), value, dtype=np.uint8), enforce_rate_limit=False)
            await asyncio.sleep(0)
        self.assertEqual(2, stream.frames_dropped)
        gate.set()
        await asyncio.wait_for(stream._processing_task, 2)
        stream.detector.infer.assert_called_once()
        self.assertEqual(3, int(stream.detector.infer.call_args.args[0][0,0,0]))
        self.assertEqual(3, stream.latest_detections.frame_seq)
        self.assertEqual(1, stream.frames_processed)
        await stream.close()

    async def test_same_stream_id_routes_alerts_to_each_session_project(self):
        first, second = self.session(), self.session()
        second.project_id = "project-b"
        await self.submit(first)
        await self.submit(second)
        self.assertEqual("project-a", first.alert_runtime.process.call_args.kwargs["project_id"])
        self.assertEqual("project-b", second.alert_runtime.process.call_args.kwargs["project_id"])
        await first.close()
        await second.close()

    async def test_closed_session_rejects_new_input(self):
        stream = self.session()
        await stream.close()
        with self.assertRaisesRegex(ValueError, "closed"):
            await self.submit(stream)
        stream.alert_runtime.process.assert_not_called()

    def test_old_media_server_cannot_authorize_read_publish_or_api(self):
        with patch("app.auth._session_user", side_effect=AssertionError("must not authenticate")):
            for action in ("read", "publish", "api"):
                store = Mock()
                with self.assertRaises(HTTPException) as error:
                    authorize_media_read(MediaAuthorizationRequest(action=action, user="aiyolo-service", password="retired-service-token", protocol="rtsp"), store)
                self.assertEqual(403, error.exception.status_code)
                store.get.assert_not_called()
