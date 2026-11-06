"""M36-T11: bounded, backed-up refresh of the explicit Windows loopback service.

No publication, frontend replacement, project edits or production deployment.
Reuses the previously verified local backup/start helpers, not its old main().
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time

import refresh_local_m36_service as maintenance
import httpx
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


def protected_snapshot(engine):
    """Canonical rows: ignore only the newly added nullable column, not config."""
    result = {}
    with engine.connect() as connection:
        for table in sorted(inspect(connection).get_table_names(schema="public")):
            quoted = connection.dialect.identifier_preparer.quote(table)
            expression = "to_jsonb(t)" + (" - 'parameter_snapshot'" if table == "project_scene_members" else "")
            rows = connection.execute(text(f"SELECT ({expression})::text FROM public.{quoted} t ORDER BY 1")).scalars().all()
            result[table] = {"count": len(rows), "sha256": hashlib.sha256("\n".join(rows).encode()).hexdigest()}
    return result


def verify_identity(listener_pid, parent_pid, *, stop=False):
    root = str(maintenance.ROOT).replace("'", "''")
    # Explicit IDs must still own exactly the approved loopback uvicorn command.
    code = (
        "$ErrorActionPreference='Stop'; "
        f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={listener_pid}'; "
        f"$q=Get-CimInstance Win32_Process -Filter 'ProcessId={parent_pid}'; "
        "$l=@(Get-NetTCPConnection -LocalPort 8080 -State Listen); "
        f"$expected='{root}\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080'; "
        f"if (-not $p -or -not $q -or $p.ParentProcessId -ne {parent_pid} -or "
        f"$l.Count -ne 1 -or $l[0].OwningProcess -ne {listener_pid} -or "
        "$l[0].LocalAddress -ne '127.0.0.1' -or "
        "$p.CommandLine.Trim() -ne $expected -or $q.CommandLine.Trim() -ne $expected) "
        "{ throw 'service identity changed; refusing refresh' }; "
        + (f"Stop-Process -Id {listener_pid},{parent_pid} -ErrorAction Stop" if stop else "Write-Output 'identity verified'")
    )
    maintenance.run(["powershell.exe", "-NoProfile", "-Command", code], label="stop-service" if stop else "verify-service")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-listener", required=True, type=int)
    parser.add_argument("--expected-parent", required=True, type=int)
    args = parser.parse_args()
    if min(args.expected_listener, args.expected_parent) < 1 or args.expected_listener == args.expected_parent:
        raise RuntimeError("two exact, distinct process IDs required")
    settings = maintenance.settings
    url = make_url(settings.database_url)
    if os.name != "nt" or settings.deployment_env != "development":
        raise RuntimeError("Windows development environment only")
    if url.host != "127.0.0.1" or url.database != "aiyolo_dev" or url.query:
        raise RuntimeError("unexpected database target")
    if any(os.environ.get(key) for key in ("DATABASE_URL", "DEPLOYMENT_ENV", "PGOPTIONS", "PGSERVICE")):
        raise RuntimeError("unexpected database or environment override")
    private = maintenance.ROOT / "backups" / ("M36-T11-" + maintenance.STAMP)
    if private.exists():
        raise RuntimeError("backup directory already exists")
    private.mkdir(parents=True)
    maintenance.PRIVATE = private
    maintenance.REPORT = maintenance.ROOT / "harness/evidence/M36" / ("M36-T11-runtime-" + maintenance.STAMP + ".json")
    maintenance.result = result = {"task": "M36-T11", "scope": "loopback-development-only",
        "backupDirectory": str(private), "startedAt": maintenance.STAMP}
    maintenance.run(["icacls", private, "/inheritance:r", "/grant:r", "*S-1-3-4:(OI)(CI)F",
        "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"], label="protect-backup")
    engine = create_engine(url)
    cluster_started = service_stopped = False
    cluster = private / "restore-cluster"
    try:
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
        if revision != "20261020_16":
            raise RuntimeError("unexpected starting migration")
        health = httpx.get(maintenance.BASE + "/healthz", timeout=10).json()
        if health.get("status") != "ok" or health.get("streams") != 0:
            raise RuntimeError("service not healthy/idle; no implicit drain")
        verify_identity(args.expected_listener, args.expected_parent)
        maintenance.save()
        verify_identity(args.expected_listener, args.expected_parent, stop=True)
        service_stopped = True
        for _ in range(40):
            if maintenance.stopped():
                break
            time.sleep(0.25)
        if not maintenance.stopped():
            raise RuntimeError("8080 still listening")
        before, assets_before = protected_snapshot(engine), maintenance.assets()
        dump = private / "aiyolo_dev-before.dump"
        maintenance.run([maintenance.PG / "pg_dump.exe", "--no-password", "--format=custom", "--file=" + str(dump)],
            env=maintenance.pg_env(url), label="database-backup")
        maintenance.run([maintenance.PG / "pg_restore.exe", "--list", dump], label="backup-list")
        with dump.open("rb") as handle:
            result["backup"] = {"bytes": dump.stat().st_size, "sha256": hashlib.file_digest(handle, "sha256").hexdigest()}
        maintenance.run([maintenance.PG / "initdb.exe", "-D", cluster, "-U", "aiyolo_app", "-E", "UTF8",
            "--no-locale", "--auth-local=trust", "--auth-host=trust", "--no-instructions"], label="restore-initdb")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        cluster_started = True
        maintenance.run([maintenance.PG / "pg_ctl.exe", "-D", cluster, "-l", private / "restore-postgres.log",
            "-o", f"-h 127.0.0.1 -p {port}", "-w", "-t", "60", "start"], label="restore-start")
        restore_url = url.set(port=port, database="postgres", password=None)
        maintenance.run([maintenance.PG / "pg_restore.exe", "--no-password", "--no-owner", "--no-privileges",
            "--exit-on-error", "--dbname=postgres", dump], env=maintenance.pg_env(restore_url), label="backup-restore")
        restore_engine = create_engine(restore_url)
        try:
            if protected_snapshot(restore_engine) != before:
                raise RuntimeError("restored backup data differs")
        finally:
            restore_engine.dispose()
        maintenance.run([maintenance.PG / "pg_ctl.exe", "-D", cluster, "-m", "fast", "-w", "stop"], label="restore-stop")
        cluster_started = False
        result["backupRestoreVerified"] = True
        maintenance.save()
        maintenance.run([maintenance.PYTHON, "-m", "alembic", "upgrade", "20261020_17"], label="migration")
        after = protected_snapshot(engine)
        if {k: v for k, v in before.items() if k != "alembic_version"} != {
                k: v for k, v in after.items() if k != "alembic_version"}:
            raise RuntimeError("business data changed during additive migration")
        with engine.connect() as connection:
            if connection.execute(text("SELECT COUNT(*) FROM public.project_scene_members "
                    "WHERE parameter_snapshot IS NOT NULL")).scalar_one() != 0:
                raise RuntimeError("migration unexpectedly granted reviewed parameters")
        result["serviceLauncherPid"] = maintenance.start_service("scene-service")
        service_stopped = False
        schema = httpx.get(maintenance.BASE + "/openapi.json", timeout=20).json()
        route = "/aiyoloapi/projects/{project_id}/scenes/{scene_id}/models/{model_id}/versions/{version}/parameters"
        if "get" not in schema.get("paths", {}).get(route, {}):
            raise RuntimeError("scene parameter route missing")
        # Read-only account/API/frontend checks. They do not approve or change Default.
        result["smokeChecks"] = maintenance.smoke()
        final = protected_snapshot(engine)
        protected = ("accounts", "projects", "project_memberships", "project_model_assignments", "project_scenes", "project_scene_members")
        if any(final[k] != before[k] for k in protected) or maintenance.assets() != assets_before:
            raise RuntimeError("protected configuration or model assets changed")
        result.update(result="passed", oldRevision=revision, newRevision="20261020_17",
            businessDataUnchanged=True, noAutomaticApproval=True, protectedTableDigests={k: before[k] for k in protected},
            health=httpx.get(maintenance.BASE + "/healthz", timeout=10).json())
        maintenance.save()
        print(json.dumps({k: v for k, v in result.items() if k not in {"smokeChecks", "protectedTableDigests"}}, ensure_ascii=False))
    except Exception as error:
        result.update(result="failed", errorType=type(error).__name__)
        if service_stopped and maintenance.stopped():
            try:
                result["recoveryLauncherPid"] = maintenance.start_service("recovery-service")
                result["serviceRecovered"] = True
            except Exception:
                result["serviceRecovered"] = False
        maintenance.save()
        raise RuntimeError("refresh failed; inspect private maintenance logs and public evidence") from None
    finally:
        engine.dispose()
        if cluster_started:
            maintenance.run([maintenance.PG / "pg_ctl.exe", "-D", cluster, "-m", "fast", "-w", "stop"], label="restore-finally-stop")


if __name__ == "__main__":
    main()
