import asyncio
import tempfile
import unittest
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from fastapi import HTTPException

import app.main as main_module
from app.config import settings
from app.database import Base, DatabaseManager
from app.main import app, streams
from app.stream_config import StreamConfiguration, StreamConfigStore
from app.project_model_assignments import ProjectModelAssignments
from app.project_business import _memory_model_assignments
from app.project_auth import set_memory_project, reset_memory_project_authorization_for_tests


ROOT = Path(__file__).resolve().parents[1]
PROJECT_CONTEXT = SimpleNamespace(project_id="00000000-0000-0000-0000-000000000001")


def resolved_stream_plan(project_id, scene_id, plan_id, revision):
    return {"projectId": project_id, "sceneId": scene_id, "planId": plan_id, "revision": revision,
            "execution": "single", "members": [{"modelId": "model-b", "version": "1.0.0", "target": "pc",
                "parameterSnapshot": {"modelId": "model-b", "modelVersion": "1.0.0", "platform": "server",
                                      "detection": {"confidenceThreshold": 0.47, "iouThreshold": 0.45,
                                                    "maxDetections": 100}}}]}


def config(
    stream_id: str,
    *,
    enabled: bool,
    source_url: str | None = None,
    yolo_enabled: bool = False,
) -> StreamConfiguration:
    return StreamConfiguration(
        stream_id=stream_id,
        display_name=f"Camera {stream_id}",
        source_type="rtsp" if source_url else "websocket",
        source_url=source_url,
        model_id="model-b",
        model_version="1.0.0",
        scene_id="safety",
        plan_id="pc-live",
        scene_revision=1,
        yolo_enabled=yolo_enabled,
        confidence=0.47,
        max_fps=13.0,
        overlay_enabled=False,
        enabled=enabled,
    )


class StreamRestartRecoveryTests(unittest.TestCase):
    def setUp(self):
        streams.clear()
        main_module.stream_restore_errors.clear()
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".test-db")
        self.path = Path(self.temp.name) / "restart.db"
        self.database = DatabaseManager(f"sqlite+pysqlite:///{self.path.as_posix()}")
        Base.metadata.create_all(self.database.engine)
        self.old_store = main_module.stream_config_store
        main_module.stream_config_store = StreamConfigStore(self.database)
        set_memory_project(PROJECT_CONTEXT.project_id, "default")
        self.addCleanup(reset_memory_project_authorization_for_tests)
        assignment = {"modelId": "model-b", "modelVersion": "1.0.0", "enabled": True,
                      "parameterPlatform": "server", "scenario": "test", "parameterSnapshot": {
                          "modelId": "model-b", "modelVersion": "1.0.0", "platform": "server", "revision": 0,
                          "detection": {"confidenceThreshold": 0.47, "iouThreshold": 0.45, "maxDetections": 100},
                          "alertRules": []}}
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch.dict(_memory_model_assignments,
                                              {(PROJECT_CONTEXT.project_id, "test"): assignment}, clear=True))
        self.patches.enter_context(patch.object(main_module, "project_model_assignments",
                     ProjectModelAssignments(None, main_module.model_catalog, main_module.model_parameter_store)))
        self.patches.enter_context(patch.object(main_module, "_resolve_stream_plan", side_effect=resolved_stream_plan))
        self.patches.enter_context(patch.object(main_module.model_catalog, "resolve_server_model",
                                                return_value=({"modelId": "model-b", "version": "1.0.0"}, ROOT / "models" / "model-b.pt")))
        self.patches.enter_context(patch.object(main_module.project_model_assignments, "snapshot", return_value={
            "detection": {"confidenceThreshold": 0.47, "iouThreshold": 0.45, "maxDetections": 100},
            "alertRules": [], "modelVersion": "1.0.0", "platform": "server", "revision": 0,
        }))

    def tearDown(self):
        async def close_streams():
            await asyncio.gather(*(stream.close() for stream in streams.values()), return_exceptions=True)

        asyncio.run(close_streams())
        streams.clear()
        main_module.stream_restore_errors.clear()
        main_module.stream_config_store = self.old_store
        self.database.close()
        self.temp.cleanup()

    def test_restart_restores_only_enabled_stream_and_keeps_parameters(self):
        main_module.stream_config_store.create(config("enabled", enabled=True, yolo_enabled=True))
        main_module.stream_config_store.create(config("disabled", enabled=False))
        before = main_module.stream_config_store.list_all()

        with patch("app.detector.YoloDetector._load"), patch.object(main_module.model_catalog, "resolve_server_model", return_value=(
            {"modelId": "model-b", "version": "1.0.0"}, ROOT / "models" / "model-b.pt")):
            asyncio.run(main_module.restore_stream_sessions())

        self.assertIn("enabled", streams)
        self.assertNotIn("disabled", streams)
        restored = streams["enabled"]
        self.assertTrue(restored.yolo_enabled)
        self.assertEqual(restored.detector.confidence, 0.47)
        self.assertEqual(restored.max_fps, 13.0)
        self.assertFalse(restored.overlay_enabled)
        self.assertEqual("1.0.0", restored.model_version)
        self.assertEqual(before, main_module.stream_config_store.list_all())
        self.assertFalse(hasattr(restored, "publisher"))

        listed = asyncio.run(main_module.list_streams(PROJECT_CONTEXT))
        by_id = {item["stream_id"]: item for item in listed}
        self.assertTrue(by_id["enabled"]["runtime_available"])
        self.assertEqual(by_id["enabled"]["configuration_state"], "enabled")
        self.assertFalse(by_id["disabled"]["runtime_available"])
        self.assertEqual(by_id["disabled"]["runtime_state"], "disabled")

    def test_rtsp_failure_is_nonfatal_redacted_and_keeps_retry_task(self):
        class ClosedCapture:
            def isOpened(self):
                return False

            def release(self):
                return None

        source = "rtsp://operator:password@camera.local/live?token=secret"
        main_module.stream_config_store.create(config("retry", enabled=True, source_url=source))

        async def restore_and_wait():
            with patch("app.stream._open_video_capture", return_value=ClosedCapture()):
                await main_module.restore_stream_sessions()
                for _ in range(30):
                    if streams["retry"].last_error:
                        break
                    await asyncio.sleep(0.01)
                restored = streams["retry"]
                return str(restored.state), restored._pull_task is not None and not restored._pull_task.done(), restored.last_error

        state, retrying, error = asyncio.run(restore_and_wait())
        self.assertEqual(state, "error")
        self.assertTrue(retrying)
        self.assertNotIn("operator", error)
        self.assertNotIn("password", error)
        self.assertNotIn("secret", error)

    def test_disabled_stream_can_be_updated_bound_and_deleted_without_runtime(self):
        main_module.stream_config_store.create(config("offline", enabled=False))
        updated = asyncio.run(main_module.update_stream_config(
            "offline",
            main_module.StreamConfigRequest(display_name="Offline Camera"),
            PROJECT_CONTEXT,
        ))
        self.assertEqual(updated["confidence"], 0.47)
        self.assertFalse(updated["runtime_available"])

        with patch.object(main_module.model_catalog, "get", return_value={"modelId": "model-b", "name": "Model B", "version": "1.0.0"}):
            bound = asyncio.run(main_module.bind_stream_model(
                "offline", main_module.StreamModelRequest(sceneId="safety", planId="pc-live", sceneRevision=1), PROJECT_CONTEXT
            ))
        self.assertEqual(bound["model"]["modelId"], "model-b")
        self.assertEqual(main_module.stream_config_store.get("offline").model_id, "model-b")

        asyncio.run(main_module.delete_stream("offline", PROJECT_CONTEXT))
        asyncio.run(main_module.restore_stream_sessions())
        self.assertIsNone(main_module.stream_config_store.get("offline"))
        self.assertNotIn("offline", streams)

    def test_stream_can_be_disabled_and_enabled_repeatedly(self):
        main_module.stream_config_store.create(config("cycle", enabled=True))
        asyncio.run(main_module.restore_stream_sessions())

        for _ in range(2):
            disabled = asyncio.run(main_module.update_stream_config(
                "cycle", main_module.StreamConfigRequest(enabled=False), PROJECT_CONTEXT
            ))
            self.assertFalse(disabled["enabled"])
            self.assertTrue(streams["cycle"].closed)

            enabled = asyncio.run(main_module.update_stream_config(
                "cycle", main_module.StreamConfigRequest(enabled=True), PROJECT_CONTEXT
            ))
            self.assertTrue(enabled["enabled"])
            self.assertTrue(enabled["runtime_available"])
            self.assertFalse(streams["cycle"].closed)

    def test_enable_failure_rolls_persisted_state_back_to_disabled(self):
        main_module.stream_config_store.create(config("broken", enabled=False))
        with patch("app.main._session_from_configuration", side_effect=RuntimeError("start failed")):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(main_module.update_stream_config(
                    "broken", main_module.StreamConfigRequest(enabled=True), PROJECT_CONTEXT
                ))
        self.assertEqual(raised.exception.status_code, 503)
        self.assertFalse(main_module.stream_config_store.get("broken").enabled)
        self.assertNotIn("broken", streams)

    def test_concurrent_updates_are_serialized_by_revision(self):
        store = StreamConfigStore()
        store.create(config("concurrent", enabled=False))
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(
                lambda value: store.update("concurrent", confidence=0.2 + value / 1000),
                range(20),
            ))
        self.assertEqual(store.get("concurrent").revision, 21)

    def test_persisted_model_binding_blocks_model_uninstall(self):
        bound = config("bound-offline", enabled=False)
        main_module.stream_config_store.create(StreamConfiguration(
            **{**bound.__dict__, "model_id": "protected-model"}
        ))
        removal = main_module._model_removal()
        with patch.object(removal, "_release", return_value=({}, {"version": "1.0.0", "lifecycleRevision": 1})), \
                patch.object(removal.assignments, "references", return_value=[]), \
                patch.object(removal.scenes, "references", return_value=[]), \
                patch.object(removal.catalog, "release_key", return_value="inactive"), \
                patch.object(removal.catalog, "_resolve_active_reference", return_value=None):
            impact = removal._impact("protected-model", None)
        self.assertEqual(impact["dependentCounts"]["streams"], 1)
        self.assertFalse(impact["safeToRemove"])

    def test_persisted_listing_still_requires_authentication(self):
        main_module.stream_config_store.create(config("protected", enabled=False))
        old_admin = settings.admin_token
        settings.admin_token = "restart-test-admin"
        try:
            with patch.object(main_module.database, "verify_schema", return_value={"status": "ok"}), \
                    patch.object(main_module.conversion_service, "start"), \
                    patch.object(main_module.conversion_service, "close"):
                with TestClient(app) as client:
                    self.assertEqual(client.get("/aiyoloapi/streams").status_code, 401)
                    response = client.get(
                        "/aiyoloapi/streams",
                        headers={
                            "X-Admin-Token": "restart-test-admin",
                            "X-Project-Id": PROJECT_CONTEXT.project_id,
                        },
                    )
                    self.assertEqual(response.status_code, 401)
        finally:
            settings.admin_token = old_admin


if __name__ == "__main__":
    unittest.main()
