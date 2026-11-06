"""M33-T48: disposable PostgreSQL checks and real-catalog/isolated-DB fixture.

Never uses the application database, republishes a model, or modifies an
existing project. The exported catalog is for Android decoding, not execution.
"""
from __future__ import annotations

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
EVIDENCE = ROOT / "evidence/M33/M33-T48"


def export_catalog(runtime):
    os.environ["DATABASE_URL"] = ""
    sys.path.insert(0, str(ROOT))
    from app.database import Base, DatabaseManager, DEFAULT_PROJECT_ID, ProjectRecord
    from app.model_catalog import ModelCatalog
    from app.model_parameters import ModelParameterStore
    from app.project_model_assignments import ProjectModelAssignments
    from app.project_scenes import ProjectScenes

    db = DatabaseManager("sqlite:///" + (runtime / "fixture.db").as_posix())
    try:
        Base.metadata.create_all(db.engine)
        project_id = "snapshot-contract-project"
        with db.session() as session:
            for identity in (DEFAULT_PROJECT_ID, project_id):
                session.add(ProjectRecord(project_id=identity, project_code=identity,
                    display_name=identity, lifecycle_state="ACTIVE"))
        catalog = ModelCatalog(ROOT / "models/registry.json")  # read-only assets
        profiles = ModelParameterStore(runtime / "parameters.json", db)
        assignments = ProjectModelAssignments(db, catalog, profiles)
        scenes = ProjectScenes(db, catalog, assignments)
        members = []
        for position, (model_id, version, target) in enumerate((
            ("uploaded-06b4dd2f10544673ab723226f91c34a7", "2.0.0", "mobile"),
            ("uploaded-c8dffd82f6a24deca8d03afdae24956f", "1.0.0", "pc"),
        )):
            item = assignments.save(project_id, model_id, version, target, 0, True, 0)
            members.append({"projectModelId": item["projectModelId"], "position": position,
                "execution": "single", "inputTypes": ["image"]})
        scenes.save(project_id, "metadata", {"name": "参数契约回归", "enabled": True,
            "inputTypes": ["image"], "models": members, "plans": []}, 0, creating=True)
        scenes.save(project_id, "metadata", {"approved": True}, 1, approval_reason="isolated automated check")
        rows = scenes.list_catalog(project_id, manage=False)
        assert len(rows) == 1 and rows[0]["available"]
        assert all(m["executionReady"] and m["parameterSnapshot"]["schemaVersion"] == 2
            and m["parameterSnapshot"]["source"] == "inherited" for m in rows[0]["models"])
        payload = {"projectId": project_id, "scenes": rows}
        (EVIDENCE / "android-catalog.json").write_text(json.dumps(payload,
            ensure_ascii=False, indent=2), encoding="utf-8")
        return {"catalog": "evidence/M33/M33-T48/android-catalog.json", "sceneCount": len(rows),
            "memberTargets": [m["target"] for m in rows[0]["models"]], "plans": 0}
    finally:
        db.close()


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (ROOT / ".tmp").mkdir(exist_ok=True)
    runtime = Path(tempfile.mkdtemp(prefix="m33-t48-pg-", dir=ROOT / ".tmp")).resolve()
    data = runtime / "pg-data"
    assert data.parent == runtime and runtime.parent == (ROOT / ".tmp").resolve()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"postgresql+psycopg://aiyolo_app@127.0.0.1:{port}/postgres"
    env = dict(os.environ, DATABASE_URL=url, RUN_POSTGRES_TESTS="1", PYTHONPATH="tests", PYTHONUTF8="1")
    result = {"runtime": str(runtime), "dataDirectory": str(data), "port": port, "tests": []}
    started = False
    try:
        with (EVIDENCE / "postgres-runner.log").open("w", encoding="utf-8") as log:
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
                print(f"Verified isolated PostgreSQL: 127.0.0.1:{port}/postgres; {data}", flush=True)
                for name in ("test_project_model_inventory.ProjectModelInventoryPostgreSqlTests",
                             "test_scene_execution_parameters.SceneParameterPostgresTests"):
                    target = EVIDENCE / (name.split(".")[-1] + ".log")
                    with target.open("w", encoding="utf-8") as output:
                        check = subprocess.run([sys.executable, "-m", "unittest", name, "-v"],
                            cwd=ROOT, env=env, stdout=output, stderr=output)
                    result["tests"].append({"name": name, "exitCode": check.returncode, "log": str(target)})
                    print(f"{name}: exit {check.returncode}", flush=True)
                with engine.connect() as connection:
                    schemas = connection.scalars(text("SELECT nspname FROM pg_namespace WHERE "
                        "nspname NOT LIKE 'pg_%' AND nspname NOT IN ('public','information_schema')")).all()
                    assert not schemas, schemas
                    result["remainingTestSchemas"] = schemas
            finally:
                engine.dispose()
        result["fixture"] = export_catalog(runtime)
    finally:
        if started:
            subprocess.run([str(PG / "pg_ctl.exe"), "-D", str(data), "-m", "fast", "-w", "stop"], check=True)
        with socket.socket() as sock:
            result["portClosed"] = sock.connect_ex(("127.0.0.1", port)) != 0
        result["passed"] = bool(result.get("fixture") and result["tests"]
            and all(t["exitCode"] == 0 for t in result["tests"]) and result["portClosed"])
        (EVIDENCE / "postgres-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
