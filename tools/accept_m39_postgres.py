"""Run M39 regression on a disposable loopback PostgreSQL; never use .env DB."""
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


def main():
    runtime = Path(tempfile.mkdtemp(prefix="m39-pg-", dir=ROOT / ".tmp")).resolve()
    data = runtime / "pg-data"
    assert data.parent == runtime and runtime.parent == (ROOT / ".tmp").resolve()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"postgresql+psycopg://aiyolo_app@127.0.0.1:{port}/postgres"
    env = os.environ.copy()
    env.update(DATABASE_URL=url, RUN_POSTGRES_TESTS="1")
    result = {"startedAt": datetime.now(timezone.utc).isoformat(), "runtime": str(runtime),
        "dataDirectory": str(data), "host": "127.0.0.1", "port": port,
        "user": "aiyolo_app", "database": "postgres", "tests": []}
    started = False
    try:
        with (runtime / "runner.log").open("w", encoding="utf-8") as log:
            subprocess.run([str(PG / "initdb.exe"), "-D", str(data), "-U", "aiyolo_app",
                "--auth-local=trust", "--auth-host=trust", "--encoding=UTF8", "--locale=C"],
                check=True, stdout=log, stderr=log)
            subprocess.run([str(PG / "pg_ctl.exe"), "-D", str(data), "-l", str(runtime / "postgres.log"),
                "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"], check=True, stdout=log, stderr=log)
            started = True
            engine = create_engine(url)
            try:
                with engine.connect() as connection:
                    assert Path(connection.execute(text("SHOW data_directory")).scalar_one()).resolve() == data
                    assert connection.execute(text("SELECT current_user")).scalar_one() == "aiyolo_app"
                    result["pid"] = int((data / "postmaster.pid").read_text().splitlines()[0])
            finally:
                engine.dispose()
            print(f"Isolated PostgreSQL verified: 127.0.0.1:{port}/postgres as aiyolo_app; {runtime}", flush=True)
            for pattern in ("test_scene_composite_runtime_grants.py", "test_scene_execution_parameters.py",
                            "test_project_scenes.py", "test_project_scene_suite_persistence.py",
                            "test_database.py"):
                target = runtime / (pattern + ".log")
                with target.open("w", encoding="utf-8") as output:
                    test = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests",
                        "-p", pattern, "-v"], cwd=ROOT, env=env, stdout=output, stderr=output)
                result["tests"].append({"pattern": pattern, "exitCode": test.returncode, "log": str(target)})
                print(f"{pattern}: exit {test.returncode}", flush=True)
            engine = create_engine(url)
            try:
                with engine.connect() as connection:
                    schemas = connection.execute(text("SELECT nspname FROM pg_namespace WHERE "
                        "nspname NOT LIKE 'pg_%' AND nspname NOT IN ('public', 'information_schema')")).scalars().all()
                    result["remainingTestSchemas"] = schemas
                    assert not schemas, "test schema cleanup failed"
            finally:
                engine.dispose()
            result["testsCompleted"] = True
    finally:
        if started:
            subprocess.run([str(PG / "pg_ctl.exe"), "-D", str(data), "-m", "fast", "-w", "stop"], check=True)
        with socket.socket() as sock:
            sock.settimeout(2)
            result["portClosed"] = sock.connect_ex(("127.0.0.1", port)) != 0
        result["completedAt"] = datetime.now(timezone.utc).isoformat()
        result["passed"] = (result.get("testsCompleted", False) and bool(result["tests"])
            and all(t["exitCode"] == 0 for t in result["tests"]) and result["portClosed"])
        evidence = ROOT / "harness/evidence/M39"
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / "postgres-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
