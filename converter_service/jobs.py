from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable
import uuid


Executor = Callable[[Path, int, str, int], dict]
TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class JobStore:
    def __init__(
        self,
        root: Path,
        calibration_root: Path,
        *,
        timeout_seconds: int,
        max_queued_jobs: int,
        executor: Executor | None = None,
    ) -> None:
        self.root = root.resolve()
        self.jobs_root = self.root / "jobs"
        self.incoming_root = self.root / "incoming"
        self.calibration_root = calibration_root.resolve()
        self.timeout_seconds = timeout_seconds
        self.max_queued_jobs = max_queued_jobs
        self.executor = executor or self._execute_worker
        self._guard = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._jobs: dict[str, dict] = {}
        self._idempotency: dict[str, str] = {}
        self._active_job_id: str | None = None
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.incoming_root.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        for metadata in sorted(self.jobs_root.glob("*/job.json")):
            try:
                job = json.loads(metadata.read_text(encoding="utf-8"))
                job_id = str(job["jobId"])
                key = str(job["idempotencyKey"])
                if not re.fullmatch(r"[0-9a-f]{32}", job_id) or not re.fullmatch(r"[0-9a-f]{64}", key):
                    continue
                if job.get("status") == "running":
                    (metadata.parent / "cancel").unlink(missing_ok=True)
                    job["status"] = "queued"
                    job["error"] = None
                    self._persist(job)
                self._jobs[job_id] = job
                self._idempotency[key] = job_id
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._work, name="model-converter", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        with self._guard:
            active = self._active_job_id
            if active:
                (self.job_directory(active) / "cancel").touch()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=15)
            self._thread = None

    def job_directory(self, job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            raise KeyError(job_id)
        return self.jobs_root / job_id

    def incoming_path(self) -> Path:
        return self.incoming_root / (uuid.uuid4().hex + ".part")

    def validate_calibration(self, value: str) -> None:
        self._resolve_calibration(value)

    def lookup(self, idempotency_key: str, source_hash: str) -> tuple[dict | None, bool]:
        with self._guard:
            job_id = self._idempotency.get(idempotency_key)
            if job_id is None:
                return None, False
            job = self._jobs[job_id]
            return dict(job), job["sourceSha256"] != source_hash

    def submit(
        self,
        source: Path,
        *,
        source_hash: str,
        idempotency_key: str,
        input_size: int,
        calibration_data: str,
    ) -> tuple[dict, bool]:
        with self._guard:
            existing_id = self._idempotency.get(idempotency_key)
            if existing_id is not None:
                existing = self._jobs[existing_id]
                if existing["sourceSha256"] != source_hash:
                    raise ValueError("idempotency_conflict")
                if existing.get("status") == "failed" and existing.get("error", {}).get("retryable"):
                    (self.job_directory(existing_id) / "cancel").unlink(missing_ok=True)
                    existing.update(status="queued", error=None, updatedAt=time.time())
                    existing["attempt"] = int(existing.get("attempt", 1)) + 1
                    self._persist(existing)
                    self._wake.set()
                    return dict(existing), True
                return dict(existing), False
            queued = sum(job.get("status") in {"queued", "running"} for job in self._jobs.values())
            if queued >= self.max_queued_jobs:
                raise OverflowError("queue_full")
            job_id = uuid.uuid4().hex
            directory = self.job_directory(job_id)
            directory.mkdir(parents=True, exist_ok=False)
            source.replace(directory / "source.pt")
            now = time.time()
            job = {
                "jobId": job_id,
                "idempotencyKey": idempotency_key,
                "sourceSha256": source_hash,
                "inputSize": input_size,
                "calibrationData": calibration_data,
                "status": "queued",
                "attempt": 1,
                "createdAt": now,
                "updatedAt": now,
                "result": None,
                "error": None,
            }
            self._jobs[job_id] = job
            self._idempotency[idempotency_key] = job_id
            self._persist(job)
            self._wake.set()
            return dict(job), True

    def get(self, job_id: str) -> dict:
        with self._guard:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return json.loads(json.dumps(self._jobs[job_id]))

    def cancel(self, job_id: str) -> dict:
        with self._guard:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            job = self._jobs[job_id]
            if job["status"] in TERMINAL_STATES:
                return dict(job)
            job["status"] = "cancelled"
            job["error"] = None
            job["updatedAt"] = time.time()
            (self.job_directory(job_id) / "cancel").touch()
            self._persist(job)
            return dict(job)

    def artifact(self, job_id: str) -> Path:
        job = self.get(job_id)
        path = self.job_directory(job_id) / "android.tflite"
        if job["status"] != "succeeded" or not path.is_file():
            raise FileNotFoundError(job_id)
        return path

    def _persist(self, job: dict) -> None:
        atomic_json(self.job_directory(job["jobId"]) / "job.json", job)

    def _resolve_calibration(self, value: str) -> str:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = self.calibration_root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.calibration_root)
        except ValueError as exc:
            raise ValueError("calibration_data_outside_root") from exc
        if not resolved.is_file():
            raise ValueError("calibration_data_not_found")
        return str(resolved)

    def _execute_worker(self, directory: Path, input_size: int, calibration_data: str, timeout: int) -> dict:
        calibration_path = self._resolve_calibration(calibration_data)
        request = {"input_size": input_size, "calibration_data": calibration_path}
        atomic_json(directory / "request.json", request)
        for name in ("result.json", "android.tflite"):
            (directory / name).unlink(missing_ok=True)
        worker = Path(__file__).resolve().parents[1] / "tools" / "conversion_worker.py"
        completed = subprocess.run(
            [sys.executable, str(worker), "--action", "mobile", "--directory", str(directory),
             "--timeout", str(timeout)],
            cwd=directory,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 30,
            check=False,
        )
        result_path = directory / "result.json"
        if not result_path.is_file():
            raise RuntimeError("worker_result_missing")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if completed.returncode or not result.get("ok"):
            raise RuntimeError("conversion_worker_failed")
        artifact = directory / "android.tflite"
        if not artifact.is_file() or artifact.stat().st_size <= 0:
            raise RuntimeError("artifact_missing")
        actual_hash = sha256_file(artifact)
        if result.get("sha256", "").lower() != actual_hash:
            raise RuntimeError("artifact_hash_mismatch")
        return {**result, "sha256": actual_hash, "sizeBytes": artifact.stat().st_size}

    def _work(self) -> None:
        while not self._stop.is_set():
            with self._guard:
                queued = sorted(
                    (job for job in self._jobs.values() if job["status"] == "queued"),
                    key=lambda item: item["createdAt"],
                )
                job = queued[0] if queued else None
                if job is not None:
                    (self.job_directory(job["jobId"]) / "cancel").unlink(missing_ok=True)
                    job["status"] = "running"
                    job["updatedAt"] = time.time()
                    self._active_job_id = job["jobId"]
                    self._persist(job)
            if job is None:
                self._wake.wait(1)
                self._wake.clear()
                continue
            directory = self.job_directory(job["jobId"])
            try:
                result = self.executor(
                    directory, job["inputSize"], job["calibrationData"], self.timeout_seconds
                )
                with self._guard:
                    current = self._jobs[job["jobId"]]
                    if current["status"] != "cancelled":
                        current.update(
                            status="succeeded",
                            result=result,
                            error=None,
                            updatedAt=time.time(),
                        )
                        self._persist(current)
            except Exception as exc:
                with self._guard:
                    current = self._jobs[job["jobId"]]
                    if current["status"] != "cancelled":
                        code = str(exc) if re.fullmatch(r"[a-z0-9_]{1,100}", str(exc)) else "conversion_failed"
                        current.update(
                            status="failed",
                            result=None,
                            error={"code": code, "message": "模型转换失败", "retryable": True},
                            updatedAt=time.time(),
                        )
                        self._persist(current)
            finally:
                with self._guard:
                    self._active_job_id = None
        with self._guard:
            if self._active_job_id:
                (self.job_directory(self._active_job_id) / "cancel").touch()
