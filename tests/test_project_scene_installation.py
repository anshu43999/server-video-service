import hashlib
import unittest

import app.main as main
from test_project_scenes import SceneApiTests


class SceneInstallationApiTests(SceneApiTests):
    def _approve(self, revision=1):
        response = self.client.post(self.scenes + "/safety/approval", headers=self.owner, json={
            "approved": True, "expectedRevision": revision, "reason": "installation review"})
        self.assertEqual(200, response.status_code, response.text)

    def test_installation_prepare_is_account_scoped_and_not_runtime_authorization(self):
        self.assertEqual(201, self.create().status_code)
        self._approve()
        installation = self.client.get(self.scenes + "/safety/installation", headers=self.user,
                                        params={"target": "pc"})
        self.assertEqual(200, installation.status_code, installation.text)
        self.assertEqual("ready", installation.json()["status"])
        prepared = self.client.post(self.scenes + "/safety/installation/prepare", headers=self.user, json={
            "expectedRevision": 2, "target": "pc"})
        self.assertEqual(200, prepared.status_code, prepared.text)
        payload = prepared.json()
        self.assertTrue(payload["installationAuthorized"])
        self.assertFalse(payload["runtimeAuthorization"])
        self.assertIsNone(payload["runtimeGrant"])
        self.assertEqual(payload["requiredMemberIds"], payload["readyMemberIds"])
        artifact = payload["members"][0]["artifacts"][0]
        self.assertEqual(64, len(artifact["sha256"]))
        self.assertTrue(artifact["hashValid"])

    def test_single_plan_resolution_binds_member_artifact_and_parameter_revision(self):
        created = self.create()
        self.assertEqual(201, created.status_code, created.text)
        member_id = created.json()["models"][0]["memberId"]
        plans = self.client.put(self.scenes + "/safety/plans", headers=self.owner, json={
            "expectedRevision": 1,
            "plans": [{"planId": "photo", "name": "照片", "inputTypes": ["image"],
                        "memberIds": [member_id], "execution": "single", "enabled": True}]})
        self.assertEqual(200, plans.status_code, plans.text)
        self._approve(2)
        resolved = self.client.post(self.scenes + "/safety/plans/photo/resolve", headers=self.user, json={
            "planId": "photo", "expectedRevision": 3, "target": "pc", "inputType": "image",
            "clientContractVersion": 2})
        self.assertEqual(200, resolved.status_code, resolved.text)
        payload = resolved.json()
        self.assertEqual(("photo", member_id, "helmet", "1.0.0"),
                         (payload["planId"], payload["memberId"], payload["modelId"], payload["modelVersion"]))
        self.assertEqual(payload["members"][0]["artifactSha256"], payload["artifactSha256"])
        self.assertEqual(payload["members"][0]["parameterRevision"], payload["parameterRevision"])
        self.assertFalse(payload["runtimeAuthorization"])

    def test_legacy_client_contract_cannot_resolve_suite_plan(self):
        created = self.create()
        self.assertEqual(201, created.status_code, created.text)
        member_id = created.json()["models"][0]["memberId"]
        plans = self.client.put(self.scenes + "/safety/plans", headers=self.owner, json={
            "expectedRevision": 1,
            "plans": [{"planId": "photo", "name": "照片", "inputTypes": ["image"],
                       "memberIds": [member_id], "execution": "single", "enabled": True}]})
        self.assertEqual(200, plans.status_code, plans.text)
        self._approve(2)
        resolved = self.client.post(self.scenes + "/safety/plans/photo/resolve", headers=self.user, json={
            "planId": "photo", "expectedRevision": 3, "target": "pc", "inputType": "image",
            "clientContractVersion": 1})
        self.assertEqual(409, resolved.status_code, resolved.text)
        self.assertEqual("execution_mode_not_supported", resolved.json()["detail"]["code"])

    def test_multi_member_plan_remains_non_executable_but_can_prepare_members(self):
        created = self.create({**self.scene, "models": [self.member("helmet"), self.member("secret", 1)]})
        self.assertEqual(201, created.status_code, created.text)
        ids = [item["memberId"] for item in created.json()["models"]]
        plans = self.client.put(self.scenes + "/safety/plans", headers=self.owner, json={
            "expectedRevision": 1,
            "plans": [{"planId": "combined", "name": "联合", "inputTypes": ["image"],
                        "memberIds": ids, "execution": "sync", "enabled": True}]})
        self.assertEqual(200, plans.status_code, plans.text)
        self._approve(2)
        prepared = self.client.post(self.scenes + "/safety/installation/prepare", headers=self.user, json={
            "expectedRevision": 3, "target": "pc", "planId": "combined"})
        self.assertEqual(200, prepared.status_code, prepared.text)
        self.assertEqual(set(ids), set(prepared.json()["requiredMemberIds"]))
        resolved = self.client.post(self.scenes + "/safety/plans/combined/resolve", headers=self.user, json={
            "planId": "combined", "expectedRevision": 3, "target": "pc", "inputType": "image",
            "clientContractVersion": 2})
        self.assertEqual(409, resolved.status_code)
        self.assertEqual("execution_mode_not_supported", resolved.json()["detail"]["code"])
        resolved = self.client.post(self.scenes + "/safety/plans/combined/resolve", headers=self.user, json={
            "planId": "combined", "expectedRevision": 3, "target": "pc", "inputType": "image",
            "clientContractVersion": 3, "supportedExecutionModes": ["sync"]})
        self.assertEqual(200, resolved.status_code, resolved.text)
        payload = resolved.json()
        self.assertEqual(3, payload["resolveContractVersion"])
        self.assertEqual("sync", payload["execution"])
        self.assertEqual(set(ids), {item["memberId"] for item in payload["members"]})
        self.assertTrue(all(item["parameterSnapshot"]["projectId"] == self.project_id
                            for item in payload["members"]))
        self.assertTrue(all(len(item["artifactSha256"]) == 64 for item in payload["members"]))
        self.assertTrue(payload["resolutionOnly"])
        self.assertFalse(payload["runtimeAuthorization"])

    def test_multimember_resolve_requires_declared_mode_not_just_contract_version(self):
        created = self.create({**self.scene, "models": [self.member("helmet"), self.member("secret", 1)]})
        self.assertEqual(201, created.status_code, created.text)
        ids = [item["memberId"] for item in created.json()["models"]]
        plans = self.client.put(self.scenes + "/safety/plans", headers=self.owner, json={
            "expectedRevision": 1,
            "plans": [{"planId": "combined", "name": "联合", "inputTypes": ["image"],
                        "memberIds": ids, "execution": "async", "enabled": True}]})
        self.assertEqual(200, plans.status_code, plans.text)
        self._approve(2)
        resolved = self.client.post(self.scenes + "/safety/plans/combined/resolve", headers=self.user, json={
            "planId": "combined", "expectedRevision": 3, "target": "pc", "inputType": "image",
            "clientContractVersion": 3, "supportedExecutionModes": ["sync"]})
        self.assertEqual(409, resolved.status_code)
        self.assertEqual("execution_mode_not_supported", resolved.json()["detail"]["code"])

    def test_multimember_resolve_rejects_stale_approval_after_scene_revision_changes(self):
        created = self.create({**self.scene, "models": [self.member("helmet"), self.member("secret", 1)]})
        self.assertEqual(201, created.status_code, created.text)
        ids = [item["memberId"] for item in created.json()["models"]]
        plans = self.client.put(self.scenes + "/safety/plans", headers=self.owner, json={
            "expectedRevision": 1,
            "plans": [{"planId": "combined", "name": "联合", "inputTypes": ["image"],
                       "memberIds": ids, "execution": "sync", "enabled": True}]})
        self.assertEqual(200, plans.status_code, plans.text)
        self._approve(2)
        body = {"planId": "combined", "expectedRevision": 3, "target": "pc", "inputType": "image",
                "clientContractVersion": 3, "supportedExecutionModes": ["sync"]}
        allowed = self.client.post(self.scenes + "/safety/plans/combined/resolve", headers=self.user, json=body)
        self.assertEqual(200, allowed.status_code, allowed.text)

        edited = self.client.patch(self.scenes + "/safety", headers=self.owner,
                                   json={"expectedRevision": 3, "name": "修订后未重审"})
        self.assertEqual(200, edited.status_code, edited.text)
        self.assertFalse(edited.json()["approved"])
        stale = self.client.post(self.scenes + "/safety/plans/combined/resolve", headers=self.user,
                                 json=body)
        self.assertEqual(404, stale.status_code, stale.text)
        self.assertEqual("scene_not_found", stale.json()["detail"]["code"])

    def test_artifact_hash_tampering_blocks_installation_and_download(self):
        self.assertEqual(201, self.create().status_code)
        self._approve()
        registry = main.model_catalog._load()
        model = next(item for item in registry["models"] if item["modelId"] == "helmet" and item["version"] == "1.0.0")
        model["artifacts"][0]["sha256"] = hashlib.sha256(b"tampered").hexdigest()
        main.model_catalog._save(registry)
        prepared = self.client.post(self.scenes + "/safety/installation/prepare", headers=self.user, json={
            "expectedRevision": 2, "target": "pc"})
        self.assertEqual(200, prepared.status_code)
        self.assertEqual("blocked", prepared.json()["status"])
        url = self.scenes + "/safety/models/helmet/versions/1.0.0/artifacts/server/download"
        self.assertIn(self.client.get(url, headers=self.user).status_code, (404, 409))

    def test_scene_range_resume_rechecks_revision_and_approval(self):
        self.assertEqual(201, self.create().status_code)
        self._approve()
        url = self.scenes + '/safety/models/helmet/versions/1.0.0/artifacts/server/download?expectedRevision=2'
        full = self.client.get(url, headers=self.user)
        self.assertEqual(200, full.status_code, full.text)
        etag = full.headers['etag']
        self.assertFalse(etag.startswith('W/'))
        first = self.client.get(url, headers={**self.user, 'Range': 'bytes=0-1', 'If-Range': etag})
        rest = self.client.get(url, headers={**self.user, 'Range': 'bytes=2-', 'If-Range': etag})
        self.assertEqual((206, 206), (first.status_code, rest.status_code))
        self.assertEqual(full.content, first.content + rest.content)
        self.assertEqual(etag, rest.headers['etag'])
        self.assertEqual(416, self.client.get(url, headers={**self.user, 'Range': 'bytes=999999-'}).status_code)
        revoked = self.client.post(self.scenes + '/safety/approval', headers=self.owner, json={
            'approved': False, 'expectedRevision': 2, 'reason': 'revoke during resume'})
        self.assertEqual(200, revoked.status_code, revoked.text)
        denied = self.client.get(url, headers={**self.user, 'Range': 'bytes=2-', 'If-Range': etag})
        self.assertIn(denied.status_code, (403, 404, 409))
        self.assertNotIn('content-range', denied.headers)


if __name__ == "__main__":
    unittest.main()
