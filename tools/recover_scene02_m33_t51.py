"""Authorized, one-shot cj02 recovery; no migration, installation or execution.

Each phase leaves evidence and refuses replay. Credentials stay in memory.
Only normal authenticated/CAS APIs can change the assignment and scene.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import settings

EVIDENCE = ROOT / "evidence/M33/M33-T51"
PROJECT = "00000000-0000-0000-0000-000000000001"
PREFIX = f"/aiyoloapi/projects/{PROJECT}"
SCENE = "cj02"
BAD = "cebb3b7b-0a84-4867-abcd-2264bf1ac4e8"
GOOD = "b4aed738-1dd9-4439-a172-da7c881473e1"
EXPECTED = {BAD: ("uploaded-c8dffd82f6a24deca8d03afdae24956f", "1.0.0", "mobile"),
            GOOD: ("uploaded-06b4dd2f10544673ab723226f91c34a7", "2.0.0", "mobile")}
VALUES = ("detection", "alertRules", "revision", "inheritedRevision")
META = {"schemaVersion", "source", "updatedAt"}
PROTECTED = ("accounts", "projects", "project_memberships", "project_model_assignments",
             "project_scenes", "project_scene_members", "project_scene_plans")
BASE = "http://127.0.0.1:8080"


def save(name, value):
    (EVIDENCE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def check(name, condition, result):
    result["checks"][name] = bool(condition)
    if not condition:
        raise RuntimeError("Check failed: " + name)


def config(scene):
    return {k: scene.get(k) for k in ("projectId", "sceneId", "name", "inputTypes", "enabled", "plans")} | {
        "models": [{k: m.get(k) for k in ("memberId", "projectModelId", "modelId", "version", "target",
                    "position", "inputTypes", "execution", "parameterRevision")} for m in scene["models"]]}


def db_state():
    if any(os.environ.get(k) for k in ("DATABASE_URL", "DEPLOYMENT_ENV", "PGOPTIONS", "PGSERVICE")):
        raise RuntimeError("Unexpected database/environment override")
    url = make_url(settings.database_url)
    if (settings.deployment_env != "development" or url.host != "127.0.0.1"
            or url.database != "aiyolo_dev" or url.query):
        raise RuntimeError("Unexpected development database")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            revision = connection.scalar(text("SELECT version_num FROM public.alembic_version"))
            tables = {}
            for table in PROTECTED:
                if connection.scalar(text("SELECT to_regclass(:t)"), {"t": "public." + table}) is None:
                    continue
                rows = connection.scalars(text(f'SELECT to_jsonb(t)::text FROM public."{table}" t ORDER BY 1')).all()
                tables[table] = {"count": len(rows), "sha256": hashlib.sha256("\n".join(rows).encode()).hexdigest()}
            return {"schemaRevision": revision, "tables": tables,
                    "registrySha256": hashlib.sha256((ROOT / "models/registry.json").read_bytes()).hexdigest()}
    finally:
        engine.dispose()


def db_profiles():
    url = make_url(settings.database_url)
    if url.host != "127.0.0.1" or url.database != "aiyolo_dev" or url.query:
        raise RuntimeError("Unexpected database for read-only snapshot verification")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            return dict(connection.execute(text("SELECT assignment_id, parameter_snapshot FROM "
                "public.project_model_assignments WHERE project_id=:project"), {"project": PROJECT}).all())
    finally:
        engine.dispose()


class Api:
    def __init__(self, result):
        self.result = result
        self.client = httpx.Client(base_url=BASE, timeout=30)
        self.logged_in = False

    def call(self, method, path, payload=None, expected=200):
        response = self.client.request(method, path, json=payload,
            headers={"X-Request-ID": "m33-t51-" + uuid4().hex})
        self.result.setdefault("http", []).append({"method": method, "path": path, "status": response.status_code})
        if response.status_code != expected:
            raise RuntimeError(f"HTTP {response.status_code}: {method} {path}; no automatic retry")
        return response.json()

    def login(self):
        fixture = (ROOT.parent / "harness/TEST_ACCOUNTS.md").read_text(encoding="utf-8-sig")
        match = re.search(r"\|\s*`admin`\s*\|\s*`([^`]+)`", fixture)
        if match is None:
            raise RuntimeError("Documented local admin fixture unavailable")
        self.call("POST", "/aiyoloapi/auth/login", {"username": "admin", "password": match[1]})
        self.logged_in = True

    def snapshot(self):
        scenes = self.call("GET", PREFIX + "/scenes")["scenes"]
        return {"assignments": self.call("GET", PREFIX + "/model-assignments")["assignments"],
                "scenes": {s["sceneId"]: self.call("GET", PREFIX + "/scenes/" + s["sceneId"]) for s in scenes},
                "profiles": db_profiles()}

    def close(self):
        try:
            if self.logged_in:
                self.call("POST", "/aiyoloapi/auth/logout")
                self.result["createdSessionRevoked"] = True
        finally:
            self.client.close()


def preflight(result):
    api = Api(result)
    try:
        api.login()
        state = api.snapshot()
        scene = state["scenes"][SCENE]
        assignments = {a["projectModelId"]: a for a in state["assignments"]}
        check("original_scene_r2_enabled_approved", scene["revision"] == 2 and scene["enabled"] and scene["approved"], result)
        check("exact_two_expected_mobile_members", len(scene["models"]) == 2 and
              {m["projectModelId"] for m in scene["models"]} == set(EXPECTED), result)
        available = api.call("GET", PREFIX + "/models/available")["models"]
        for member in scene["models"]:
            identity = EXPECTED[member["projectModelId"]]
            assignment = assignments[member["projectModelId"]]
            check("identity_" + member["projectModelId"],
                  (member["modelId"], member["version"], member["target"]) == identity and
                  (assignment["modelId"], assignment["modelVersion"], assignment["target"]) == identity, result)
            profile = next(m for m in available if (m["modelId"], m["version"]) == identity[:2])["parameterProfiles"]["android"]
            check("current_values_match_frozen_" + member["projectModelId"], all(
                profile.get(k) == member["parameterSnapshot"].get(k) for k in VALUES), result)
            check("profile_complete_" + member["projectModelId"], META <= set(profile) and
                  profile["schemaVersion"] == 2 and profile["source"] in {"default", "custom", "inherited"} and
                  profile["revision"] == assignment["parameterRevision"], result)
        check("bad_assignment_r1_enabled_missing_metadata", assignments[BAD]["revision"] == 1 and
              assignments[BAD]["enabled"] and not (META & set(state["profiles"][BAD])), result)
        check("good_assignment_complete_r2", assignments[GOOD]["revision"] == 2 and
              META <= set(state["profiles"][GOOD]), result)
        health = api.call("GET", "/healthz")
        check("healthy_idle", health.get("status") == "ok" and health.get("streams") == 0, result)
        state["dbState"] = db_state()
        save("before.json", state)
    finally:
        api.close()


def process_identity(stop=False):
    expected = f'"{ROOT / ".venv/Scripts/python.exe"}" -m uvicorn app.main:app --host 0.0.0.0 --port 8080'
    code = ("$ErrorActionPreference='Stop'; "
        "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=32220'; "
        "$q=Get-CimInstance Win32_Process -Filter 'ProcessId=59612'; "
        "$l=@(Get-NetTCPConnection -LocalPort 8080 -State Listen); "
        f"$expected='{expected}'; "
        "if (-not $p -or -not $q -or $p.ParentProcessId -ne 59612 -or $l.Count -ne 1 -or "
        "$l[0].OwningProcess -ne 32220 -or $l[0].LocalAddress -ne '0.0.0.0' -or "
        "$p.CommandLine.Trim() -ne $expected -or $q.CommandLine.Trim() -ne $expected) "
        "{throw 'Service identity changed; refusing restart'}; "
        + ("Stop-Process -Id 32220,59612 -ErrorAction Stop" if stop else "Write-Output 'identity verified'"))
    response = subprocess.run(["powershell.exe", "-NoProfile", "-Command", code], cwd=ROOT,
        capture_output=True, text=True, timeout=15)
    if response.returncode:
        raise RuntimeError("Service identity verification/stop failed")


def refresh(result):
    before = json.loads((EVIDENCE / "before.json").read_text(encoding="utf-8"))
    check("database_unchanged_since_preflight", db_state() == before["dbState"], result)
    with httpx.Client(base_url=BASE, timeout=10) as client:
        health = client.get("/healthz").json()
        check("healthy_idle_immediately_before_restart", health.get("status") == "ok" and health.get("streams") == 0, result)
    process_identity()
    process_identity(stop=True)
    result["oldProcessIds"] = [32220, 59612]
    for _ in range(40):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 8080)) != 0:
                break
        time.sleep(0.1)
    else:
        raise RuntimeError("8080 still listening; do not start duplicate service")
    logs = ROOT / ".tmp" / ("m33-t51-service-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    logs.mkdir(parents=True, exist_ok=False)
    with (logs / "stdout.log").open("ab") as out, (logs / "stderr.log").open("ab") as err:
        process = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), "-m", "uvicorn", "app.main:app",
            "--host", "0.0.0.0", "--port", "8080"], cwd=ROOT, stdin=subprocess.DEVNULL,
            stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
    result.update(newLauncherPid=process.pid, privateRuntimeLogs=str(logs), bind="0.0.0.0:8080")
    save("refresh-progress.json", result)
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError("Service exited; inspect startup log before any recovery action")
        try:
            with httpx.Client(base_url=BASE, timeout=1) as client:
                response = client.get("/healthz")
                if response.status_code == 200 and response.json().get("status") == "ok":
                    result["health"] = response.json()
                    break
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    else:
        raise RuntimeError("Startup health check timed out; inspect current process before retry")
    check("configuration_database_registry_unchanged_by_restart", db_state() == before["dbState"], result)
    result["sceneSourceSha256"] = hashlib.sha256((ROOT / "app/project_scenes.py").read_bytes()).hexdigest()


def recover(result):
    before = json.loads((EVIDENCE / "before.json").read_text(encoding="utf-8"))
    refreshed = json.loads((EVIDENCE / "refresh-result.json").read_text(encoding="utf-8"))
    check("refresh_succeeded", refreshed["outcome"] == "passed", result)
    api = Api(result)
    try:
        api.login()
        check("configuration_unchanged_before_mutation", api.snapshot() ==
              {k: before[k] for k in ("assignments", "scenes", "profiles")}, result)
        scene = before["scenes"][SCENE]
        # Confirms the running service loaded M33-T50; this must fail without mutation.
        denied = api.call("POST", PREFIX + f"/scenes/{SCENE}/approval", {
            "approved": True, "expectedRevision": 2, "reason": "M33-T51：核验不完整快照被拒绝，不改变审批"}, expected=409)
        check("live_guard_identifies_exact_bad_assignment", denied.get("detail", {}).get("code") ==
              "project_model_snapshot_invalid" and denied["detail"].get("projectModelId") == BAD, result)
        check("rejected_approval_preserves_all_configuration", api.snapshot() ==
              {k: before[k] for k in ("assignments", "scenes", "profiles")}, result)
        old = next(a for a in before["assignments"] if a["projectModelId"] == BAD)
        saved = api.call("PUT", PREFIX + "/model-assignments", {
            "modelId": old["modelId"], "modelVersion": old["modelVersion"], "target": "mobile",
            "parameterRevision": old["parameterRevision"], "enabled": old["enabled"], "expectedRevision": 1})
        check("only_bad_assignment_saved_r2", saved["projectModelId"] == BAD and saved["revision"] == 2, result)
        saved_profile = db_profiles()[BAD]
        check("assignment_parameter_values_unchanged", all(
            saved_profile.get(k) == before["profiles"][BAD].get(k) for k in VALUES), result)
        check("scene_not_implicitly_edited", api.call("GET", PREFIX + f"/scenes/{SCENE}") == scene, result)
        api.call("POST", PREFIX + f"/scenes/{SCENE}/approval", {"approved": True, "expectedRevision": 2,
            "reason": "用户授权bug修复：恢复ppe移动端完整参数快照；参数值、成员、输入及方案不变；待人工复测"})
        after = api.snapshot()
        new_scene = after["scenes"][SCENE]
        check("scene_r3_enabled_approved", new_scene["revision"] == 3 and new_scene["enabled"] and new_scene["approved"], result)
        check("scene_configuration_unchanged", config(new_scene) == config(scene), result)
        check("other_scenes_unchanged", {k: v for k, v in after["scenes"].items() if k != SCENE} ==
              {k: v for k, v in before["scenes"].items() if k != SCENE}, result)
        other = lambda rows: sorted((a for a in rows if a["projectModelId"] != BAD), key=lambda a: a["projectModelId"])
        check("other_assignments_unchanged", other(after["assignments"]) == other(before["assignments"]), result)
        check("other_assignment_snapshots_unchanged", {k: v for k, v in after["profiles"].items() if k != BAD} ==
              {k: v for k, v in before["profiles"].items() if k != BAD}, result)
        for previous, member in zip(scene["models"], new_scene["models"]):
            p = member["parameterSnapshot"]
            check("complete_snapshot_" + member["projectModelId"], META <= set(p) and
                  p["schemaVersion"] == 2 and p["source"] in {"default", "custom", "inherited"}, result)
            check("frozen_values_unchanged_" + member["projectModelId"], all(
                p.get(k) == previous["parameterSnapshot"].get(k) for k in VALUES), result)
        catalog = api.call("GET", PREFIX + "/scenes?target=mobile")
        check("mobile_catalog_cj02_available_r3", any(s["sceneId"] == SCENE and s["revision"] == 3 and
              s["available"] for s in catalog["scenes"]), result)
        save("after.json", after)
        save("mobile-catalog.json", catalog)
    finally:
        api.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("preflight", "refresh", "recover"))
    parser.add_argument("--preflight-attempt", type=int, default=1)
    args = parser.parse_args()
    phase = args.phase
    if args.preflight_attempt < 1 or (phase != "preflight" and args.preflight_attempt != 1):
        raise RuntimeError("Only read-only preflight can have an additional numbered attempt")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    filename = phase + "-result.json"
    if phase == "preflight" and args.preflight_attempt != 1:
        filename = f"preflight-result-attempt{args.preflight_attempt}.json"
    if (EVIDENCE / filename).exists():
        raise RuntimeError("Phase result exists; inspect before any repeat")
    result = {"taskId": "M33-T51", "phase": phase, "humanStatus": "待人工复测", "checks": {},
              "startedAt": datetime.now().astimezone().isoformat()}
    try:
        {"preflight": preflight, "refresh": refresh, "recover": recover}[phase](result)
        result["outcome"] = "passed"
    except Exception as error:
        result["outcome"] = "stopped_inspect_before_retry"
        result["error"] = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        raise RuntimeError("Recovery stopped; inspect phase result before retry") from None
    finally:
        result["endedAt"] = datetime.now().astimezone().isoformat()
        save(filename, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
