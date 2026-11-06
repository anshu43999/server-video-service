import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app.main as main_module
from app.database import Base, DatabaseManager, StreamConfigRecord
from app.config import Settings
from app.main import CreateStreamRequest, StreamConfigRequest, StreamModelRequest, streams
from app.stream import StreamSession
from app.stream_config import (
    StreamConfiguration,
    StreamConfigConflict,
    StreamConfigStore,
    redact_source_url,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_CONTEXT = SimpleNamespace(project_id="00000000-0000-0000-0000-000000000001")
SCENE_SELECTION = {"scene_id": "safety", "plan_id": "pc-video", "scene_revision": 3}


def resolved_stream_plan(_project_id, scene_id, plan_id, revision):
    return {"sceneId": scene_id, "planId": plan_id, "revision": revision, "execution": "single",
            "members": [{"modelId": "model-a", "version": "1.0.0", "target": "pc",
                         "parameterSnapshot": {"modelId": "model-a", "modelVersion": "1.0.0", "platform": "server",
                                               "detection": {"confidenceThreshold": 0.42, "iouThreshold": 0.45,
                                                             "maxDetections": 100}}}]}


def configuration(stream_id: str = "camera-1") -> StreamConfiguration:
    return StreamConfiguration(
        stream_id=stream_id,
        display_name="North Gate Camera",
        source_type="rtsp",
        source_url="rtsp://operator:secret@10.0.0.8:8554/live?token=hidden",
        model_id=None,
        yolo_enabled=False,
        confidence=0.25,
        max_fps=20.0,
        overlay_enabled=True,
    )


class StreamConfigStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".test-db")
        self.path = Path(self.temp.name) / "streams.db"
        self.database = DatabaseManager(f"sqlite+pysqlite:///{self.path.as_posix()}")
        Base.metadata.create_all(self.database.engine)

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def test_crud_survives_store_recreation_and_redacts_credentials(self):
        store = StreamConfigStore(self.database)
        created = store.create(configuration())
        self.assertEqual(created.revision, 1)
        self.assertEqual(created.public()["source_url"], "rtsp://10.0.0.8:8554/live")
        with self.assertRaises(StreamConfigConflict):
            store.create(configuration())

        updated = store.update("camera-1", yolo_enabled=True, confidence=0.61, enabled=False)
        self.assertEqual(updated.revision, 2)

        reopened_database = DatabaseManager(self.database.url)
        reopened = StreamConfigStore(reopened_database)
        loaded = reopened.get("camera-1")
        self.assertIsNotNone(loaded)
        self.assertTrue(loaded.yolo_enabled)
        self.assertEqual(loaded.confidence, 0.61)
        self.assertFalse(loaded.enabled)
        self.assertTrue(reopened.delete("camera-1"))
        self.assertIsNone(reopened.get("camera-1"))
        reopened_database.close()

    def test_schema_contains_only_control_plane_fields(self):
        columns = {column.name for column in StreamConfigRecord.__table__.columns}
        self.assertIn("source_url", columns)
        self.assertIn("model_id", columns)
        self.assertTrue({"scene_id", "plan_id", "scene_revision"}.issubset(columns))
        self.assertFalse(columns & {"latest_frame", "websocket_queue", "frames_received", "runtime_metrics"})

    def test_retirement_preserves_legacy_rows_all_fields_and_revisions(self):
        timestamp = datetime(2026, 9, 14, 8, 30, tzinfo=timezone.utc)
        with self.database.session() as session:
            for project, source_type, enabled in (("project-a", "rtsp", True), ("project-b", "websocket", False)):
                session.add(StreamConfigRecord(
                    project_id=project, stream_id="legacy-shared", display_name="Legacy Camera",
                    source_type=source_type, source_url="rtsp://user:secret@camera/live" if enabled else None,
                    model_id="legacy-model", model_version="1.2.3", yolo_enabled=True,
                    confidence=0.61, max_fps=13.0, overlay_enabled=False, enabled=enabled,
                    revision=7, created_at=timestamp, updated_at=timestamp))
        before = [asdict(row) for row in StreamConfigStore(self.database).list_all()]
        with patch.dict(os.environ, {"MEDIAMTX_ENABLED": "true", "MAX_OUTPUT_SUBSCRIBERS": "legacy"}):
            self.assertNotIn("mediamtx_enabled", Settings(_env_file=None).model_dump())
            reopened = DatabaseManager(self.database.url)
            try:
                after = [asdict(row) for row in StreamConfigStore(reopened).list_all()]
                self.assertEqual(before, after)
                self.assertEqual(2, len(after))
                self.assertEqual({7}, {row["revision"] for row in after})
                self.assertEqual({"rtsp", "websocket"}, {row["source_type"] for row in after})
            finally:
                reopened.close()

    def test_same_stream_id_is_independent_across_projects(self):
        store = StreamConfigStore(self.database)
        first = configuration("shared")
        second = StreamConfiguration(**{**first.__dict__, "project_id": "project-b"})
        store.create(first)
        store.create(second)

        self.assertEqual(2, len(store.list_all()))
        self.assertEqual(["shared"], [item.stream_id for item in store.list(first.project_id)])
        self.assertEqual("project-b", store.get("shared", "project-b").project_id)
        store.update("shared", project_id="project-b", display_name="Project B Camera")
        self.assertEqual("North Gate Camera", store.get("shared", first.project_id).display_name)
        self.assertEqual("Project B Camera", store.get("shared", "project-b").display_name)

    def test_redaction_handles_ipv6_and_never_returns_userinfo_or_query(self):
        value = redact_source_url("rtsps://name:password@[2001:db8::1]:7441/cam?api_key=secret")
        self.assertEqual(value, "rtsps://[2001:db8::1]:7441/cam")

    def test_pull_error_redacts_rtsp_credentials(self):
        class ClosedCapture:
            def isOpened(self):
                return False

            def release(self):
                return None

        async def exercise():
            stream = StreamSession("redacted", "rtsp://name:password@camera.local/live?token=secret")
            with patch("app.stream._open_video_capture", return_value=ClosedCapture()):
                await stream.start()
                for _ in range(20):
                    if stream.last_error:
                        break
                    await asyncio.sleep(0.01)
                await stream.close()
            return stream.last_error

        error = asyncio.run(exercise())
        self.assertIn("rtsp://camera.local/live", error)
        self.assertNotIn("name", error)
        self.assertNotIn("password", error)
        self.assertNotIn("secret", error)


class StreamConfigApiPersistenceTests(unittest.TestCase):
    def setUp(self):
        streams.clear()
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".test-db")
        self.path = Path(self.temp.name) / "api-streams.db"
        self.database = DatabaseManager(f"sqlite+pysqlite:///{self.path.as_posix()}")
        Base.metadata.create_all(self.database.engine)
        self.old_store = main_module.stream_config_store
        main_module.stream_config_store = StreamConfigStore(self.database)

    def tearDown(self):
        for stream in list(streams.values()):
            asyncio.run(stream.close())
        streams.clear()
        main_module.stream_config_store = self.old_store
        self.database.close()
        self.temp.cleanup()

    def test_create_patch_bind_list_and_delete_persist(self):
        with patch.object(main_module, "_resolve_stream_plan", side_effect=resolved_stream_plan), \
                patch.object(main_module, "_bind_registered_model", return_value={"modelId": "model-a"}):
            created = asyncio.run(main_module.create_stream(CreateStreamRequest(
                stream_id="secure-cam",
                display_name="Secure Camera",
                source_url="rtsp://stream-user:topsecret@camera.local/live?token=also-secret",
                sceneId="safety", planId="pc-video", sceneRevision=3,
                enabled=False,
            ), PROJECT_CONTEXT))
        self.assertEqual(created["source_url"], "rtsp://camera.local/live")
        self.assertNotIn("topsecret", str(created))

        with patch.object(main_module.model_catalog, "resolve_server_model", return_value=(
            {"modelId": "model-a", "scenario": "site", "purpose": "business", "labels": ["object"], "inputSize": 640},
            ROOT / "models" / "model-a.pt",
        )), \
            patch.object(main_module.project_model_assignments, "snapshot", return_value={
                "detection": {"confidenceThreshold": 0.42, "iouThreshold": 0.45, "maxDetections": 100},
                "alertRules": [], "modelVersion": "1.0.0", "platform": "server", "revision": 1}):
            with patch.object(main_module, "_resolve_stream_plan", side_effect=resolved_stream_plan):
                asyncio.run(main_module.bind_stream_model(
                    "secure-cam", StreamModelRequest(sceneId="safety", planId="pc-video", sceneRevision=3), PROJECT_CONTEXT
                ))
            with patch.object(main_module, "_resolve_stream_plan", side_effect=resolved_stream_plan):
                updated = asyncio.run(main_module.update_stream_config(
                    "secure-cam",
                    StreamConfigRequest(confidence=0.42, max_fps=12, yolo_enabled=True, overlay_enabled=False),
                    PROJECT_CONTEXT,
                ))
        self.assertEqual(updated["confidence"], 0.42)
        self.assertTrue(main_module.stream_config_store.get("secure-cam").yolo_enabled)
        self.assertEqual(main_module.stream_config_store.get("secure-cam").model_version, "1.0.0")
        self.assertEqual(main_module.stream_config_store.get("secure-cam").model_id, "model-a")
        self.assertEqual(main_module.stream_config_store.get("secure-cam").scene_id, "safety")
        self.assertEqual(main_module.stream_config_store.get("secure-cam").plan_id, "pc-video")
        self.assertEqual(main_module.stream_config_store.get("secure-cam").scene_revision, 3)

        listed = asyncio.run(main_module.list_streams(PROJECT_CONTEXT))
        self.assertEqual(listed[0]["display_name"], "Secure Camera")
        self.assertNotIn("stream-user", str(listed))
        self.assertNotIn("topsecret", str(listed))
        self.assertNotIn("also-secret", str(listed))

        asyncio.run(main_module.delete_stream("secure-cam", PROJECT_CONTEXT))
        self.assertIsNone(main_module.stream_config_store.get("secure-cam"))

    def test_create_requires_explicit_scene_plan_and_revision(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            CreateStreamRequest(stream_id="no-plan", enabled=False)
        with self.assertRaises(ValidationError):
            StreamModelRequest(model_id="helmet")
        with self.assertRaises(ValidationError):
            StreamConfigRequest(model_id="helmet")

    def test_stream_selection_resolves_exact_pc_video_revision(self):
        from fastapi import HTTPException
        with patch.object(main_module.project_scenes, "resolve_plan", return_value={
            "sceneId": "safety", "planId": "pc-video", "revision": 3, "execution": "single",
            "members": [{"modelId": "model-a", "version": "1.0.0", "target": "pc"}],
        }) as resolver:
            result = main_module._resolve_stream_plan(PROJECT_CONTEXT.project_id, "safety", "pc-video", 3)
        self.assertEqual(result["revision"], 3)
        request = resolver.call_args.args[3]
        self.assertEqual((request.target, request.inputType, request.expectedRevision), ("pc", "video", 3))

        with patch.object(main_module.project_scenes, "resolve_plan", return_value={
            "sceneId": "safety", "planId": "pc-video", "revision": 3, "execution": "sync",
            "members": [{}, {}],
        }):
            with self.assertRaises(HTTPException) as raised:
                main_module._resolve_stream_plan(PROJECT_CONTEXT.project_id, "safety", "pc-video", 3)
        self.assertEqual(raised.exception.detail["code"], "stream_plan_not_supported")

        with patch.object(main_module.project_scenes, "resolve_plan", side_effect=HTTPException(
                409, detail={"code": "revision_conflict"})):
            with self.assertRaises(HTTPException) as raised:
                main_module._resolve_stream_plan(PROJECT_CONTEXT.project_id, "safety", "pc-video", 2)
        self.assertEqual(raised.exception.detail["code"], "revision_conflict")

    def test_storage_failure_does_not_leave_runtime_session(self):
        with patch.object(main_module, "_resolve_stream_plan", side_effect=resolved_stream_plan), \
                patch.object(main_module, "_bind_registered_model", return_value={}), \
                patch.object(main_module.stream_config_store, "create", side_effect=RuntimeError("db down")):
            with self.assertRaisesRegex(Exception, "503"):
                asyncio.run(main_module.create_stream(
                    CreateStreamRequest(stream_id="partial", sceneId="safety", planId="pc-video",
                                        sceneRevision=3, enabled=False), PROJECT_CONTEXT
                ))
        self.assertNotIn("partial", streams)

    def test_create_is_idempotent_when_configuration_exists_without_runtime(self):
        request = CreateStreamRequest(stream_id="resume-me", sceneId="safety", planId="pc-video",
                                      sceneRevision=3, enabled=False)
        with patch.object(main_module, "_resolve_stream_plan", side_effect=resolved_stream_plan), \
                patch.object(main_module, "_bind_registered_model", return_value={"modelId": "model-a"}):
            first = asyncio.run(main_module.create_stream(request, PROJECT_CONTEXT))
        self.assertEqual(first["revision"], 1)
        streams.pop("resume-me")

        async def restore(_configuration):
            return StreamSession("resume-me", None, project_id=PROJECT_CONTEXT.project_id)
        with patch.object(main_module, "_resolve_stream_plan", side_effect=resolved_stream_plan), \
                patch.object(main_module, "_bind_registered_model", return_value={"modelId": "model-a"}), \
                patch.object(main_module, "_session_from_configuration", side_effect=restore):
            second = asyncio.run(main_module.create_stream(request, PROJECT_CONTEXT))
        self.assertEqual(second["stream_id"], "resume-me")
        self.assertEqual(second["revision"], 1)
        self.assertIn("resume-me", streams)


if __name__ == "__main__":
    unittest.main()
