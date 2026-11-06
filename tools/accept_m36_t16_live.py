"""Exercise M36-T16 against a fresh, loopback-only service and disposable PostgreSQL DB."""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("M36_T16_BASE_URL", "http://127.0.0.1:18081")
DB_URL = os.environ["DATABASE_URL"]
PASSWORD = "temporary-test-password"
MODELS = {
    # The only explicitly authorized internal-test assets are the two uploaded versions.
    # helmet is version 2.0.0 in the registry; aliases below model capability slots,
    # not claims that the repository contains distinct PPE/fire models.
    "helmet": ("uploaded-06b4dd2f10544673ab723226f91c34a7", "2.0.0"),
    "ppe": ("uploaded-06b4dd2f10544673ab723226f91c34a7", "2.0.0"),
    "fire": ("uploaded-06b4dd2f10544673ab723226f91c34a7", "3.0.0"),
}


class Run:
    def __init__(self):
        self.client = httpx.Client(base_url=BASE, timeout=30)
        self.trace = []
        self.tokens = {}

    def call(self, role, method, path, *, body=None, expected=200):
        response = self.client.request(method, path,
            headers={"Authorization": "Bearer " + self.tokens[role]} if role in self.tokens else {}, json=body)
        self.trace.append({"role": role, "method": method, "path": path,
                           "status": response.status_code, "requestId": response.headers.get("x-request-id")})
        if response.status_code != expected:
            raise AssertionError(f"{role} {method} {path}: expected {expected}, got {response.status_code}: {response.text}")
        return response

    def create_account(self, role):
        account = self.call("admin", "POST", "/aiyoloapi/platform/accounts", expected=201,
                            body={"username": f"m36t16-{role}-{uuid4().hex[:8]}",
                                  "password": PASSWORD, "platformRole": "NORMAL_USER"}).json()
        return account["accountId"], account["username"]

    def create_project(self, code, owner_id):
        project = self.call("admin", "POST", "/aiyoloapi/projects", expected=201,
                            body={"projectCode": code, "displayName": code, "ownerAccountId": owner_id}).json()
        return project["projectId"], f"/aiyoloapi/projects/{project['projectId']}"

    def add_member(self, project_path, account_id, role):
        self.call("admin", "POST", project_path + "/members", expected=201,
                  body={"accountId": account_id, "projectRole": role})

    def login(self, key, username):
        self.tokens[key] = self.call(key, "POST", "/aiyoloapi/auth/login", expected=200,
                                     body={"username": username, "password": PASSWORD}).json()["accessToken"]

    @staticmethod
    def member(member_id, kind, position, input_types):
        model_id, version = MODELS[kind]
        return {"memberId": member_id, "modelId": model_id, "version": version,
                "position": position, "target": "mobile", "inputTypes": input_types,
                "execution": "single"}

    def create_scene(self, project_path, scene_id, members, inputs):
        return self.call("gly", "POST", project_path + "/scenes", expected=201, body={
            "sceneId": scene_id, "name": scene_id, "inputTypes": inputs, "enabled": True,
            "expectedRevision": 0, "models": members}).json()

    def put_plans(self, project_path, scene_id, revision, plans):
        return self.call("gly", "PUT", f"{project_path}/scenes/{scene_id}/plans", body={
            "expectedRevision": revision, "plans": plans}).json()

    def approve(self, project_path, scene_id, revision, approved=True):
        return self.call("gly", "POST", f"{project_path}/scenes/{scene_id}/approval", body={
            "approved": approved, "expectedRevision": revision, "reason": "M36-T16 isolated internal acceptance"}).json()

    def run(self):
        health = self.client.get("/healthz")
        assert health.status_code == 200 and health.json()["database"]["status"] == "ok", health.text
        status = self.client.get("/aiyoloapi/auth/status").json()
        if status["setupRequired"]:
            setup = self.call("admin", "POST", "/aiyoloapi/auth/setup", expected=200,
                              body={"username": "m36t16-admin", "password": PASSWORD})
            self.tokens["admin"] = setup.json()["accessToken"]
        else:
            self.login("admin", "m36t16-admin")
        admin_me = self.call("admin", "GET", "/aiyoloapi/auth/me").json()
        assert admin_me["platformRole"] == "PLATFORM_ADMIN", admin_me
        gly_id, gly_username = self.create_account("gly")
        ptcy_id, ptcy_username = self.create_account("ptcy")
        self.login("gly", gly_username)
        self.login("ptcy", ptcy_username)
        suffix = uuid4().hex[:10]
        projects = [self.create_project(f"m36t16-{suffix}-{n}", admin_me["accountId"]) for n in ("a", "b")]
        for project_id, project_path in projects:
            self.add_member(project_path, gly_id, "PROJECT_OWNER")
            self.add_member(project_path, ptcy_id, "PROJECT_USER")

        p1, p2 = projects[0][1], projects[1][1]
        mixed = self.create_scene(p1, "mixed", [
            self.member("helmet-image", "helmet", 0, ["image"]),
            self.member("ppe-image", "ppe", 1, ["image"]),
            self.member("ppe-video", "ppe", 2, ["video"]),
            self.member("fire-video", "fire", 3, ["video"]),
        ], ["image", "video"])
        assert len(mixed["models"]) == 4 and mixed["revision"] == 1
        plans = self.put_plans(p1, "mixed", 1, [
            {"planId": "photo", "name": "photo", "inputTypes": ["image"],
             "memberIds": ["helmet-image"], "execution": "single", "enabled": True},
            {"planId": "photo-ppe", "name": "photo-ppe", "inputTypes": ["image"],
             "memberIds": ["ppe-image"], "execution": "single", "enabled": True},
            {"planId": "camera", "name": "camera", "inputTypes": ["video"],
             "memberIds": ["ppe-video", "fire-video"], "execution": "async", "enabled": True},
            {"planId": "all-camera", "name": "all-camera", "inputTypes": ["video"],
             "memberIds": ["ppe-video", "fire-video"], "execution": "async", "enabled": True},
        ])
        assert plans["revision"] == 2
        approved = self.approve(p1, "mixed", 2)
        assert approved["approved"] and approved["revision"] == 3
        visible = self.call("ptcy", "GET", p1 + "/scenes").json()["scenes"]
        assert len(visible) == 1 and len(visible[0]["models"]) == 4
        resolved = self.call("ptcy", "POST", p1 + "/scenes/mixed/plans/photo/resolve", body={
            "planId": "photo", "expectedRevision": 3, "target": "mobile", "inputType": "image",
            "clientContractVersion": 2}).json()
        assert resolved["memberId"] == "helmet-image" and resolved["planId"] == "photo"
        assert resolved["resolutionOnly"] is True and resolved["runtimeAuthorization"] is False
        ppe_resolution = self.call("ptcy", "POST", p1 + "/scenes/mixed/plans/photo-ppe/resolve", body={
            "planId": "photo-ppe", "expectedRevision": 3, "target": "mobile", "inputType": "image",
            "clientContractVersion": 2}).json()
        assert ppe_resolution["memberId"] == "ppe-image"
        assert ppe_resolution["modelId"] == MODELS["ppe"][0]
        old = self.call("ptcy", "POST", p1 + "/scenes/mixed/plans/photo/resolve", expected=409, body={
            "planId": "photo", "expectedRevision": 3, "target": "mobile", "inputType": "image",
            "clientContractVersion": 1})
        assert old.json()["detail"]["code"] == "execution_mode_not_supported"
        prepared = self.call("ptcy", "POST", p1 + "/scenes/mixed/installation/prepare", body={
            "expectedRevision": 3, "target": "mobile", "planId": "photo"}).json()
        assert prepared["installationAuthorized"] and prepared["runtimeAuthorization"] is False
        download = visible[0]["models"][0]["artifacts"][0]["url"]
        assert self.call("ptcy", "GET", download).content
        self.call("ptcy", "POST", p1 + "/scenes/mixed/plans/camera/resolve", expected=409, body={
            "planId": "camera", "expectedRevision": 3, "target": "mobile", "inputType": "video",
            "clientContractVersion": 2})

        photo = self.create_scene(p2, "photo-only", [
            self.member("helmet-photo", "helmet", 0, ["image"]),
            self.member("ppe-photo", "ppe", 1, ["image"]),
        ], ["image"])
        self.put_plans(p2, "photo-only", photo["revision"], [{"planId": "photo", "name": "photo",
            "inputTypes": ["image"], "memberIds": ["helmet-photo"], "execution": "single", "enabled": True}])
        self.approve(p2, "photo-only", 2)
        camera = self.create_scene(p2, "camera-only", [
            self.member("ppe-camera", "ppe", 0, ["video"]),
            self.member("fire-camera", "fire", 1, ["video"]),
        ], ["video"])
        self.put_plans(p2, "camera-only", camera["revision"], [{"planId": "camera", "name": "camera",
            "inputTypes": ["video"], "memberIds": ["ppe-camera"], "execution": "single", "enabled": True}])
        self.approve(p2, "camera-only", 2)
        assert {x["sceneId"] for x in self.call("ptcy", "GET", p2 + "/scenes").json()["scenes"]} == {
            "photo-only", "camera-only"}

        # Same expected revision is a compare-and-swap: one writer wins, the other conflicts.
        def edit(name):
            return self.client.patch(p1 + "/scenes/mixed", headers={"Authorization": "Bearer " + self.tokens["gly"]},
                                     json={"expectedRevision": 3, "name": name})
        with ThreadPoolExecutor(max_workers=2) as pool:
            edits = list(pool.map(edit, ("concurrent-a", "concurrent-b")))
        assert sorted(r.status_code for r in edits) == [200, 409], [r.text for r in edits]
        self.call("gly", "POST", p1 + "/scenes/mixed/approval", body={
            "approved": True, "expectedRevision": 4, "reason": "reapprove after CAS edit"})
        self.call("gly", "POST", p1 + "/scenes/mixed/approval", body={
            "approved": False, "expectedRevision": 5, "reason": "revoke in isolated test"})
        assert self.call("ptcy", "GET", p1 + "/scenes").json()["scenes"] == []
        self.call("ptcy", "GET", download, expected=404)

        engine = create_engine(DB_URL)
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT scene_id, revision, approved FROM project_scenes WHERE project_id IN (:a,:b) ORDER BY project_id, scene_id"),
                                {"a": projects[0][0], "b": projects[1][0]}).mappings().all()
            plans_db = conn.execute(text("SELECT count(*) FROM project_scene_plans WHERE project_id IN (:a,:b)"),
                                    {"a": projects[0][0], "b": projects[1][0]}).scalar_one()
            audit_count = conn.execute(text("SELECT count(*) FROM project_audit_events WHERE project_id IN (:a,:b)"),
                                       {"a": projects[0][0], "b": projects[1][0]}).scalar_one()
        engine.dispose()
        assert len(rows) == 3 and plans_db == 6 and audit_count >= 8, (rows, plans_db, audit_count)
        releases = {}
        for alias, (model_id, version) in MODELS.items():
            release = self.call("admin", "GET", f"/aiyoloapi/models/{model_id}/versions/{version}").json()
            releases[alias] = {key: release.get(key) for key in
                ("modelId", "version", "status", "releaseEligible", "licenseStatus", "license", "artifacts")}
        return {"startedAt": datetime.now(timezone.utc).isoformat(), "baseUrl": BASE,
                "database": "disposable PostgreSQL; full Alembic head", "projects": [p[0] for p in projects],
                "contract": {"suiteContractVersion": 2, "planResolutionClientContractMinimum": 2,
                             "legacyResolutionVersion": 1, "legacyResolutionStatus": 409,
                             "legacyResolutionCode": "execution_mode_not_supported",
                             "resolutionOnly": True, "runtimeAuthorization": False,
                             "planResolvePath": "/aiyoloapi/projects/{project_id}/scenes/{scene_id}/plans/{plan_id}/resolve",
                             "installationPreparePath": "/aiyoloapi/projects/{project_id}/scenes/{scene_id}/installation/prepare"},
                "models": releases,
                "sampleCoverage": {"apiArtifactDownload": "verified for published internal-test-only artifacts",
                                   "representativeBusinessImages": "not used; no dataset declared for these uploaded versions",
                                   "cameraVideo": "not used; task validates metadata/authorization, not inference"},
                "singlePlanResolutionExample": resolved,
                "reusedModelResolutionExample": ppe_resolution,
                "scenes": [dict(row) for row in rows], "planRows": plans_db, "auditRows": audit_count,
                "caseCount": len(self.trace), "trace": self.trace}


if __name__ == "__main__":
    run = Run()
    try:
        result = run.run()
        out = ROOT / "harness/evidence/M36/M36-T16-live-postgres-http.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items() if k != "trace"}, ensure_ascii=False, indent=2))
    finally:
        for role in list(run.tokens):
            try:
                run.call(role, "POST", "/aiyoloapi/auth/logout")
            except Exception:
                pass
        run.client.close()
