import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.main as main_module
from app.database import Base, DatabaseManager, StreamConfigRecord
from app.main import CreateStreamRequest, StreamConfigRequest, StreamModelRequest, streams
from app.stream import StreamSession
from app.stream_config import (
    StreamConfiguration,
    StreamConfigConflict,
    StreamConfigStore,
    redact_source_url,
)


ROOT = Path(__file__).resolve().parents[1]


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
        self.assertFalse(columns & {"latest_frame", "websocket_queue", "frames_received", "runtime_metrics"})

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
        created = asyncio.run(main_module.create_stream(CreateStreamRequest(
            stream_id="secure-cam",
            display_name="Secure Camera",
            source_url="rtsp://stream-user:topsecret@camera.local/live?token=also-secret",
            enabled=False,
        )))
        self.assertEqual(created["source_url"], "rtsp://camera.local/live")
        self.assertNotIn("topsecret", str(created))

        updated = asyncio.run(main_module.update_stream_config(
            "secure-cam",
            StreamConfigRequest(confidence=0.42, max_fps=12, yolo_enabled=True, overlay_enabled=False),
        ))
        self.assertEqual(updated["confidence"], 0.42)
        self.assertTrue(main_module.stream_config_store.get("secure-cam").yolo_enabled)

        with patch.object(main_module.model_catalog, "resolve_server_model", return_value=(
            {"modelId": "model-a", "scenario": "site", "purpose": "business", "labels": ["object"], "inputSize": 640},
            ROOT / "models" / "model-a.pt",
        )):
            asyncio.run(main_module.bind_stream_model("secure-cam", StreamModelRequest(model_id="model-a")))
        self.assertEqual(main_module.stream_config_store.get("secure-cam").model_id, "model-a")

        listed = asyncio.run(main_module.list_streams(None))
        self.assertEqual(listed[0]["display_name"], "Secure Camera")
        self.assertNotIn("stream-user", str(listed))
        self.assertNotIn("topsecret", str(listed))
        self.assertNotIn("also-secret", str(listed))

        asyncio.run(main_module.delete_stream("secure-cam"))
        self.assertIsNone(main_module.stream_config_store.get("secure-cam"))

    def test_storage_failure_does_not_leave_runtime_session(self):
        with patch.object(main_module.stream_config_store, "create", side_effect=RuntimeError("db down")):
            with self.assertRaisesRegex(Exception, "503"):
                asyncio.run(main_module.create_stream(CreateStreamRequest(stream_id="partial", enabled=False)))
        self.assertNotIn("partial", streams)

    def test_create_is_idempotent_when_configuration_exists_without_runtime(self):
        request = CreateStreamRequest(stream_id="resume-me", enabled=False)
        first = asyncio.run(main_module.create_stream(request))
        self.assertEqual(first["revision"], 1)
        streams.pop("resume-me")

        second = asyncio.run(main_module.create_stream(request))
        self.assertEqual(second["stream_id"], "resume-me")
        self.assertEqual(second["revision"], 1)
        self.assertIn("resume-me", streams)


if __name__ == "__main__":
    unittest.main()
