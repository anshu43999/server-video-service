"""M33-T50: run approval regressions only in a disposable PostgreSQL cluster."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence/M33/M33-T50"
PG = Path(r"D:\PostgreSQL\bin")


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (ROOT / ".tmp").mkdir(exist_ok=True)
    runtime = Path(tempfile.mkdtemp(prefix="m33-t50-pg-", dir=ROOT / ".tmp")).resolve()
    data = runtime / "data"
    assert runtime.parent == (ROOT / ".tmp").resolve() and data.parent == runtime
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"postgresql+psycopg://aiyolo_app@127.0.0.1:{port}/postgres"
    env = dict(os.environ, DATABASE_URL=url, RUN_POSTGRES_TESTS="1", PYTHONPATH="tests", PYTHONUTF8="1")
    result = {"runtime": str(runtime), "port": port, "dataDirectory": str(data), "tests": []}
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
                    assert Path(connection.scalar(text("SHOW data_directory"))).resolve() == data
                    assert connection.scalar(text("SELECT current_user")) == "aiyolo_app"
                    assert connection.scalar(text("SELECT current_database()")) == "postgres"
                for name in ("test_scene_snapshot_approval.SceneSnapshotApprovalPostgresTests",
                             "test_scene_execution_parameters.SceneParameterPostgresTests",
                             "test_project_model_inventory.ProjectModelInventoryPostgreSqlTests"):
                    target = EVIDENCE / (name.split(".")[-1] + ".log")
                    with target.open("w", encoding="utf-8") as output:
                        test = subprocess.run([sys.executable, "-m", "unittest", name, "-v"],
                            cwd=ROOT, env=env, stdout=output, stderr=output)
                    result["tests"].append({"name": name, "exitCode": test.returncode, "log": str(target)})
                    print(f"{name}: exit {test.returncode}", flush=True)
                with engine.connect() as connection:
                    schemas = connection.scalars(text("SELECT nspname FROM pg_namespace WHERE "
                        "nspname NOT LIKE 'pg_%' AND nspname NOT IN ('public','information_schema')")).all()
                    assert not schemas, schemas
                    result["remainingSchemas"] = schemas
            finally:
                engine.dispose()
    finally:
        if started:
            subprocess.run([str(PG / "pg_ctl.exe"), "-D", str(data), "-m", "fast", "-w", "stop"], check=True)
        with socket.socket() as sock:
            result["portClosed"] = sock.connect_ex(("127.0.0.1", port)) != 0
        result["passed"] = bool(len(result["tests"]) == 3 and
            all(item["exitCode"] == 0 for item in result["tests"]) and result["portClosed"])
        report = json.dumps(result, indent=2)
        (runtime / "result.json").write_text(report, encoding="utf-8")
        (EVIDENCE / "postgres-result.json").write_text(report, encoding="utf-8")
        print(report, flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
