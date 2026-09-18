"""Persistent, single-worker model jobs. Conversion never runs on the ASGI loop."""
from __future__ import annotations

import json
import hashlib
import http.client
import os
import re
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import urlsplit
from urllib.parse import urlencode

from pydantic import BaseModel, Field, field_validator, model_validator

from sqlalchemy import select

from .database import ConversionConfigRecord, ConversionJobRecord, DatabaseManager

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConversionConfig(BaseModel):
    mode: Literal["wsl", "local", "remote"] = "wsl"
    distribution: str = Field(default="Ubuntu", min_length=1, max_length=100)
    python_path: str = Field(default="", max_length=512)
    input_size: Literal[320, 416, 640] = 640
    calibration_data: str = Field(default="", max_length=512)
    timeout_seconds: int = Field(default=1800, ge=30, le=7200)
    auto_convert: bool = False
    remote_endpoint: str = Field(default="", max_length=512)
    remote_token_env: str = Field(default="AIYOLO_REMOTE_CONVERSION_TOKEN", max_length=100)
    remote_allow_insecure_http: bool = False
    remote_poll_interval_seconds: float = Field(default=2.0, ge=0.5, le=30.0)
    remote_verifier_mode: Literal["wsl", "local"] = "wsl"

    @field_validator("distribution", "python_path", "calibration_data", "remote_endpoint", "remote_token_env")
    @classmethod
    def safe_argument(cls, value: str) -> str:
        value = value.strip()
        if any(ord(ch) < 32 for ch in value) or value.startswith("-"):
            raise ValueError("配置不能含控制字符或以 - 开头")
        return value

    @model_validator(mode="after")
    def validate_remote(self):
        if self.mode != "remote":
            return self
        endpoint = urlsplit(self.remote_endpoint)
        allowed_schemes = {"https"} | ({"http"} if self.remote_allow_insecure_http else set())
        if endpoint.scheme.lower() not in allowed_schemes or not endpoint.hostname:
            raise ValueError("远程转换地址必须是包含主机的 HTTPS URL")
        if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise ValueError("远程转换地址不能包含凭据、查询参数或片段")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,99}", self.remote_token_env):
            raise ValueError("远程转换令牌环境变量名无效")
        if not self.python_path:
            raise ValueError("远程转换必须配置 local/WSL Python 用于本地复验")
        return self


class ConversionPreflightError(ValueError):
    """The configured conversion environment is not reachable right now."""


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


def wsl_path(path: Path) -> str:
    text = str(path.resolve())
    match = re.fullmatch(r"([A-Za-z]):[\\/](.*)", text)
    if not match:
        raise ValueError("WSL 模式要求工程位于本机盘符目录中")
    return f"/mnt/{match[1].lower()}/" + match[2].replace("\\", "/")


class ProcessRunner:
    def preflight(self, config: ConversionConfig) -> dict:
        """Run a cheap environment probe before queueing WSL work.

        A queued worker cannot provide a useful error when the WSL service is
        inaccessible: wsl.exe may exit with the unsigned DWORD value
        4294967295 and never start Python. Probe the same distribution and
        interpreter synchronously so callers get an actionable response.
        """
        if config.mode != "wsl":
            return {"ok": True, "mode": config.mode}
        command = ["wsl.exe", "--distribution", config.distribution,
                   "--exec", config.python_path, "--version"]
        try:
            completed = subprocess.run(
                command, cwd=PROJECT_ROOT, shell=False,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=15, check=False,
            )
        except FileNotFoundError as exc:
            raise ConversionPreflightError("未找到 wsl.exe，请启用 WSL 后重试") from exc
        except subprocess.TimeoutExpired as exc:
            raise ConversionPreflightError("WSL 连通性检测超时，请确认 WSL 服务已启动") from exc
        output = self._decode_probe_output(completed.stdout)
        if completed.returncode != 0:
            code = completed.returncode if completed.returncode >= 0 else completed.returncode + 2**32
            detail = output.strip()[-500:] if output.strip() else "无诊断输出"
            raise ConversionPreflightError(
                f"WSL 连通性检测失败（退出码 {code}）：{detail}。"
                "请确认 WSL 服务和 Ubuntu 发行版可用后重试"
            )
        return {"ok": True, "mode": "wsl", "distribution": config.distribution,
                "python": output.strip() or config.python_path}

    @staticmethod
    def _decode_probe_output(payload: bytes | str | None) -> str:
        if isinstance(payload, str):
            return payload
        if not payload:
            return ""
        for encoding in ("utf-8", "utf-16", "gb18030"):
            try:
                text = payload.decode(encoding)
                if "\x00" not in text:
                    return text
            except UnicodeDecodeError:
                continue
        return payload.decode("utf-8", errors="replace")

    def command(self, config: ConversionConfig, action: str, directory: Path) -> list[str]:
        if config.mode == "remote":
            # Secret-free validation marker. The HTTP adapter handles execution.
            return ["remote-conversion", config.remote_endpoint, action]
        if not config.python_path:
            raise ValueError("请先配置转换虚拟环境的 Python 路径")
        script = PROJECT_ROOT / "tools" / "conversion_worker.py"
        args = ["--action", action, "--timeout", str(60 if action == "check" else config.timeout_seconds)]
        if config.mode == "wsl":
            if not config.python_path.startswith("/"):
                raise ValueError("WSL Python 必须使用 Linux 绝对路径")
            return ["wsl.exe", "--distribution", config.distribution, "--exec", config.python_path,
                    wsl_path(script), "--directory", wsl_path(directory), *args]
        executable = Path(config.python_path)
        if not executable.is_absolute() or not executable.is_file():
            raise ValueError("本机 Python 路径不存在或不是绝对路径")
        return [str(executable), str(script), "--directory", str(directory.resolve()), *args]

    def run(self, config: ConversionConfig, action: str, directory: Path,
            stopping: threading.Event) -> dict:
        if config.mode == "remote":
            return RemoteConversionRunner(self).run(config, action, directory, stopping)
        return self.run_worker(config, action, directory, stopping)

    def run_worker(self, config: ConversionConfig, action: str, directory: Path,
                   stopping: threading.Event, request: dict | None = None) -> dict:
        directory.mkdir(parents=True, exist_ok=True)
        atomic_json(directory / "request.json", request or config.model_dump())
        result_path = directory / "result.json"
        result_path.unlink(missing_ok=True)
        (directory / "cancel").unlink(missing_ok=True)
        command = self.command(config, action, directory)
        deadline = time.monotonic() + (60 if action == "check" else config.timeout_seconds) + 20
        with (directory / "worker.log").open("wb") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       cwd=PROJECT_ROOT, shell=False,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            while process.poll() is None:
                if stopping.wait(0.2):
                    (directory / "cancel").touch()
                    try:
                        process.wait(timeout=12)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise RuntimeError("服务停止，任务已中断，可重试")
                if time.monotonic() > deadline:
                    (directory / "cancel").touch()
                    process.kill()
                    process.wait()
                    raise RuntimeError("转换进程超时，请检查环境或增加超时时间")
        if not result_path.is_file():
            # Detailed logs remain private to administrators; no stdout is returned to clients.
            raise RuntimeError(f"转换进程未返回结果（退出码 {process.returncode}），请查看任务日志")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not result.get("ok") or process.returncode:
            raise RuntimeError(str(result.get("error", "转换进程失败"))[:2000])
        return result


class RemoteConversionRunner:
    """Synchronous adapter used only on the conversion worker thread."""

    def __init__(self, local_runner: ProcessRunner):
        self.local_runner = local_runner

    def run(self, config: ConversionConfig, action: str, directory: Path,
            stopping: threading.Event) -> dict:
        token = os.environ.get(config.remote_token_env, "")
        if not token or any(ord(character) < 33 for character in token):
            raise ValueError(f"远程转换令牌环境变量 {config.remote_token_env} 未配置或格式无效")
        if action == "check":
            health = self._json_request(config, token, "GET", "/v1/health")
            if health.get("status") != "ok" or health.get("protocolVersion") != 1:
                raise RuntimeError("远程转换服务协议不兼容")
            verifier_config = config.model_copy(update={"mode": config.remote_verifier_mode})
            verifier = self.local_runner.run_worker(verifier_config, "check", directory, stopping)
            return {"ok": True, "remote_available": True, "mobile_available": verifier.get("mobile_available", False),
                    "protocolVersion": 1, "verifier": verifier}
        if action != "mobile":
            raise ValueError("远程转换只支持环境检测与移动端转换")
        source = directory / "source.pt"
        if not source.is_file() or source.stat().st_size <= 0:
            raise ValueError("远程转换缺少源 PT")
        source_hash = self._sha256(source)
        local_job_id = directory.parent.name
        idempotency_key = hashlib.sha256(
            f"{local_job_id}:{source_hash}:{config.input_size}:{config.calibration_data}".encode("utf-8")
        ).hexdigest()
        query = urlencode({"inputSize": config.input_size, "calibrationData": config.calibration_data})
        submitted = self._json_request(
            config, token, "POST", f"/v1/conversions?{query}", source=source,
            extra_headers={"Idempotency-Key": idempotency_key, "X-Source-SHA256": source_hash},
        )
        remote_job_id = self._remote_job_id(submitted)
        deadline = time.monotonic() + config.timeout_seconds
        current = submitted
        while current.get("status") in {"queued", "running"}:
            if stopping.wait(config.remote_poll_interval_seconds):
                self._cancel(config, token, remote_job_id)
                raise RuntimeError("服务停止，远程转换任务已请求取消，可重试")
            if time.monotonic() >= deadline:
                self._cancel(config, token, remote_job_id)
                raise RuntimeError("远程转换超时，任务已请求取消")
            current = self._json_request(config, token, "GET", f"/v1/conversions/{remote_job_id}")
        if current.get("status") != "succeeded":
            code = str(current.get("error", {}).get("code", "remote_failed")) if isinstance(current.get("error"), dict) else "remote_failed"
            raise RuntimeError(f"远程转换失败（{code[:100]}）")
        result = current.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("远程转换成功响应缺少 result")
        labels = result.get("labels")
        if not isinstance(labels, list) or not labels or any(not isinstance(label, str) or not label for label in labels):
            raise RuntimeError("远程转换返回的标签无效")
        expected_size = result.get("sizeBytes")
        expected_hash = str(result.get("sha256", ""))
        artifact_url = result.get("artifactUrl")
        if not isinstance(expected_size, int) or expected_size <= 0 or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
            raise RuntimeError("远程转换返回的产物完整性元数据无效")
        if not isinstance(artifact_url, str) or not artifact_url.startswith("/") or artifact_url.startswith("//"):
            raise RuntimeError("远程转换产物 URL 必须是同源绝对路径")
        target = directory / "android.tflite"
        self._download(config, token, artifact_url, target, expected_size, expected_hash)
        verifier_config = config.model_copy(update={"mode": config.remote_verifier_mode})
        verified = self.local_runner.run_worker(
            verifier_config, "verify", directory, stopping,
            request={"input_size": config.input_size, "expected_labels": labels},
        )
        if verified.get("labels") != labels:
            target.unlink(missing_ok=True)
            raise RuntimeError("本地复验的类别顺序与远程结果不一致")
        return {**verified, "sha256": expected_hash.lower(), "sizeBytes": expected_size,
                "calibration": config.calibration_data, "remote_job_id": remote_job_id}

    def _connection(self, config: ConversionConfig) -> tuple[http.client.HTTPConnection, str]:
        endpoint = urlsplit(config.remote_endpoint)
        connection_class = http.client.HTTPSConnection if endpoint.scheme == "https" else http.client.HTTPConnection
        connection = connection_class(endpoint.hostname, endpoint.port, timeout=min(config.timeout_seconds, 60))
        base = endpoint.path.rstrip("/")
        return connection, base

    def _json_request(self, config: ConversionConfig, token: str, method: str, path: str,
                      source: Path | None = None, extra_headers: dict[str, str] | None = None) -> dict:
        connection, base = self._connection(config)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", **(extra_headers or {})}
        try:
            if source is None:
                connection.request(method, base + path, headers=headers)
            else:
                headers.update({"Content-Type": "application/octet-stream", "Content-Length": str(source.stat().st_size)})
                connection.putrequest(method, base + path)
                for name, value in headers.items():
                    connection.putheader(name, value)
                connection.endheaders()
                with source.open("rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        connection.send(block)
            response = connection.getresponse()
            payload = response.read(1024 * 1024 + 1)
            if len(payload) > 1024 * 1024:
                raise RuntimeError("远程转换 JSON 响应过大")
            if response.status not in {200, 202}:
                code = self._error_code(payload)
                raise RuntimeError(f"远程转换请求失败：HTTP {response.status}（{code}）")
            parsed = json.loads(payload.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise RuntimeError("远程转换响应必须是 JSON 对象")
            return parsed
        except (OSError, http.client.HTTPException, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError("无法连接远程转换服务或响应无效") from exc
        finally:
            connection.close()

    def _download(self, config: ConversionConfig, token: str, path: str, target: Path,
                  expected_size: int, expected_hash: str) -> None:
        connection, base = self._connection(config)
        partial = target.with_suffix(".tflite.part")
        digest = hashlib.sha256()
        received = 0
        try:
            connection.request("GET", base + path, headers={"Authorization": f"Bearer {token}", "Accept": "application/octet-stream"})
            response = connection.getresponse()
            if response.status != 200:
                raise RuntimeError(f"远程转换产物下载失败：HTTP {response.status}")
            declared = response.getheader("Content-Length")
            if declared is not None and int(declared) != expected_size:
                raise RuntimeError("远程转换产物大小与响应头不一致")
            with partial.open("wb") as output:
                while True:
                    block = response.read(min(1024 * 1024, expected_size - received + 1))
                    if not block:
                        break
                    received += len(block)
                    if received > expected_size:
                        raise RuntimeError("远程转换产物超过声明大小")
                    digest.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            if received != expected_size or digest.hexdigest().lower() != expected_hash.lower():
                raise RuntimeError("远程转换产物大小或 SHA-256 不匹配")
            partial.replace(target)
        finally:
            connection.close()
            partial.unlink(missing_ok=True)

    def _cancel(self, config: ConversionConfig, token: str, remote_job_id: str) -> None:
        try:
            self._json_request(config, token, "DELETE", f"/v1/conversions/{remote_job_id}")
        except RuntimeError:
            pass

    @staticmethod
    def _remote_job_id(response: dict) -> str:
        value = response.get("jobId")
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
            raise RuntimeError("远程转换返回的 jobId 无效")
        return value

    @staticmethod
    def _error_code(payload: bytes) -> str:
        try:
            value = json.loads(payload.decode("utf-8")).get("code", "remote_error")
            return str(value)[:100] if re.fullmatch(r"[A-Za-z0-9._-]+", str(value)) else "remote_error"
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            return "remote_error"

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()


class ConversionService:
    def __init__(self, root: Path, runner: ProcessRunner | None = None,
                 database_manager: DatabaseManager | None = None):
        self.root = root
        self.runner = runner or ProcessRunner()
        self._guard = threading.RLock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock_file = None
        self._database = database_manager
        self._legacy_import_checked = False
        self.handler: Callable[[dict, Path, ConversionConfig], dict] = self._default_handler

    @property
    def database_manager(self) -> DatabaseManager | None:
        return self._database

    def configure_database(self, database_manager: DatabaseManager | None) -> None:
        with self._guard:
            self._database = database_manager
            self._legacy_import_checked = False

    def _import_legacy_once(self) -> None:
        if self._database is None or self._legacy_import_checked:
            return
        with self._guard:
            if self._legacy_import_checked:
                return
            with self._database.session() as session:
                config_row = session.get(ConversionConfigRecord, "default")
                legacy_config = self.root / "config.json"
                if config_row is None and legacy_config.is_file():
                    config = ConversionConfig.model_validate_json(legacy_config.read_text(encoding="utf-8"))
                    session.add(ConversionConfigRecord(
                        config_key="default", payload=config.model_dump()
                    ))
                jobs_exist = session.scalar(select(ConversionJobRecord.job_id).limit(1)) is not None
                legacy_jobs = self.root / "jobs.sqlite3"
                if not jobs_exist and legacy_jobs.is_file():
                    with sqlite3.connect(legacy_jobs, timeout=10) as legacy:
                        rows = legacy.execute("SELECT id, payload FROM jobs").fetchall()
                    for job_id, payload in rows:
                        try:
                            job = json.loads(payload)
                            if not isinstance(job, dict) or not isinstance(job_id, str):
                                continue
                            session.add(ConversionJobRecord(
                                job_id=job_id,
                                action=str(job.get("action") or "inspect"),
                                status=str(job.get("status") or "failed"),
                                attempt=max(1, int(job.get("attempt", 1))),
                                created_epoch=float(job.get("created_at", time.time())),
                                updated_epoch=float(job.get("updated_at", job.get("created_at", time.time()))),
                                payload=job,
                            ))
                        except (TypeError, ValueError, json.JSONDecodeError):
                            continue
            self._legacy_import_checked = True

    @contextmanager
    def _db(self):
        self.root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.root / "jobs.sqlite3", timeout=10)
        try:
            with connection:
                connection.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
                yield connection
        finally:
            connection.close()

    def config(self) -> ConversionConfig:
        if self._database is not None:
            self._import_legacy_once()
            with self._database.session() as session:
                row = session.get(ConversionConfigRecord, "default")
                if row is not None:
                    return ConversionConfig.model_validate(row.payload)
        path = self.root / "config.json"
        return ConversionConfig.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else ConversionConfig()

    def configure(self, config: ConversionConfig) -> ConversionConfig:
        # Validate the executable argument now; dependency availability is checked asynchronously.
        self.runner.command(config, "check", self.root / "probe")
        with self._guard:
            if self._database is not None:
                self._import_legacy_once()
                with self._database.session() as session:
                    row = session.get(ConversionConfigRecord, "default")
                    if row is None:
                        session.add(ConversionConfigRecord(config_key="default", payload=config.model_dump()))
                    else:
                        row.payload = config.model_dump()
            else:
                atomic_json(self.root / "config.json", config.model_dump())
        return config

    def _save(self, job: dict) -> dict:
        job["updated_at"] = time.time()
        if self._database is not None:
            self._import_legacy_once()
            with self._database.session() as session:
                row = session.get(ConversionJobRecord, job["id"])
                values = {
                    "action": str(job.get("action") or "inspect"),
                    "status": str(job.get("status") or "failed"),
                    "attempt": max(1, int(job.get("attempt", 1))),
                    "created_epoch": float(job.get("created_at", time.time())),
                    "updated_epoch": float(job["updated_at"]),
                    "payload": json.loads(json.dumps(job, ensure_ascii=False)),
                }
                if row is None:
                    session.add(ConversionJobRecord(job_id=job["id"], **values))
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
            return job
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO jobs VALUES (?, ?)", (job["id"], json.dumps(job, ensure_ascii=False)))
        return job

    def jobs(self) -> list[dict]:
        if self._database is not None:
            self._import_legacy_once()
            with self._database.session() as session:
                rows = session.scalars(select(ConversionJobRecord).order_by(
                    ConversionJobRecord.created_epoch.desc()
                )).all()
                return [json.loads(json.dumps(row.payload, ensure_ascii=False)) for row in rows]
        with self._guard, self._db() as db:
            return sorted((json.loads(row[0]) for row in db.execute("SELECT payload FROM jobs")),
                          key=lambda job: job["created_at"], reverse=True)

    def get(self, job_id: str) -> dict:
        if self._database is not None:
            self._import_legacy_once()
            with self._database.session() as session:
                row = session.get(ConversionJobRecord, job_id)
                if row is None:
                    raise KeyError(job_id)
                return json.loads(json.dumps(row.payload, ensure_ascii=False))
        with self._guard, self._db() as db:
            row = db.execute("SELECT payload FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            return json.loads(row[0])

    def submit(self, action: str, metadata: dict | None = None) -> dict:
        with self._guard:
            if sum(job["status"] in {"queued", "running"} for job in self.jobs()) >= 20:
                raise ValueError("转换队列已满，请等待已有任务完成")
            config = self.config()
            if action != "inspect":
                self.runner.command(config, action, self.root / "probe")
                if action in {"check", "mobile"}:
                    self.runner.preflight(config)
            job = self._save({"id": uuid.uuid4().hex, "action": action, "status": "queued",
                              "created_at": time.time(), "config": config.model_dump(),
                              "attempt": 1, "metadata": metadata or {}, "result": {}, "error": None})
        self._wake.set()
        return job

    def retry(self, job_id: str) -> dict:
        with self._guard:
            job = self.get(job_id)
            if job["status"] not in {"failed", "interrupted"}:
                raise ValueError("只有失败或中断任务可以重试")
            config = self.config()
            if job["action"] != "inspect":
                self.runner.command(config, job["action"], self.root / "probe")
                if job["action"] in {"check", "mobile"}:
                    self.runner.preflight(config)
            job.update(status="queued", error=None, config=config.model_dump(), attempt=job["attempt"] + 1)
            self._save(job)
        self._wake.set()
        return job

    def start(self) -> None:
        if self._thread is not None:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self._import_legacy_once()
        lock = (self.root / "worker.lock").open("a+b")
        try:
            lock.seek(0)
            if os.name == "nt":
                import msvcrt
                if (self.root / "worker.lock").stat().st_size == 0:
                    lock.write(b"0")
                    lock.flush()
                    lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock.close()
            raise RuntimeError("转换任务目录已由其他服务进程占用，请使用单 worker 启动")
        self._lock_file = lock
        for job in self.jobs():
            if job["status"] == "running":
                attempt_dir = self.root / job["id"] / str(job["attempt"])
                attempt_dir.mkdir(parents=True, exist_ok=True)
                (attempt_dir / "cancel").touch()
                self._save({**job, "status": "interrupted", "error": "服务重启时任务尚未完成，请检查后重试"})
        self._stop.clear()
        self._thread = threading.Thread(target=self._work, name="model-conversion", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=15)
            if self._thread.is_alive():
                raise RuntimeError("转换工作线程未停止，保留目录锁防止重复执行")
            self._thread = None
        if self._lock_file:
            self._lock_file.close()
            self._lock_file = None

    def _default_handler(self, job: dict, directory: Path, config: ConversionConfig) -> dict:
        return self.runner.run(config, job["action"], directory, self._stop)

    def _work(self) -> None:
        while not self._stop.is_set():
            with self._guard:
                queued = [job for job in self.jobs() if job["status"] == "queued"]
                job = queued[-1] if queued else None
                if job:
                    job["status"] = "running"
                    self._save(job)
            if not job:
                self._wake.wait(1)
                self._wake.clear()
                continue
            # Every attempt has a fresh workspace. An interrupted exporter can never overwrite its retry.
            directory = self.root / job["id"] / str(job["attempt"])
            try:
                result = self.handler(job, directory, ConversionConfig.model_validate(job["config"]))
                job.update(status="succeeded", result=result, error=None)
            except Exception as exc:
                job.update(status="interrupted" if self._stop.is_set() else "failed", error=str(exc)[:2000])
            with self._guard:
                self._save(job)
