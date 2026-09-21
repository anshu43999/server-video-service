from __future__ import annotations

import hashlib
import inspect
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


Executor = Callable[..., dict]
TERMINAL_STATES = {"succeeded", "failed", "cancelled"}
BUILTIN_CALIBRATION_ALIASES = {"coco8.yaml"}


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
        builtin_calibration_manifest: Path | None = None,
        timeout_seconds: int,
        max_queued_jobs: int,
        executor: Executor | None = None,
    ) -> None:
        self.root = root.resolve()
        self.jobs_root = self.root / "jobs"
        self.incoming_root = self.root / "incoming"
        self.calibration_root = calibration_root.resolve()
        self.builtin_calibration_manifest = (
            builtin_calibration_manifest.resolve() if builtin_calibration_manifest else None
        )
        self._builtin_runtime_path: Path | None = None
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
                    job.update(
                        status="queued",
                        stage="queued",
                        stageLabel="等待远程转换服务",
                        progress=None,
                        message="服务重启后任务已重新排队",
                        startedAt=None,
                        error=None,
                    )
                    self._persist(job)
                job.setdefault("stage", "completed" if job.get("status") == "succeeded" else job.get("status", "queued"))
                job.setdefault("stageLabel", "远程转换完成" if job.get("status") == "succeeded" else "等待远程转换服务")
                job.setdefault("progress", 100 if job.get("status") == "succeeded" else None)
                job.setdefault("message", job["stageLabel"])
                job.setdefault("startedAt", None)
                job.setdefault("completedAt", None)
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
                    existing.update(
                        status="queued",
                        stage="queued",
                        stageLabel="等待远程转换服务",
                        progress=None,
                        message="重试任务已进入队列",
                        startedAt=None,
                        completedAt=None,
                        error=None,
                        updatedAt=time.time(),
                    )
                    existing["attempt"] = int(existing.get("attempt", 1)) + 1
                    self._persist(existing)
                    self._wake.set()
                    return self._view(existing), True
                return self._view(existing), False
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
                "stage": "queued",
                "stageLabel": "等待远程转换服务",
                "progress": None,
                "message": "任务已进入单 worker 队列",
                "attempt": 1,
                "createdAt": now,
                "updatedAt": now,
                "startedAt": None,
                "completedAt": None,
                "result": None,
                "error": None,
            }
            self._jobs[job_id] = job
            self._idempotency[idempotency_key] = job_id
            self._persist(job)
            self._wake.set()
            return self._view(job), True

    def get(self, job_id: str) -> dict:
        with self._guard:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return self._view(self._jobs[job_id])

    def _view(self, job: dict) -> dict:
        result = json.loads(json.dumps(job))
        if result.get("status") == "queued":
            queued = sorted(
                (item for item in self._jobs.values() if item.get("status") == "queued"),
                key=lambda item: item["createdAt"],
            )
            result["queuePosition"] = next(
                (index + 1 for index, item in enumerate(queued) if item["jobId"] == result["jobId"]),
                None,
            )
        else:
            result["queuePosition"] = None
        return result

    def cancel(self, job_id: str) -> dict:
        with self._guard:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            job = self._jobs[job_id]
            if job["status"] in TERMINAL_STATES:
                return dict(job)
            job["status"] = "cancelled"
            job["stage"] = "cancelled"
            job["stageLabel"] = "转换已取消"
            job["progress"] = None
            job["message"] = "转换任务已取消"
            job["error"] = None
            job["updatedAt"] = time.time()
            job["completedAt"] = job["updatedAt"]
            (self.job_directory(job_id) / "cancel").touch()
            self._persist(job)
            return self._view(job)

    def artifact(self, job_id: str) -> Path:
        job = self.get(job_id)
        path = self.job_directory(job_id) / "android.tflite"
        if job["status"] != "succeeded" or not path.is_file():
            raise FileNotFoundError(job_id)
        return path

    def _persist(self, job: dict) -> None:
        atomic_json(self.job_directory(job["jobId"]) / "job.json", job)

    def _resolve_calibration(self, value: str) -> str:
        if value in BUILTIN_CALIBRATION_ALIASES:
            return self._resolve_builtin_calibration()
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

    def _resolve_builtin_calibration(self) -> str:
        manifest_path = self.builtin_calibration_manifest
        if manifest_path is None or not manifest_path.is_file():
            raise ValueError("builtin_calibration_missing")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("schemaVersion") != 1 or manifest.get("datasetId") != "coco8-dev":
                raise ValueError
            root = manifest_path.parent.resolve()
            entries = manifest.get("files")
            if not isinstance(entries, list) or len(entries) < 2:
                raise ValueError
            fingerprint = hashlib.sha256()
            verified: dict[str, Path] = {}
            for entry in entries:
                relative = Path(str(entry["path"]))
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError
                path = (root / relative).resolve()
                path.relative_to(root)
                if not path.is_file() or path.stat().st_size != int(entry["sizeBytes"]):
                    raise ValueError
                actual = sha256_file(path)
                if actual != str(entry["sha256"]).lower():
                    raise ValueError
                normalized = relative.as_posix()
                fingerprint.update(normalized.encode("utf-8") + b"\0")
                fingerprint.update(actual.encode("ascii") + b"\0")
                verified[normalized] = path
            if fingerprint.hexdigest() != manifest.get("contentSha256"):
                raise ValueError
            yaml_path = str(manifest.get("yamlPath", ""))
            source_dataset = verified.get(yaml_path)
            if source_dataset is None:
                raise ValueError
            return str(self._materialize_builtin_calibration(
                root, entries, source_dataset, str(manifest["contentSha256"])
            ))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("builtin_calibration_invalid") from exc

    def _materialize_builtin_calibration(
        self, source_root: Path, entries: list[dict], source_dataset: Path, content_hash: str
    ) -> Path:
        with self._guard:
            if self._builtin_runtime_path is not None and self._builtin_runtime_path.is_file():
                return self._builtin_runtime_path
            parent = self.root / "builtin-calibration"
            target = parent / content_hash
            staging = parent / f".{content_hash}.{uuid.uuid4().hex}.tmp"
            parent.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True)
            try:
                for entry in entries:
                    relative = Path(str(entry["path"]))
                    source = source_root / relative
                    destination = staging / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
                runtime_dataset = staging / source_dataset.relative_to(source_root)
                yaml_text = runtime_dataset.read_text(encoding="utf-8")
                marker = "__AIYOLO_BUILTIN_CALIBRATION_ROOT__"
                if marker not in yaml_text:
                    raise ValueError("builtin_calibration_yaml_invalid")
                yaml_text = yaml_text.replace(marker, target.as_posix())
                runtime_dataset.write_text(yaml_text, encoding="utf-8")
                shutil.rmtree(target, ignore_errors=True)
                staging.replace(target)
                self._builtin_runtime_path = target / source_dataset.relative_to(source_root)
                return self._builtin_runtime_path
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True)
                raise

    def _execute_worker(
        self, directory: Path, input_size: int, calibration_data: str, timeout: int,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> dict:
        calibration_path = self._resolve_calibration(calibration_data)
        request = {"input_size": input_size, "calibration_data": calibration_path}
        atomic_json(directory / "request.json", request)
        for name in ("result.json", "progress.json", "android.tflite"):
            (directory / name).unlink(missing_ok=True)
        worker = Path(__file__).resolve().parents[1] / "tools" / "conversion_worker.py"
        process = subprocess.Popen(
            [sys.executable, str(worker), "--action", "mobile", "--directory", str(directory),
             "--timeout", str(timeout)],
            cwd=directory,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        progress_path = directory / "progress.json"
        previous = ""
        deadline = time.monotonic() + timeout + 30
        while process.poll() is None:
            previous = self._read_worker_progress(progress_path, progress_callback, previous)
            if time.monotonic() >= deadline:
                process.kill()
                process.wait()
                raise RuntimeError("conversion_timeout")
            time.sleep(0.2)
        self._read_worker_progress(progress_path, progress_callback, previous)
        result_path = directory / "result.json"
        if not result_path.is_file():
            raise RuntimeError("worker_result_missing")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if process.returncode or not result.get("ok"):
            raise RuntimeError("conversion_worker_failed")
        artifact = directory / "android.tflite"
        if not artifact.is_file() or artifact.stat().st_size <= 0:
            raise RuntimeError("artifact_missing")
        actual_hash = sha256_file(artifact)
        if result.get("sha256", "").lower() != actual_hash:
            raise RuntimeError("artifact_hash_mismatch")
        return {**result, "sha256": actual_hash, "sizeBytes": artifact.stat().st_size}

    @staticmethod
    def _read_worker_progress(
        path: Path, callback: Callable[[dict], None] | None, previous: str
    ) -> str:
        if callback is None or not path.is_file():
            return previous
        try:
            raw = path.read_text(encoding="utf-8")
            if raw == previous:
                return previous
            payload = json.loads(raw)
            callback(payload)
            return raw
        except (OSError, ValueError, json.JSONDecodeError):
            return previous

    def _report_progress(self, job_id: str, payload: dict) -> None:
        stage = str(payload.get("stage") or "exporting")
        if not re.fullmatch(r"[a-z0-9_]{1,64}", stage):
            stage = "exporting"
        labels = {
            "loading_model": "正在加载 PT 模型",
            "validating_model": "正在验证 PT 模型",
            "exporting": "正在导出移动端模型",
            "locating_artifact": "正在整理导出产物",
            "verifying_artifact": "正在验证移动端模型",
            "finalizing": "正在整理处理结果",
        }
        progress = payload.get("progress")
        if not isinstance(progress, (int, float)):
            progress = None
        with self._guard:
            current = self._jobs[job_id]
            if current["status"] != "running":
                return
            current.update(
                stage=stage,
                stageLabel=str(payload.get("stageLabel") or labels.get(stage, "远程服务正在转换"))[:100],
                progress=None if progress is None else max(0, min(100, round(progress))),
                message=str(payload.get("message") or labels.get(stage, "远程服务正在转换"))[:300],
                updatedAt=time.time(),
            )
            self._persist(current)

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
                    now = time.time()
                    job.update(
                        status="running",
                        stage="starting",
                        stageLabel="正在启动远程转换",
                        progress=None,
                        message="远程 worker 已接收任务",
                        startedAt=now,
                        completedAt=None,
                        updatedAt=now,
                    )
                    self._active_job_id = job["jobId"]
                    self._persist(job)
            if job is None:
                self._wake.wait(1)
                self._wake.clear()
                continue
            directory = self.job_directory(job["jobId"])
            try:
                parameters = inspect.signature(self.executor).parameters
                arguments = (
                    directory, job["inputSize"], job["calibrationData"], self.timeout_seconds
                )
                if "progress_callback" in parameters:
                    result = self.executor(
                        *arguments,
                        progress_callback=lambda payload: self._report_progress(job["jobId"], payload),
                    )
                else:
                    result = self.executor(*arguments)
                with self._guard:
                    current = self._jobs[job["jobId"]]
                    if current["status"] != "cancelled":
                        now = time.time()
                        current.update(
                            status="succeeded",
                            stage="completed",
                            stageLabel="远程转换完成",
                            progress=100,
                            message="远程转换与产物校验已完成",
                            result=result,
                            error=None,
                            completedAt=now,
                            updatedAt=now,
                        )
                        self._persist(current)
            except Exception as exc:
                with self._guard:
                    current = self._jobs[job["jobId"]]
                    if current["status"] != "cancelled":
                        code = str(exc) if re.fullmatch(r"[a-z0-9_]{1,100}", str(exc)) else "conversion_failed"
                        now = time.time()
                        current.update(
                            status="failed",
                            stage="failed",
                            stageLabel="远程转换失败",
                            progress=None,
                            message="远程转换失败",
                            result=None,
                            error={"code": code, "message": "模型转换失败", "retryable": True},
                            completedAt=now,
                            updatedAt=now,
                        )
                        self._persist(current)
            finally:
                with self._guard:
                    self._active_job_id = None
        with self._guard:
            if self._active_job_id:
                (self.job_directory(self._active_job_id) / "cancel").touch()
