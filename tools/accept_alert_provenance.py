"""M29-T19: isolated PostgreSQL regressions; never use the application database."""
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
    runtime = Path(tempfile.mkdtemp(prefix="alert-provenance-", dir=ROOT / ".tmp")).resolve()
    data = runtime / "pg-data"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"postgresql+psycopg://aiyolo_app@127.0.0.1:{port}/postgres"
    env = {**os.environ, "DATABASE_URL": url, "RUN_POSTGRES_TESTS": "1", "PYTHONUTF8": "1", "MINIO_ENDPOINT": ""}
    result = {"endpoint": url, "dataDirectory": str(data), "tests": []}
    started = False
    try:
        assert runtime.parent == (ROOT / ".tmp").resolve() and data.parent == runtime
        with (runtime / "runner.log").open("w", encoding="utf-8") as output:
            subprocess.run([str(PG / "initdb.exe"), "-D", str(data), "-U", "aiyolo_app",
                            "--auth-local=trust", "--auth-host=trust", "--encoding=UTF8", "--locale=C"],
                           check=True, stdout=output, stderr=output)
            subprocess.run([str(PG / "pg_ctl.exe"), "-D", str(data), "-l", str(runtime / "postgres.log"),
                            "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"], check=True, stdout=output, stderr=output)
        started = True
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                assert Path(connection.execute(text("SHOW data_directory")).scalar_one()).resolve() == data
                assert connection.execute(text("SELECT current_user")).scalar_one() == "aiyolo_app"
        finally:
            engine.dispose()
        for pattern in ["test_alert_postgresql.py", "test_mobile_alert_ingest.py", "test_alert_persistence.py", "test_alert_disposition.py"]:
            test_env = env if pattern == "test_alert_postgresql.py" else {**env, "DATABASE_URL": "", "RUN_POSTGRES_TESTS": "0"}
            log = runtime / (pattern + ".log")
            with log.open("w", encoding="utf-8") as output:
                process = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", pattern, "-v"],
                                         cwd=ROOT, env=test_env, stdout=output, stderr=output)
            result["tests"].append({"pattern": pattern, "exitCode": process.returncode, "log": str(log)})
            print(f"{pattern}: exit {process.returncode}; {log}", flush=True)
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                schemas = connection.execute(text("SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' "
                                                   "AND nspname NOT IN ('public','information_schema')")).scalars().all()
                assert not schemas, schemas
                result["remainingTestSchemas"] = schemas
        finally:
            engine.dispose()
    finally:
        if started:
            subprocess.run([str(PG / "pg_ctl.exe"), "-D", str(data), "-m", "fast", "-w", "stop"], check=True)
        with socket.socket() as sock:
            result["portClosed"] = sock.connect_ex(("127.0.0.1", port)) != 0
        result["passed"] = len(result["tests"]) == 4 and all(row["exitCode"] == 0 for row in result["tests"]) and result["portClosed"]
        (runtime / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(runtime / "result.json", flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
