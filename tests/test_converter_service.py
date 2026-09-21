from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest

from fastapi.testclient import TestClient

from converter_service.config import ConverterSettings
from converter_service.jobs import JobStore, sha256_file
from converter_service.main import create_app


TOKEN = "converter-test-token-32-characters"
SOURCE = b"fake-ultralytics-pt-weights"
ARTIFACT = b"fake-int8-tflite-artifact"
ROOT = Path(__file__).resolve().parents[1]
BUILTIN_MANIFEST = ROOT / "calibration" / "builtin" / "dev8" / "manifest.json"


def completed_executor(directory: Path, input_size: int, calibration_data: str, timeout: int) -> dict:
    target = directory / "android.tflite"
    target.write_bytes(ARTIFACT)
    return {
        "ok": True,
        "labels": ["person", "car"],
        "input_size": input_size,
        "warmup": "passed",
        "input": {"name": "input", "shape": [1, 3, input_size, input_size], "dataType": "float32", "quantization": [0.0, 0]},
        "output": {"name": "output", "shape": [1, 6, 8400], "dataType": "float32", "quantization": [0.0, 0]},
        "quantization": "int8",
        "calibration": calibration_data,
        "sha256": sha256_file(target),
        "sizeBytes": target.stat().st_size,
    }


class ConverterServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.calibration = self.root / "calibration"
        self.calibration.mkdir()
        (self.calibration / "dataset.yaml").write_text("path: images\n", encoding="utf-8")
        self.store = JobStore(
            self.root / "data", self.calibration,
            builtin_calibration_manifest=BUILTIN_MANIFEST,
            timeout_seconds=30, max_queued_jobs=4, executor=completed_executor,
        )
        config = ConverterSettings(
            token=TOKEN, root=self.root / "data", calibration_root=self.calibration,
            builtin_calibration_manifest=BUILTIN_MANIFEST,
            timeout_seconds=30, max_queued_jobs=4,
        )
        self.client_context = TestClient(create_app(self.store, token=TOKEN, config=config))
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    @staticmethod
    def headers(source: bytes = SOURCE, key: str = "a" * 64) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/octet-stream",
            "Idempotency-Key": key,
            "X-Source-SHA256": hashlib.sha256(source).hexdigest(),
        }

    def wait_for_terminal(self, job_id: str) -> dict:
        for _ in range(100):
            response = self.client.get(
                f"/v1/conversions/{job_id}",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            self.assertEqual(200, response.status_code)
            body = response.json()
            if body["status"] not in {"queued", "running"}:
                return body
            time.sleep(0.01)
        self.fail("converter job did not finish")

    def test_health_requires_bearer_token(self) -> None:
        self.assertEqual(401, self.client.get("/v1/health").status_code)
        response = self.client.get("/v1/health", headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(200, response.status_code)
        self.assertEqual(1, response.json()["protocolVersion"])

    def test_submit_poll_download_and_idempotent_replay(self) -> None:
        response = self.client.post(
            "/v1/conversions?inputSize=640&calibrationData=dataset.yaml",
            content=SOURCE, headers=self.headers(),
        )
        self.assertEqual(202, response.status_code)
        job_id = response.json()["jobId"]
        completed = self.wait_for_terminal(job_id)
        self.assertEqual("succeeded", completed["status"])
        self.assertEqual(hashlib.sha256(ARTIFACT).hexdigest(), completed["result"]["sha256"])
        self.assertNotIn("calibration", completed["result"])
        self.assertNotIn(str(self.root), str(completed))
        artifact = self.client.get(
            completed["result"]["artifactUrl"],
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        self.assertEqual(ARTIFACT, artifact.content)
        replay = self.client.post(
            "/v1/conversions?inputSize=640&calibrationData=dataset.yaml",
            content=SOURCE, headers=self.headers(),
        )
        self.assertEqual(200, replay.status_code)
        self.assertEqual(job_id, replay.json()["jobId"])
        reloaded = JobStore(
            self.root / "data", self.calibration,
            builtin_calibration_manifest=BUILTIN_MANIFEST,
            timeout_seconds=30, max_queued_jobs=4, executor=completed_executor,
        )
        self.assertEqual("succeeded", reloaded.get(job_id)["status"])

    def test_public_status_exposes_stage_and_progress_fields(self) -> None:
        response = self.client.post(
            "/v1/conversions?inputSize=640&calibrationData=dataset.yaml",
            content=SOURCE, headers=self.headers(key="e" * 64),
        )
        body = response.json()
        self.assertIn(body["stage"], {"queued", "starting", "loading_model", "validating_model", "completed"})
        self.assertIn("queuePosition", body)
        completed = self.wait_for_terminal(body["jobId"])
        self.assertEqual("completed", completed["stage"])
        self.assertEqual(100, completed["progress"])
        self.assertIsNotNone(completed["startedAt"])

    def test_hash_mismatch_and_idempotency_conflict_are_rejected(self) -> None:
        bad = self.headers()
        bad["X-Source-SHA256"] = "0" * 64
        response = self.client.post(
            "/v1/conversions?inputSize=640&calibrationData=dataset.yaml",
            content=SOURCE, headers=bad,
        )
        self.assertEqual(422, response.status_code)
        self.assertEqual("source_hash_mismatch", response.json()["code"])
        accepted = self.client.post(
            "/v1/conversions?inputSize=640&calibrationData=dataset.yaml",
            content=SOURCE, headers=self.headers(key="b" * 64),
        )
        self.assertEqual(202, accepted.status_code)
        other = b"different-model"
        conflict = self.client.post(
            "/v1/conversions?inputSize=640&calibrationData=dataset.yaml",
            content=other, headers=self.headers(source=other, key="b" * 64),
        )
        self.assertEqual(409, conflict.status_code)
        self.assertEqual("idempotency_conflict", conflict.json()["code"])

    def test_calibration_must_stay_inside_read_only_mount(self) -> None:
        response = self.client.post(
            "/v1/conversions?inputSize=640&calibrationData=../secret.yaml",
            content=SOURCE, headers=self.headers(key="d" * 64),
        )
        self.assertEqual(422, response.status_code)
        self.assertEqual("invalid_calibration", response.json()["code"])
        self.assertNotIn(str(self.root), response.text)

    def test_builtin_coco8_alias_is_allowed_without_an_arbitrary_path(self) -> None:
        resolved = self.store._resolve_calibration("coco8.yaml")
        runtime = Path(resolved)
        self.assertTrue(runtime.is_file())
        self.assertTrue(runtime.is_relative_to(self.root / "data" / "builtin-calibration"))
        self.assertNotIn("__AIYOLO_BUILTIN_CALIBRATION_ROOT__", runtime.read_text(encoding="utf-8"))
        self.assertEqual(8, len(list((runtime.parent / "images").glob("**/*.jpg"))))
        self.assertEqual(8, len(list((runtime.parent / "labels").glob("**/*.txt"))))
        with self.assertRaisesRegex(ValueError, "calibration_data_not_found"):
            self.store.validate_calibration("other-built-in.yaml")

    def test_builtin_calibration_rejects_missing_or_tampered_assets(self) -> None:
        copied = self.root / "builtin"
        shutil.copytree(BUILTIN_MANIFEST.parent, copied)
        store = JobStore(
            self.root / "tamper-data", self.calibration,
            builtin_calibration_manifest=copied / "manifest.json",
            timeout_seconds=30, max_queued_jobs=1, executor=completed_executor,
        )
        store.validate_calibration("coco8.yaml")
        manifest = json.loads((copied / "manifest.json").read_text(encoding="utf-8"))
        image = copied / manifest["files"][1]["path"]
        image.write_bytes(image.read_bytes() + b"tampered")
        with self.assertRaisesRegex(ValueError, "builtin_calibration_invalid"):
            store.validate_calibration("coco8.yaml")
        missing = JobStore(
            self.root / "missing-data", self.calibration,
            builtin_calibration_manifest=self.root / "missing.json",
            timeout_seconds=30, max_queued_jobs=1, executor=completed_executor,
        )
        with self.assertRaisesRegex(ValueError, "builtin_calibration_missing"):
            missing.validate_calibration("coco8.yaml")

    def test_cancel_is_idempotent_and_hides_artifact(self) -> None:
        started = threading.Event()

        def blocking(directory: Path, _size: int, _calibration: str, _timeout: int) -> dict:
            started.set()
            while not (directory / "cancel").exists():
                time.sleep(0.01)
            raise RuntimeError("cancelled")

        self.client_context.__exit__(None, None, None)
        blocking_store = JobStore(
            self.root / "blocking-data", self.calibration,
            builtin_calibration_manifest=BUILTIN_MANIFEST,
            timeout_seconds=30, max_queued_jobs=4, executor=blocking,
        )
        config = ConverterSettings(
            token=TOKEN, root=self.root / "blocking-data", calibration_root=self.calibration,
            builtin_calibration_manifest=BUILTIN_MANIFEST,
            timeout_seconds=30,
        )
        self.client_context = TestClient(create_app(blocking_store, token=TOKEN, config=config))
        self.client = self.client_context.__enter__()
        response = self.client.post(
            "/v1/conversions?inputSize=320&calibrationData=dataset.yaml",
            content=SOURCE, headers=self.headers(key="c" * 64),
        )
        job_id = response.json()["jobId"]
        self.assertTrue(started.wait(2))
        auth = {"Authorization": f"Bearer {TOKEN}"}
        first = self.client.delete(f"/v1/conversions/{job_id}", headers=auth)
        second = self.client.delete(f"/v1/conversions/{job_id}", headers=auth)
        self.assertEqual("cancelled", first.json()["status"])
        self.assertEqual("cancelled", second.json()["status"])
        self.assertEqual(404, self.client.get(f"/v1/conversions/{job_id}/artifact", headers=auth).status_code)


if __name__ == "__main__":
    unittest.main()
