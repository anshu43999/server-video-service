"""User-authorized refresh of the loopback development service, not deployment."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import settings
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
import httpx

PG = Path("D:/PostgreSQL/bin")
PYTHON = ROOT / ".venv/Scripts/python.exe"
BASE = "http://127.0.0.1:8080"
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")
PRIVATE = ROOT / "backups" / ("M36-T09-" + STAMP)
REPORT = ROOT / "evidence/M36/M36-T09-runtime-update.json"
REPORT.parent.mkdir(parents=True, exist_ok=True)
result = {"task": "M36-T09", "scope": "loopback-development-only", "startedAt": STAMP}


def save():
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def run(argv, *, env=None, label, stdout=None):
    log = PRIVATE / (label + ".log")
    with log.open("wb") as handle:
        completed = subprocess.run([str(v) for v in argv], cwd=ROOT, env=env,
            stdin=subprocess.DEVNULL, stdout=stdout or handle, stderr=handle, timeout=180)
    if completed.returncode:
        raise RuntimeError(label + " failed; inspect the private maintenance log")


def snapshot(engine):
    output = {}
    with engine.connect() as connection:
        for table in sorted(inspect(connection).get_table_names(schema="public")):
            quoted = connection.dialect.identifier_preparer.quote(table)
            rows = connection.execute(text("SELECT row_to_json(t)::text FROM public." + quoted + " t ORDER BY 1")).scalars().all()
            output[table] = {"count": len(rows), "sha256": hashlib.sha256("\n".join(rows).encode()).hexdigest()}
    return output


def assets():
    paths = [ROOT / "models/registry.json", ROOT / ".env"]
    paths += [p for p in (ROOT / "models").rglob("*") if p.is_file() and p.suffix in {".pt", ".onnx", ".tflite"}]
    return {p.relative_to(ROOT).as_posix(): hashlib.file_digest(p.open("rb"), "sha256").hexdigest() for p in paths if p.is_file()}


def pg_env(url):
    return dict(os.environ, PGHOST=url.host, PGPORT=str(url.port or 5432), PGDATABASE=url.database,
                PGUSER=url.username, PGPASSWORD=url.password or "", PGCONNECT_TIMEOUT="8")


def stopped():
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", 8080)) != 0


def start_service(label):
    # Windows processes must not inherit executor pipes, and no console is shown.
    out = (PRIVATE / (label + ".stdout.log")).open("ab")
    err = (PRIVATE / (label + ".stderr.log")).open("ab")
    try:
        process = subprocess.Popen([str(PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8080"],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
            creationflags=subprocess.CREATE_NO_WINDOW)
    finally:
        out.close()
        err.close()
    for _ in range(60):
        try:
            response = httpx.get(BASE + "/healthz", timeout=2)
            if response.status_code == 200 and response.json().get("status") == "ok":
                return process.pid
        except httpx.HTTPError:
            pass
        if process.poll() is not None:
            raise RuntimeError("service exited; inspect private startup log")
        time.sleep(0.5)
    raise RuntimeError("service health check timed out")


def smoke():
    account_doc = (ROOT.parent / "harness/TEST_ACCOUNTS.md").read_text(encoding="utf-8-sig")
    project = "00000000-0000-0000-0000-000000000001"
    checks = []
    with httpx.Client(base_url=BASE, timeout=20) as client:
        for username in ("admin", "gly"):
            match = re.search(r"\|\s*`" + username + r"`\s*\|\s*`([^`]+)`", account_doc)
            if not match:
                raise RuntimeError("documented test account not found")
            login = client.post("/aiyoloapi/auth/login", json={"username": username, "password": match.group(1)})
            if login.status_code != 200:
                raise RuntimeError("documented account login failed: " + username)
            headers = {"Authorization": "Bearer " + login.json()["accessToken"]}
            for path in ("/aiyoloapi/auth/projects", f"/aiyoloapi/projects/{project}/model-assignments",
                         f"/aiyoloapi/projects/{project}/models/available", f"/aiyoloapi/projects/{project}/scenes"):
                response = client.get(path, headers=headers)
                if response.status_code != 200:
                    raise RuntimeError("read-only smoke check failed: " + path + " status " + str(response.status_code))
                checks.append({"account": username, "path": path, "status": 200})
            # Empty invalid payload must reach the new route but cannot change grants.
            route = f"/aiyoloapi/projects/{project}/model-assignments/m36-t09-readonly-probe/targets"
            response = client.put(route, headers=headers, json={})
            if response.status_code != 422:
                raise RuntimeError("new batch target route not active")
            checks.append({"account": username, "path": route, "status": 422, "mutation": False})
        page = client.get("/admin/")
        if page.status_code != 200 or "no-cache" not in page.headers.get("cache-control", ""):
            raise RuntimeError("admin HTML not served correctly")
        served = page.content
        if served != (ROOT / "admin-web/dist/index.html").read_bytes():
            raise RuntimeError("served frontend differs from the staged build")
        for path in re.findall(r'(?:src|href)="(/admin/assets/[^"]+)"', page.text):
            response = client.get(path)
            if response.status_code != 200:
                raise RuntimeError("frontend asset unavailable")
            checks.append({"path": path, "status": 200})
        schema = client.get("/openapi.json").json()
        if "put" not in schema["paths"].get("/aiyoloapi/projects/{project_id}/model-assignments/{scenario}/targets", {}):
            raise RuntimeError("new route missing from active OpenAPI")
    return checks


def main():
    if os.name != "nt" or settings.deployment_env != "development":
        raise RuntimeError("only the verified Windows development environment is allowed")
    url = make_url(settings.database_url)
    if url.host != "127.0.0.1" or url.database != "aiyolo_dev" or url.query:
        raise RuntimeError("unexpected database target or connection overrides")
    for key in ("DATABASE_URL", "DEPLOYMENT_ENV", "PGOPTIONS", "PGSERVICE"):
        if os.environ.get(key):
            raise RuntimeError("unexpected environment override: " + key)
    staging = ROOT / "admin-web/dist-m36-t09-staging"
    if not (staging / "index.html").is_file():
        raise RuntimeError("staged frontend build missing")
    engine = create_engine(url)
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
    if revision != "20261019_15":
        raise RuntimeError("unexpected starting migration version")
    health = httpx.get(BASE + "/healthz").json()
    if health.get("streams") != 0:
        raise RuntimeError("active streams require a separate drain plan")
    PRIVATE.mkdir(parents=True)
    run(["icacls", PRIVATE, "/inheritance:r", "/grant:r", "*S-1-3-4:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"], label="protect-backup")
    result.update({"backupDirectory": str(PRIVATE), "database": url.database, "oldRevision": revision})
    save()
    # Verify exact process identities and port owner immediately before stopping.
    stop_code = "$ErrorActionPreference='Stop'; $p=Get-CimInstance Win32_Process -Filter 'ProcessId=36440'; $q=Get-CimInstance Win32_Process -Filter 'ProcessId=4620'; $listener=Get-NetTCPConnection -LocalPort 8080 -State Listen; if (-not $p -or -not $q -or $p.ParentProcessId -ne 4620 -or $listener.OwningProcess -ne 36440 -or $p.CommandLine -notlike '*server-video-service*.venv*uvicorn app.main:app*127.0.0.1*8080*' -or $q.CommandLine -notlike '*server-video-service*.venv*uvicorn app.main:app*127.0.0.1*8080*') { throw 'service identity changed' }; Stop-Process -Id 4620,36440 -ErrorAction Stop"
    service_stopped = False
    cluster_started = False
    try:
        run(["powershell.exe", "-NoProfile", "-Command", stop_code], label="stop-old-service")
        service_stopped = True
        for _ in range(20):
            if stopped():
                break
            time.sleep(0.25)
        if not stopped():
            raise RuntimeError("8080 still listening after stop")
        before = snapshot(engine)
        asset_before = assets()
        dump = PRIVATE / "aiyolo_dev-before.dump"
        run([PG / "pg_dump.exe", "--no-password", "--format=custom", "--file=" + str(dump)], env=pg_env(url), label="database-backup")
        run([PG / "pg_restore.exe", "--list", dump], label="backup-list")
        result["backup"] = {"bytes": dump.stat().st_size, "sha256": hashlib.file_digest(dump.open("rb"), "sha256").hexdigest()}
        # Restore into a private, short-lived loopback cluster, never over a live DB.
        cluster = PRIVATE / "restore-cluster"
        run([PG / "initdb.exe", "-D", cluster, "-U", "aiyolo_app", "-E", "UTF8", "--no-locale", "--auth-local=trust", "--auth-host=trust", "--no-instructions"], label="restore-initdb")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        cluster_started = True
        run([PG / "pg_ctl.exe", "-D", cluster, "-l", PRIVATE / "restore-postgres.log", "-o", f"-h 127.0.0.1 -p {port}", "-w", "-t", "60", "start"], label="restore-start", stdout=subprocess.DEVNULL)
        restore_url = url.set(port=port, database="postgres", password=None)
        run([PG / "pg_restore.exe", "--no-password", "--no-owner", "--no-privileges", "--exit-on-error", "--dbname=postgres", dump], env=pg_env(restore_url), label="backup-restore")
        restored_engine = create_engine(restore_url)
        try:
            restored = snapshot(restored_engine)
            if before != restored:
                raise RuntimeError("restored row counts or hashes differ")
        finally:
            restored_engine.dispose()
        run([PG / "pg_ctl.exe", "-D", cluster, "-m", "fast", "-w", "stop"], label="restore-stop")
        cluster_started = False
        result["backupRestoreVerified"] = {"tables": len(before), "allRowCountsAndHashesMatch": True}
        save()
        run([PYTHON, "-m", "alembic", "upgrade", "20261020_16"], label="database-migration")
        after = snapshot(engine)
        if {k: v for k, v in before.items() if k != "alembic_version"} != {k: v for k, v in after.items() if k != "alembic_version"}:
            raise RuntimeError("migration changed business data")
        with engine.connect() as connection:
            result["newRevision"] = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
            constraints = inspect(connection).get_unique_constraints("project_model_assignments", schema="public")
        if not any(c["column_names"] == ["project_id", "scenario", "parameter_platform"] for c in constraints):
            raise RuntimeError("new independent target constraint missing")
        shutil.move(str(ROOT / "admin-web/dist"), str(PRIVATE / "frontend-before"))
        shutil.move(str(staging), str(ROOT / "admin-web/dist"))
        result["serviceLauncherPid"] = start_service("new-service")
        service_stopped = False
        result["smokeChecks"] = smoke()
        final = snapshot(engine)
        protected = ("accounts", "projects", "project_memberships", "project_model_assignments", "project_scenes", "project_scene_members")
        if any(final[name] != before[name] for name in protected) or assets() != asset_before:
            raise RuntimeError("protected project/model/scene/configuration changed")
        result.update({"result": "passed", "businessDataUnchangedByMigration": True,
            "protectedDataUnchangedAfterSmoke": True, "modelFilesAndRegistryUnchanged": True,
            "sceneApprovalChanged": False, "modelGrantsChanged": False,
            "beforeTables": before, "health": httpx.get(BASE + "/healthz").json()})
        save()
        print(json.dumps({k: v for k, v in result.items() if k not in {"beforeTables", "smokeChecks"}}, ensure_ascii=False))
    except Exception as exc:
        result["result"] = "failed"
        result["error"] = str(exc)
        save()
        if service_stopped and stopped():
            try:
                result["recoveryLauncherPid"] = start_service("recovery-service")
                result["serviceRecovered"] = True
            except Exception:
                result["serviceRecovered"] = False
            save()
        raise
    finally:
        engine.dispose()
        if cluster_started:
            run([PG / "pg_ctl.exe", "-D", cluster, "-m", "fast", "-w", "stop"], label="restore-finally-stop")


if __name__ == "__main__":
    main()
