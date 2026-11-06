"""One authorized recovery of test01 through normal authenticated/CAS HTTP APIs.

No SQL writes, snapshot patching, installation, or execution. A repeated run
stops before writes once the original assignment/scene revisions have changed.
Credentials are read from the workspace test-account fixture and never logged.
"""
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence/M33/M33-T49"
PROJECT = "00000000-0000-0000-0000-000000000001"
PREFIX = f"/aiyoloapi/projects/{PROJECT}"
SCENE = "test01"
EXPECTED = {
    "b4aed738-1dd9-4439-a172-da7c881473e1":
        ("uploaded-06b4dd2f10544673ab723226f91c34a7", "2.0.0", "mobile"),
    "3c13061c-a389-40d8-bfc1-eac88380449f":
        ("uploaded-c8dffd82f6a24deca8d03afdae24956f", "1.0.0", "pc"),
}
VALUE_FIELDS = ("detection", "alertRules", "revision", "inheritedRevision")
SNAPSHOT_FIELDS = {"schemaVersion", "source", "updatedAt", "projectId", "modelId",
                   "modelVersion", "platform", "revision", "inheritedRevision",
                   "detection", "alertRules"}


def configuration(scene):
    return {"projectId": scene["projectId"], "sceneId": scene["sceneId"],
            "name": scene["name"], "inputTypes": scene["inputTypes"],
            "enabled": scene["enabled"], "plans": scene["plans"],
            "models": [{k: m.get(k) for k in ("memberId", "projectModelId", "modelId",
                "version", "target", "position", "inputTypes", "execution", "parameterRevision")}
                for m in scene["models"]]}


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    if (EVIDENCE / "result.json").exists():
        raise RuntimeError("An execution result exists; inspect it instead of replaying mutations")
    opener = build_opener(HTTPCookieProcessor())
    trace = []
    result = {"taskId": "M33-T49", "projectId": PROJECT, "sceneId": SCENE,
              "humanStatus": "待人工复测", "checks": {}}

    def request(method, path, payload=None):
        headers = {"Content-Type": "application/json", "X-Request-ID": "m33-t49-" + uuid4().hex}
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = Request("http://127.0.0.1:8080" + path, data=data, headers=headers, method=method)
        try:
            with opener.open(req, timeout=30) as response:
                trace.append({"method": method, "path": path, "status": response.status})
                return json.load(response)
        except HTTPError as exc:
            trace.append({"method": method, "path": path, "status": exc.code})
            raise RuntimeError(f"HTTP {exc.code}: {method} {path}; no automatic retry") from None

    def check(name, condition):
        result["checks"][name] = bool(condition)
        if not condition:
            raise RuntimeError("Check failed: " + name)

    logged_in = False
    try:
        fixture = (ROOT.parent / "harness/TEST_ACCOUNTS.md").read_text(encoding="utf-8")
        credentials = re.search(r"\| `admin` \| `([^`]+)` \|", fixture)
        if credentials is None:
            raise RuntimeError("Documented local admin fixture unavailable")
        request("POST", "/aiyoloapi/auth/login", {"username": "admin", "password": credentials[1]})
        logged_in = True
        before = request("GET", PREFIX + "/scenes/" + SCENE)
        assignments = request("GET", PREFIX + "/model-assignments")["assignments"]
        available = request("GET", PREFIX + "/models/available")["models"]
        check("original_scene_revision_2_enabled_approved", before["revision"] == 2
              and before["enabled"] and before["approved"])
        check("only_expected_two_members", {m["projectModelId"] for m in before["models"]} == set(EXPECTED)
              and len(before["models"]) == 2)
        selected = {a["projectModelId"]: a for a in assignments if a["projectModelId"] in EXPECTED}
        for member in before["models"]:
            identity = EXPECTED[member["projectModelId"]]
            assignment = selected[member["projectModelId"]]
            check("identity_" + member["target"],
                (member["modelId"], member["version"], member["target"]) == identity
                and (assignment["modelId"], assignment["modelVersion"], assignment["target"]) == identity)
            check("original_assignment_" + member["target"], assignment["revision"] == 1 and assignment["enabled"])
            model = next(m for m in available if (m["modelId"], m["version"]) == identity[:2])
            platform = "android" if identity[2] == "mobile" else "server"
            profile = model["parameterProfiles"][platform]
            check("pending_parameters_unchanged_" + member["target"], all(
                profile.get(k) == member["parameterSnapshot"].get(k) for k in VALUE_FIELDS))
            check("pending_contract_valid_" + member["target"], profile["schemaVersion"] == 2
                and profile["source"] in {"default", "custom", "inherited"}
                and profile["revision"] == assignment["parameterRevision"])
        (EVIDENCE / "before.json").write_text(json.dumps(
            {"scene": before, "assignments": assignments}, ensure_ascii=False, indent=2), encoding="utf-8")
        for identity_id, identity in EXPECTED.items():
            old = selected[identity_id]
            updated = request("PUT", PREFIX + "/model-assignments", {
                "modelId": identity[0], "modelVersion": identity[1], "target": identity[2],
                "parameterRevision": old["parameterRevision"], "enabled": old["enabled"],
                "expectedRevision": old["revision"]})
            check("assignment_saved_" + identity[2], updated["projectModelId"] == identity_id
                  and updated["revision"] == old["revision"] + 1)
        pending = request("GET", PREFIX + "/scenes/" + SCENE)
        check("scene_not_implicitly_approved_or_edited", pending["revision"] == before["revision"]
              and configuration(pending) == configuration(before))
        request("POST", PREFIX + "/scenes/" + SCENE + "/approval", {
            "approved": True, "expectedRevision": before["revision"],
            "reason": "用户明确授权重新保存：恢复完整参数快照，检测/告警参数、成员、输入及方案保持不变；待人工复测"})
        after = request("GET", PREFIX + "/scenes/" + SCENE)
        after_assignments = request("GET", PREFIX + "/model-assignments")["assignments"]
        catalog = request("GET", PREFIX + "/scenes?target=mobile")
        check("scene_revision_3_approved", after["revision"] == 3 and after["approved"])
        check("configuration_unchanged", configuration(after) == configuration(before))
        for old_member, new_member in zip(before["models"], after["models"]):
            snapshot = new_member["parameterSnapshot"]
            check("snapshot_complete_" + new_member["target"], SNAPSHOT_FIELDS <= set(snapshot)
                  and snapshot["schemaVersion"] == 2 and snapshot["source"] in {"default", "custom", "inherited"})
            check("approved_parameter_values_unchanged_" + new_member["target"],
                  all(snapshot.get(k) == old_member["parameterSnapshot"].get(k) for k in VALUE_FIELDS))
        other = lambda rows: [a for a in rows if a["projectModelId"] not in EXPECTED]
        check("other_assignments_unchanged", other(assignments) == other(after_assignments))
        check("mobile_catalog_contains_available_test01", any(
            s["sceneId"] == SCENE and s["revision"] == 3 and s["available"] for s in catalog["scenes"]))
        (EVIDENCE / "after.json").write_text(json.dumps(
            {"scene": after, "assignments": after_assignments, "catalog": catalog},
            ensure_ascii=False, indent=2), encoding="utf-8")
        result["outcome"] = "saved_and_reapproved"
    except Exception as exc:
        result["outcome"] = "stopped_inspect_before_retry"
        result["error"] = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        raise
    finally:
        if logged_in:
            try:
                request("POST", "/aiyoloapi/auth/logout")
                result["created_session_revoked"] = True
            except Exception:
                result["created_session_revoked"] = False
        result["http"] = trace
        (EVIDENCE / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
