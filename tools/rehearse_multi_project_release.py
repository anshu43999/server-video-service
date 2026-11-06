"""Rehearse M33 upgrade and rollback in a disposable, loopback-only PostgreSQL cluster.

This tool never uses DATABASE_URL, MIGRATION_DATABASE_URL or a live cluster. It
only reads a verified offline T14 bundle. All output contains counts/timings,
never restored rows or credentials. The generated cluster is stopped and removed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import auth, project_migration as migration
from app.config import Settings
from app.database import DatabaseManager, DEFAULT_PROJECT_ID, ProjectAuditEventRecord
from app.audit_retention import retain_audits
from app.project_management import create_project_management_router
from app.service_principals import ALERTS_INGEST, create_service_principal_router, resolve_service_context


def _run(binary: Path, *arguments: str) -> None:
    # pg_ctl starts a background postmaster. On Windows that process may inherit
    # the parent's pipe handles; communicate() would then wait for the *server*
    # to exit even though pg_ctl has already reported successful startup.
    redirect = subprocess.DEVNULL if binary.stem == "pg_ctl" else subprocess.PIPE
    subprocess.run([str(binary), *arguments], check=True, stdin=subprocess.DEVNULL,
                   stdout=redirect, stderr=redirect, text=True, timeout=120)


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _require(response, status: int):
    if response.status_code != status:
        detail = response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else None
        code = detail.get("code") if isinstance(detail, dict) else None
        # Only a short, fixed-format error code is diagnostic-safe; never print
        # a detail string or response body from the restored snapshot.
        safe_code = code if isinstance(code, str) and code.isascii() and code.replace("_", "").isalpha() else "unknown"
        raise RuntimeError(f"rehearsal HTTP check failed: expected {status}, got {response.status_code}, code {safe_code}")
    return response.json() if response.content else {}


def _request(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _credential_request(credential: str, project_id: str) -> Request:
    return Request({"type": "http", "method": "POST", "path": "/ingest",
                    "path_params": {"project_id": project_id},
                    "headers": [(b"authorization", ("Bearer " + credential).encode()),
                                (b"x-service-timestamp", str(int(time.time())).encode()),
                                (b"x-service-nonce", uuid4().hex.encode())]})


def _credential_status(credential: str, project_id: str) -> int:
    from fastapi import HTTPException
    try:
        resolve_service_context(_credential_request(credential, project_id), ALERTS_INGEST)
    except HTTPException as error:
        return error.status_code
    return 200


def _router_app():
    app = FastAPI()
    app.include_router(auth.create_auth_router())
    app.include_router(create_project_management_router())
    app.include_router(create_service_principal_router())
    return app


def _restart_probe():
    # Invoked only by this tool in a fresh Python process. Secrets arrive via
    # stdin, never command-line arguments or stdout. Do not accept remote URLs.
    payload = json.load(sys.stdin)
    url = make_url(payload["url"])
    if url.host != "127.0.0.1" or url.database != "m33_source":
        raise ValueError("restart probe must use the temporary loopback database")
    db = DatabaseManager(payload["url"])
    settings = Settings(_env_file=None, database_url=payload["url"], deployment_env="production",
                        admin_token=None, mobile_token=None)
    try:
        with patch.object(auth, "database", db), patch.object(auth, "settings", settings), TestClient(_router_app()) as client:
            _require(client.get("/aiyoloapi/projects/" + payload["projectId"],
                                headers=_request(payload["session"])), 200)
            if _credential_status(payload["credential"], payload["projectId"]) != 200:
                raise RuntimeError("rotated credential did not survive fresh worker")
    finally:
        db.close()


def _business_rehearsal(url: str, restart_database) -> dict:
    """Use production auth/management handlers against only this local cluster."""
    db = DatabaseManager(url)
    isolated_settings = Settings(_env_file=None, database_url=url, deployment_env="production",
                                 admin_token=None, mobile_token=None)
    with patch.object(auth, "database", db), patch.object(auth, "settings", isolated_settings):
        try:
            admin_name = "rehearsal-admin-" + uuid4().hex[:8]
            auth._create_account(admin_name, "rehearsal-password-1", auth.ROLE_ADMIN)
            with TestClient(_router_app()) as client:
                admin_token = _require(client.post("/aiyoloapi/auth/login", json={
                    "username": admin_name, "password": "rehearsal-password-1"}), 200)["accessToken"]
                admin = _request(admin_token)
                owner = _require(client.post("/aiyoloapi/platform/accounts", headers=admin, json={
                    "username": "rehearsal-owner", "password": "rehearsal-password-1",
                    "platformRole": "NORMAL_USER"}), 201)
                member = _require(client.post("/aiyoloapi/platform/accounts", headers=admin, json={
                    "username": "rehearsal-user", "password": "rehearsal-password-1",
                    "platformRole": "NORMAL_USER"}), 201)
                project = _require(client.post("/aiyoloapi/platform/projects", headers=admin, json={
                    "projectCode": "rehearsal-sandbox", "displayName": "离线演练项目",
                    "ownerAccountId": owner["accountId"]}), 201)
                project_id = project["projectId"]
                base = f"/aiyoloapi/projects/{project_id}"
                membership = _require(client.post(base + "/members", headers=admin, json={
                    "accountId": member["accountId"], "projectRole": "PROJECT_USER"}), 201)
                user_token = _require(client.post("/aiyoloapi/auth/login", json={
                    "username": "rehearsal-user", "password": "rehearsal-password-1"}), 200)["accessToken"]
                user = _request(user_token)
                _require(client.get(base, headers=user), 200)
                expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                issued = _require(client.post(base + "/service-principals", headers=admin, json={
                    "displayName": "演练设备", "principalType": "DEVICE",
                    "capabilities": [ALERTS_INGEST], "expiresAt": expiry}), 201)
                assert _credential_status(issued["credential"], project_id) == 200
                rotated = _require(client.post(base + "/service-principals/" + issued["principalId"] + "/rotate",
                                               headers=admin, json={"expectedRevision": issued["revision"],
                                                                    "expiresAt": expiry}), 200)
                assert _credential_status(issued["credential"], project_id) == 401
                assert _credential_status(rotated["credential"], project_id) == 200
                # Restart the temporary PostgreSQL server AND verify authorization
                # in a fresh worker with no inherited in-memory account state.
                db.close()
                restart_database()
                probe = subprocess.run([sys.executable, "-c",
                    "from tools.rehearse_multi_project_release import _restart_probe; _restart_probe()"],
                    cwd=ROOT, input=json.dumps({"url": url, "projectId": project_id,
                                               "session": user_token, "credential": rotated["credential"]}),
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
                if probe.returncode:
                    raise RuntimeError("fresh authorization worker restart failed")
                _require(client.get(base, headers=user), 200)
                assert _credential_status(rotated["credential"], project_id) == 200
                _require(client.delete(base + "/members/" + member["accountId"], headers=admin,
                                       params={"expectedRevision": membership["revision"]}), 204)
                _require(client.get(base, headers=user), 404)
                projects = _require(client.get("/aiyoloapi/auth/projects", headers=user), 200)["projects"]
                assert all(item["projectId"] != project_id for item in projects)
                archived = _require(client.post(base + "/archive", headers=admin,
                                                json={"expectedRevision": project["revision"]}), 200)
                assert archived["lifecycleState"] == "ARCHIVED"
                assert _credential_status(rotated["credential"], project_id) == 403
                assert _credential_status(rotated["credential"], DEFAULT_PROJECT_ID) == 404
                # Prove legal hold and explicit deletion without touching snapshot
                # audit history: only the newly inserted synthetic 400-day row ages out.
                audit_id = str(uuid4())
                with db.session() as session:
                    session.add(ProjectAuditEventRecord(audit_id=audit_id, project_id=project_id,
                        occurred_at=datetime.now(timezone.utc) - timedelta(days=400),
                        action="rehearsal.retention", target_type="rehearsal", outcome="SUCCESS"))
                held = retain_audits(db, held_projects=(project_id,))
                preview = retain_audits(db)
                assert preview["eligible"]["project_audit_events"] == held["eligible"]["project_audit_events"] + 1
                assert not any(preview["deleted"].values())
                retention = retain_audits(db, apply=True)
                assert retention["deleted"]["project_audit_events"] == 1
                return {"projectCreated": True, "sessionSurvivedRestart": True,
                        "freshAuthorizationWorker": True, "postgresRestarted": True,
                        "auditRetentionVerified": True,
                        "memberRevoked": True, "deviceRotated": True, "archiveBlocksIngest": True}
        finally:
            db.close()


def _bundle_hashes(bundle):
    return {path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in bundle.rglob("*") if path.is_file()}


def _protect_directory(path):
    # The offline snapshot contains production data. Protect the entire
    # disposable tree before copying it, including logs and native dump files.
    if os.name == "nt":
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                        "*S-1-3-4:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F",
                        "*S-1-5-32-544:(OI)(CI)F"], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    else:
        path.chmod(0o700)


def rehearse(bundle: Path, pg_bin: Path, *, run_regressions=False) -> dict:
    if not __debug__:
        raise ValueError("rehearsal assertions require Python without -O")
    if not bundle.is_dir():
        raise ValueError("offline bundle not found")
    manifest = migration.verify_bundle(bundle)
    if manifest["dialect"] != "postgresql" or manifest["format"] != 2:
        raise ValueError("rehearsal requires a complete PostgreSQL format-2 offline bundle")
    for name in ("initdb", "pg_ctl", "pg_dump", "pg_restore"):
        if not (pg_bin / f"{name}.exe").is_file():
            raise ValueError("required local PostgreSQL binary not found: " + name)
    backups = (ROOT / "backups").resolve()
    backups.mkdir(exist_ok=True)
    working = Path(tempfile.mkdtemp(prefix="m33-t17-", dir=backups)).resolve()
    if working.parent != backups or not working.name.startswith("m33-t17-"):
        raise RuntimeError("temporary cluster path escaped the dedicated backup directory")
    data = working / "cluster"
    cluster_started = False
    original_hashes = _bundle_hashes(bundle)
    try:
        _protect_directory(working)
        # restore() records a verification marker next to the manifest. Work on a
        # private copy so even verification metadata never changes the source.
        copied_bundle = working / "input-bundle"
        shutil.copytree(bundle, copied_bundle)
        _run(pg_bin / "initdb.exe", "-D", str(data), "-U", "m33test", "-E", "UTF8", "--no-locale",
             "--auth-local=trust", "--auth-host=trust", "--no-instructions")
        port = _port()
        cluster_started = True
        _run(pg_bin / "pg_ctl.exe", "-D", str(data), "-l", str(working / "postgres.log"),
             "-o", f"-h 127.0.0.1 -p {port}", "-w", "-t", "60", "start")
        base = make_url(f"postgresql+psycopg://m33test@127.0.0.1:{port}/postgres")
        engine = sa.create_engine(base, isolation_level="AUTOCOMMIT")
        try:
            with engine.connect() as connection:
                for name in ("source", "native_restore", "verified_restore", "rollback"):
                    connection.execute(sa.text(f"CREATE DATABASE m33_{name}"))
        finally:
            engine.dispose()
        source = base.set(database="m33_source").render_as_string(hide_password=False)
        native = base.set(database="m33_native_restore").render_as_string(hide_password=False)
        rollback = base.set(database="m33_rollback").render_as_string(hide_password=False)
        verified = base.set(database="m33_verified_restore").render_as_string(hide_password=False)
        started = time.monotonic()
        migration.restore(source, copied_bundle, maintenance=True)
        restored_seconds = round(time.monotonic() - started, 2)
        with migration.database_connection(source) as connection:
            source_snapshot = migration.preflight(connection)
            source_schema = migration.schema_signature(connection)
        dump = working / "legacy.dump"
        _run(pg_bin / "pg_dump.exe", "--no-password", "--format=custom", f"--file={dump}",
             "--dbname=" + source.replace("postgresql+psycopg:", "postgresql:"))
        _run(pg_bin / "pg_restore.exe", "--no-owner", "--no-privileges", "--exit-on-error",
             "--dbname=" + native.replace("postgresql+psycopg:", "postgresql:"), str(dump))
        with migration.database_connection(native) as connection:
            if (migration.preflight(connection)["tables"] != source_snapshot["tables"] or
                    migration.schema_signature(connection) != source_schema):
                raise RuntimeError("native PostgreSQL backup/restore mismatch")
        fresh = working / "verified-bundle"
        migration.prepare(source, fresh)
        migration.restore(verified, fresh, maintenance=True)
        started = time.monotonic()
        migration.apply(source, fresh, maintenance=True,
                        archive_orphan_receipts=bool(source_snapshot["blockers"]))
        applied_seconds = round(time.monotonic() - started, 2)
        repeated = migration.apply(source, fresh, maintenance=True,
                                   archive_orphan_receipts=bool(source_snapshot["blockers"]))
        if repeated["phase"] != "already-applied":
            raise RuntimeError("repeated upgrade was not idempotent")
        with migration.database_connection(source) as connection:
            migration.reconcile(connection, fresh, migration.verify_bundle(fresh))
            revision = migration.preflight(connection)["revision"]
        if revision != migration.TARGET:
            raise RuntimeError("target revision not reached")
        def restart_database():
            _run(pg_bin / "pg_ctl.exe", "-D", str(data), "-m", "fast", "-w", "-t", "60", "stop")
            _run(pg_bin / "pg_ctl.exe", "-D", str(data), "-l", str(working / "postgres.log"),
                 "-o", f"-h 127.0.0.1 -p {port}", "-w", "-t", "60", "start")

        business = _business_rehearsal(source, restart_database)
        try:
            with migration.database_connection(source, write=True) as connection:
                from alembic import command
                command.downgrade(migration.config(connection), migration.LEGACY)
        except RuntimeError:
            pass
        else:
            raise RuntimeError("lossy downgrade was not refused")
        with migration.database_connection(source) as connection:
            if migration.preflight(connection)["revision"] != migration.TARGET:
                raise RuntimeError("refused downgrade changed the upgraded schema")
        # Actual rollback restoration occurs AFTER the upgrade and new-project
        # mutations, into another empty database; source data is never overwritten.
        migration.restore(rollback, fresh, maintenance=True)
        with migration.database_connection(rollback) as connection:
            restored = migration.preflight(connection)
            if restored["tables"] != source_snapshot["tables"] or restored["revision"] != migration.LEGACY:
                raise RuntimeError("pre-upgrade rollback copy differs from original legacy backup")
        regression_count = None
        if run_regressions:
            env = {**os.environ, "DATABASE_URL": base.render_as_string(hide_password=False),
                   "MINIO_ENDPOINT": " ", "RUN_POSTGRES_TESTS": "1", "RUN_POSTGRES_MIGRATION_TESTS": "1"}
            suite = ("test_multi_project_migration_postgresql", "test_default_project_rollout_postgresql",
                     "test_service_principal_storage", "test_project_reporting_postgresql")
            result = subprocess.run([sys.executable, "-m", "unittest", *suite, "-v"],
                cwd=ROOT, env={**env, "PYTHONPATH": os.pathsep.join((str(ROOT / "tests"), str(ROOT)))},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
            # These tests use synthetic data in separate random schemas.
            if result.returncode:
                raise RuntimeError("isolated PostgreSQL regressions failed")
            import re
            regression_count = int(re.search(r"Ran (\d+) tests", result.stderr).group(1))
        return {"isolation": "temporary loopback PostgreSQL, no production connection",
                "sourceRevision": source_snapshot["revision"], "targetRevision": revision,
                "legacyAccounts": len(source_snapshot["accountMapping"]),
                "legacyRows": {key: value["count"] for key, value in source_snapshot["tables"].items()
                               if key in ("alert_events", "alert_delivery_receipts", "stream_configs")},
                "orphanReceiptCount": migration.verify_bundle(fresh)["orphanArchive"]["count"],
                "nativeBackupRestored": True, "rollbackLegacyMatched": True,
                "postgresRegressionTests": regression_count, "sourceBundleUnchanged": True,
                "lossyDowngradeRefused": True, "temporaryClusterRemoved": True,
                "repeatedUpgradeSafe": True, "restoreSeconds": restored_seconds,
                "upgradeSeconds": applied_seconds, **business}
    finally:
        if cluster_started:
            try:
                status = subprocess.run([str(pg_bin / "pg_ctl.exe"), "-D", str(data), "status"],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if status.returncode == 0:
                    _run(pg_bin / "pg_ctl.exe", "-D", str(data), "-m", "fast", "-w", "-t", "60", "stop")
                elif (data / "postmaster.pid").exists():
                    raise RuntimeError("temporary PostgreSQL state is uncertain")
            except Exception:
                print("isolated PostgreSQL stop failed; inspect the temporary cluster before cleanup", file=sys.stderr)
                raise
        # Only remove the directory this run created, never source bundles or live databases.
        if working.parent == backups and working.name.startswith("m33-t17-"):
            shutil.rmtree(working)
        if _bundle_hashes(bundle) != original_hashes:
            raise RuntimeError("source backup files changed during rehearsal")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True, help="verified, offline format-2 PostgreSQL bundle")
    parser.add_argument("--postgres-bin", type=Path, required=True, help="local PostgreSQL binaries directory")
    parser.add_argument("--run-regressions", action="store_true", help="run PostgreSQL regressions against only the temporary cluster")
    args = parser.parse_args()
    try:
        print(json.dumps(rehearse(args.bundle.resolve(), args.postgres_bin.resolve(),
                                 run_regressions=args.run_regressions), ensure_ascii=False))
    except Exception as error:
        frames = [frame for frame in traceback.extract_tb(error.__traceback__)
                  if Path(frame.filename).resolve() == Path(__file__).resolve()]
        print(json.dumps({"result": "failed", "type": type(error).__name__,
                          "checkLine": frames[-1].lineno if frames else None,
                          "callerLine": frames[-2].lineno if len(frames) >= 2 else None,
                          "message": str(error) if isinstance(error, ValueError) or
                                     (frames and frames[-1].name == "_require") else "see isolated rehearsal checks"}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
