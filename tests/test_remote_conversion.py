import hashlib
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from app.conversion import ConversionConfig, RemoteConversionRunner


ARTIFACT = b"fake-tflite-from-remote"


class RemoteHandler(BaseHTTPRequestHandler):
    uploaded = b""
    auth = None
    idempotency_key = None
    delete_count = 0
    artifact_hash = hashlib.sha256(ARTIFACT).hexdigest()
    terminal_status = "succeeded"

    def do_GET(self):
        if self.path.endswith("/v1/health"):
            return self.reply({"status": "ok", "protocolVersion": 1})
        if self.path.endswith("/artifact"):
            self.send_response(200)
            self.send_header("Content-Length", str(len(ARTIFACT)))
            self.end_headers()
            self.wfile.write(ARTIFACT)
            return
        if "/v1/conversions/remote-1" in self.path:
            result = {
                "labels": ["person", "car"], "sizeBytes": len(ARTIFACT),
                "sha256": self.artifact_hash, "artifactUrl": "/v1/conversions/remote-1/artifact",
            }
            return self.reply({"jobId": "remote-1", "status": self.terminal_status, "result": result})
        self.send_error(404)

    def do_POST(self):
        type(self).auth = self.headers.get("Authorization")
        type(self).idempotency_key = self.headers.get("Idempotency-Key")
        type(self).uploaded = self.rfile.read(int(self.headers["Content-Length"]))
        self.reply({"jobId": "remote-1", "status": "running"}, 202)

    def do_DELETE(self):
        type(self).delete_count += 1
        self.reply({"jobId": "remote-1", "status": "cancelled"})

    def reply(self, value, status=200):
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class FakeLocalVerifier:
    def run_worker(self, config, action, directory, stopping, request=None):
        if action == "check":
            return {"ok": True, "mobile_available": True}
        if action != "verify" or Path(directory, "android.tflite").read_bytes() != ARTIFACT:
            raise AssertionError("artifact was not downloaded before local verification")
        labels = request["expected_labels"]
        return {
            "ok": True, "labels": labels, "input_size": request["input_size"], "warmup": "passed",
            "input": {"name": "input", "shape": [1, 3, 640, 640], "dataType": "float32", "quantization": [0.0, 0]},
            "output": {"name": "output", "shape": [1, len(labels) + 4, 8400], "dataType": "float32", "quantization": [0.0, 0]},
            "quantization": "int8", "ultralytics": "remote-service",
        }


class RemoteConversionTests(unittest.TestCase):
    def setUp(self):
        RemoteHandler.uploaded = b""
        RemoteHandler.auth = None
        RemoteHandler.idempotency_key = None
        RemoteHandler.delete_count = 0
        RemoteHandler.artifact_hash = hashlib.sha256(ARTIFACT).hexdigest()
        RemoteHandler.terminal_status = "succeeded"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), RemoteHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name) / "job-1" / "1"
        self.directory.mkdir(parents=True)
        (self.directory / "source.pt").write_bytes(b"pt-weights")
        self.config = ConversionConfig(
            mode="remote", remote_endpoint=f"http://127.0.0.1:{self.server.server_port}",
            remote_allow_insecure_http=True, remote_token_env="TEST_REMOTE_TOKEN",
            remote_poll_interval_seconds=0.5, python_path="/venv/bin/python",
        )

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    @patch.dict(os.environ, {"TEST_REMOTE_TOKEN": "secret-token"})
    def test_streams_upload_polls_downloads_hashes_and_locally_verifies(self):
        progress = []
        result = RemoteConversionRunner(FakeLocalVerifier()).run(
            self.config, "mobile", self.directory, threading.Event(),
            progress_callback=progress.append,
        )
        self.assertEqual(RemoteHandler.uploaded, b"pt-weights")
        self.assertEqual(RemoteHandler.auth, "Bearer secret-token")
        self.assertRegex(RemoteHandler.idempotency_key, r"^[0-9a-f]{64}$")
        self.assertEqual((self.directory / "android.tflite").read_bytes(), ARTIFACT)
        self.assertEqual(result["labels"], ["person", "car"])
        self.assertEqual(result["remote_job_id"], "remote-1")
        self.assertTrue(any(item["stage"] == "remote_running" for item in progress))
        self.assertTrue(any(item["stage"] == "downloading" and item["progress"] == 100 for item in progress))

    @patch.dict(os.environ, {"TEST_REMOTE_TOKEN": "secret-token"})
    def test_hash_mismatch_is_rejected_and_partial_is_removed(self):
        RemoteHandler.artifact_hash = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            RemoteConversionRunner(FakeLocalVerifier()).run(
                self.config, "mobile", self.directory, threading.Event(),
            )
        self.assertFalse((self.directory / "android.tflite").exists())
        self.assertFalse((self.directory / "android.tflite.part").exists())

    @patch.dict(os.environ, {"TEST_REMOTE_TOKEN": "secret-token"})
    def test_stop_cancels_remote_job(self):
        RemoteHandler.terminal_status = "running"
        stopping = threading.Event()
        stopping.set()
        with self.assertRaisesRegex(RuntimeError, "请求取消"):
            RemoteConversionRunner(FakeLocalVerifier()).run(self.config, "mobile", self.directory, stopping)
        self.assertEqual(RemoteHandler.delete_count, 1)

    def test_missing_token_fails_before_network(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "TEST_REMOTE_TOKEN"):
                RemoteConversionRunner(FakeLocalVerifier()).run(
                    self.config, "mobile", self.directory, threading.Event(),
                )


if __name__ == "__main__":
    unittest.main()
