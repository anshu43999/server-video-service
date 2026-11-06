"""Verify M42-T01 on a disposable cluster, never the configured application DB."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
PG = Path(r"D:\PostgreSQL\bin")


def main(*, task="T01", patterns=None, test_env=None, test_timeout=180):
    if not 1 <= test_timeout <= 1200:
        raise ValueError("test timeout must stay within twenty minutes")
    runtime = Path(tempfile.mkdtemp(prefix="m42-contract-", dir=ROOT / ".tmp")).resolve()
    data = runtime / "pg-data"
    assert runtime.parent == (ROOT / ".tmp").resolve() and data.parent == runtime
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert port != 5432
    url = f"postgresql+psycopg://aiyolo_app@127.0.0.1:{port}/postgres"
    env = os.environ.copy()
    env.update(DATABASE_URL=url, RUN_POSTGRES_TESTS="1", PYTHONUTF8="1")
    env.update(test_env or {})
    evidence = ROOT / "harness/evidence/M42"
    evidence.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    env.setdefault("APK_TEST_EVIDENCE_ROOT", str(evidence / (task + "-" + run_id + "-raw")))
    result = dict(startedAt=datetime.now(timezone.utc).isoformat(), runtime=str(runtime),
                  dataDirectory=str(data), user="aiyolo_app", host="127.0.0.1", port=port,
                  database="postgres", tests=[])
    started = False
    try:
        with (runtime / "runner.log").open("w", encoding="utf-8") as log:
            subprocess.run([str(PG / "initdb.exe"), "-D", str(data), "-U", "aiyolo_app",
                "--auth-local=trust", "--auth-host=trust", "--encoding=UTF8", "--locale=C"],
                check=True, stdout=log, stderr=log, timeout=60)
            subprocess.run([str(PG / "pg_ctl.exe"), "-D", str(data), "-l", str(runtime / "postgres.log"),
                "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"], check=True, stdout=log, stderr=log, timeout=60)
            started = True
            engine = create_engine(url)
            try:
                with engine.connect() as connection:
                    assert Path(connection.execute(text("SHOW data_directory")).scalar_one()).resolve() == data
                    assert int(connection.execute(text("SHOW port")).scalar_one()) == port
                    assert connection.execute(text("SELECT current_user")).scalar_one() == "aiyolo_app"
                    result["pid"] = int((data / "postmaster.pid").read_text().splitlines()[0])
            finally:
                engine.dispose()
            print(f"Verified isolated PostgreSQL: 127.0.0.1:{port}/postgres, role=aiyolo_app", flush=True)
            for pattern in patterns or ("test_app_update_*.py", "test_database.py", "test_alert_advice_knowledge_migration.py"):
                target = evidence / (task + "-" + run_id + "-" + pattern.replace("*", "all") + ".log")
                with target.open("w", encoding="utf-8") as output:
                    test = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests",
                        "-p", pattern, "-v"], cwd=ROOT, env=env, stdout=output, stderr=output, timeout=test_timeout)
                result["tests"].append(dict(pattern=pattern, exitCode=test.returncode,
                    log=target.relative_to(ROOT).as_posix()))
                print(f"{pattern}: exit {test.returncode}", flush=True)
            engine = create_engine(url)
            try:
                with engine.connect() as connection:
                    schemas = connection.execute(text("SELECT nspname FROM pg_namespace WHERE "
                        "nspname NOT LIKE 'pg_%' AND nspname NOT IN ('public', 'information_schema')")).scalars().all()
                    result["remainingTestSchemas"] = schemas
                    assert not schemas, "test schemas were not cleaned"
            finally:
                engine.dispose()
            result["testsCompleted"] = True
    finally:
        # Scope stop to the exact cluster, including startup-timeout cleanup.
        if started or (data / "postmaster.pid").exists():
            subprocess.run([str(PG / "pg_ctl.exe"), "-D", str(data), "-m", "fast", "-w", "stop"],
                           check=True, stdout=subprocess.DEVNULL, timeout=60)
        with socket.socket() as sock:
            sock.settimeout(2)
            result["portClosed"] = sock.connect_ex(("127.0.0.1", port)) != 0
        result["completedAt"] = datetime.now(timezone.utc).isoformat()
        result["passed"] = bool(result.get("testsCompleted") and result["tests"]
            and all(t["exitCode"] == 0 for t in result["tests"]) and result["portClosed"])
        (evidence / (task + "-result.json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
        (evidence / (task + "-" + run_id + "-result.json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
