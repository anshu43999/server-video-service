import unittest
from unittest.mock import patch
from pathlib import Path

import app.main as main
from app.project_management import memory_audits_for_tests
import test_project_scenes as scene_tests


class SceneAuthorizationTests(scene_tests.SceneApiTests):
    # Run the base CRUD checks too with the authorization surface enabled.
    def approve(self, approved=True, revision=1, headers=None):
        return self.client.post(self.scenes + "/safety/approval",
            headers=headers or {**self.owner, "X-Request-Id": "scene-review"},
            json={"approved": approved, "expectedRevision": revision, "reason": "reviewed"})

    def user_scenes(self, params=None):
        return self.client.get(self.scenes, headers=self.user, params=params or {}).json()["scenes"]

    def test_approval_user_visibility_target_input_filters_and_edit_reapproval(self):
        self.assertEqual(201, self.create().status_code)
        self.assertEqual([], self.user_scenes())
        self.assertEqual(404, self.client.get(self.scenes + "/safety", headers=self.user).status_code)
        self.assertEqual(403, self.approve(headers=self.user).status_code)
        approved = self.approve()
        self.assertEqual(200, approved.status_code, approved.text)
        self.assertEqual((2, True), (approved.json()["revision"], approved.json()["approved"]))
        rows = self.user_scenes({"target": "pc", "inputType": "image"})
        self.assertEqual(1, len(rows))
        self.assertEqual("1.0.0", rows[0]["models"][0]["version"])
        self.assertTrue(rows[0]["models"][0]["targetReadiness"]["pc"])
        self.assertEqual([], self.user_scenes({"target": "mobile"}))
        audit = [a for a in memory_audits_for_tests()["project"] if a["action"] == "scene.approval"][0]
        self.assertEqual(approved.headers["x-request-id"], audit["requestId"])
        self.assertEqual((1, 2), (audit["previousRevision"], audit["newRevision"]))
        updated = self.client.patch(self.scenes + "/safety", headers=self.owner,
            json={"expectedRevision": 2, "inputTypes": ["video"]})
        self.assertFalse(updated.json()["approved"])
        self.assertEqual([], self.user_scenes())
        self.assertEqual(200, self.approve(revision=3).status_code)
        self.assertEqual([], self.user_scenes({"inputType": "image"}))
        self.assertEqual(1, len(self.user_scenes({"inputType": "video"})))

    def test_scene_download_rechecks_approval_target_hash_and_does_not_grant_old_runtime(self):
        self.assertEqual(201, self.create().status_code)
        url = self.scenes + "/safety/models/helmet/versions/1.0.0/artifacts/server/download"
        self.assertEqual(404, self.client.get(url, headers=self.owner).status_code)
        self.approve()
        directory = self.user_scenes()[0]
        self.assertEqual(url, directory["models"][0]["artifacts"][0]["url"])
        self.assertEqual(b"helmet-1.0.0", self.client.get(url, headers=self.user).content)
        for forbidden in (url.replace("artifacts/server", "artifacts/android"),
                          url.replace("versions/1.0.0", "versions/2.0.0"),
                          ):
            self.assertEqual(404, self.client.get(forbidden, headers=self.user).status_code)
        self.assertEqual(200, self.client.get(
            self.project_path + "/models/helmet/versions/1.0.0/artifacts/server/download", headers=self.user).status_code)
        self.assertEqual(200, self.approve(False, 2).status_code)
        self.assertEqual([], self.user_scenes())
        self.assertEqual(404, self.client.get(url, headers=self.user).status_code)
        self.assertEqual(200, self.approve(True, 3).status_code)
        registry = main.model_catalog._load()
        path = Path(self.temp.name) / registry["models"][0]["artifacts"][0]["path"]
        path.write_bytes(b"tampered")
        self.assertEqual([], self.user_scenes())
        self.assertEqual(404, self.client.get(url, headers=self.user).status_code)

    def test_multi_model_sync_async_resolution_explicitly_rejected_no_member_dropped(self):
        body = {**self.scene, "models": [self.member("helmet"), self.member("secret", 1, execution="async")]}
        self.assertEqual(201, self.create(body).status_code)
        self.approve()
        row = self.user_scenes()[0]
        self.assertEqual(2, len(row["models"]))
        self.assertFalse(row["executionSupported"])
        result = self.client.post(self.scenes + "/safety/resolve", headers=self.user,
            json={"expectedRevision": 2, "target": "pc", "inputType": "video"})
        self.assertEqual(409, result.status_code)
        self.assertEqual("execution_mode_not_supported", result.json()["detail"]["code"])
        self.assertEqual(5, len(main.project_model_assignments.list(self.project_id)))

    def test_single_resolution_stale_revision_and_model_revocation_rechecked(self):
        self.create()
        self.approve()
        body = {"expectedRevision": 2, "target": "pc", "inputType": "video"}
        path = self.scenes + "/safety/resolve"
        resolved = self.client.post(path, headers=self.user, json=body)
        self.assertEqual(200, resolved.status_code, resolved.text)
        self.assertTrue(resolved.json()["resolutionOnly"])
        self.assertEqual("revision_conflict", self.client.post(path, headers=self.user,
            json={**body, "expectedRevision": 1}).json()["detail"]["code"])
        registry = main.model_catalog._load()
        registry["models"][0]["status"] = "REVOKED"
        main.model_catalog._save(registry)
        self.assertEqual([], self.user_scenes())
        self.assertEqual(404, self.client.post(path, headers=self.user, json=body).status_code)
        self.assertEqual(200, self.approve(False, 2).status_code)

    def test_disabled_scene_stale_approval_and_membership_revocation(self):
        self.create({**self.scene, "enabled": False})
        self.assertEqual("scene_disabled", self.approve().json()["detail"]["code"])
        self.client.patch(self.scenes + "/safety", headers=self.owner, json={"expectedRevision": 1, "enabled": True})
        self.assertEqual("revision_conflict", self.approve().json()["detail"]["code"])
        self.approve(revision=2)
        self.assertEqual(1, len(self.user_scenes()))
        account_id = self.client.get("/aiyoloapi/auth/me", headers=self.user).json()["accountId"]
        members = self.client.get(self.project_path + "/members", headers=self.owner).json()["members"]
        member = next(m for m in members if m["accountId"] == account_id)
        removed = self.client.delete(self.project_path + "/members/" + account_id,
            headers=self.owner, params={"expectedRevision": member["revision"]})
        self.assertEqual(204, removed.status_code, removed.text)
        self.assertEqual(404, self.client.get(self.scenes, headers=self.user).status_code)
        self.assertEqual(404, self.client.post(self.scenes + "/safety/resolve", headers=self.user,
            json={"expectedRevision": 3, "target": "pc", "inputType": "video"}).status_code)

    def test_scene_becomes_unavailable_when_project_model_is_disabled(self):
        self.assertEqual(201, self.create().status_code)
        self.assertEqual(200, self.approve().status_code)
        self.assertEqual(1, len(self.user_scenes()))
        self.assertEqual(200, self._assign({**self.body, "enabled": False, "expectedRevision": 1}).status_code)
        self.assertEqual([], self.user_scenes())

    def test_single_async_member_is_not_executable_and_mixed_targets_never_drop_members(self):
        self.create({**self.scene, "models": [self.member("helmet", execution="sync")]})
        self.approve()
        result = self.client.post(self.scenes + "/safety/resolve", headers=self.user,
            json={"expectedRevision": 2, "target": "pc", "inputType": "video"})
        self.assertEqual("execution_mode_not_supported", result.json()["detail"]["code"])
        updated = self.client.put(self.scenes + "/safety/models", headers=self.owner, json={"expectedRevision": 2,
            "models": [self.member("helmet"), self.member("helmet", 1, target="mobile") ]})
        self.assertEqual(200, updated.status_code, updated.text)
        self.approve(revision=3)
        row = self.user_scenes({"target": "pc"})[0]
        self.assertEqual(1, len(row["models"]))
        self.assertTrue(row["executionSupported"])
        mobile = self.user_scenes({"target": "mobile"})[0]
        self.assertTrue(mobile["executionSupported"])
        for target in ("pc", "mobile"):
            resolved = self.client.post(self.scenes + "/safety/resolve", headers=self.user,
                json={"expectedRevision": 4, "target": target, "inputType": "image"})
            self.assertEqual(200, resolved.status_code, resolved.text)
            self.assertEqual(target, resolved.json()["model"]["target"])
        self.assertEqual("android", mobile["models"][0]["artifacts"][0]["artifactId"])
        mobile_url = mobile["models"][0]["artifacts"][0]["url"]
        self.assertEqual(200, self.client.get(mobile_url, headers=self.user).status_code)
        registry = main.model_catalog._load()
        (Path(self.temp.name) / registry["models"][0]["artifacts"][1]["path"]).unlink()
        self.assertEqual(1, len(self.user_scenes({"target": "pc"})))
        self.assertEqual([], self.user_scenes({"target": "mobile"}))
        resolved = self.client.post(self.scenes + "/safety/resolve", headers=self.user,
            json={"expectedRevision": 4, "target": "pc", "inputType": "image"})
        self.assertEqual(200, resolved.status_code, resolved.text)


if __name__ == "__main__":
    unittest.main()
