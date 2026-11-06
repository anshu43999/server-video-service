import copy
import unittest
from unittest.mock import patch

import app.main as main_module
from app.alert_advice_knowledge import AlertAdviceKnowledgeStore, helmet_mock_seed
from app.project_management import memory_audits_for_tests
from project_api_support import ProjectApiSupport


class AlertAdviceApiTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        self.start_project_api("advice-api")
        self.store = AlertAdviceKnowledgeStore()
        self._project_isolation.enter_context(
            patch.object(main_module, "alert_advice_knowledge_store", self.store)
        )
        self.base = f"{self.project_path}/alert-advice/knowledge-entries"

    @staticmethod
    def _body(entry_id="helmet-entry", alert_type="ppe_no_helmet", category="head"):
        seed = helmet_mock_seed()
        return {
            "entryId": entry_id,
            "alertTypeId": alert_type,
            "recognitionCategoryId": category,
            "status": "ACTIVE",
            **copy.deepcopy(seed["payload"]),
        }

    def _create_member(self, username="advice-member"):
        created = self.client.post(
            "/aiyoloapi/platform/accounts", headers=self.headers,
            json={"username": username, "password": f"{username}-password-1", "platformRole": "NORMAL_USER"},
        )
        self.assertEqual(201, created.status_code, created.text)
        account_id = created.json()["accountId"]
        member = self.client.post(
            f"{self.project_path}/members", headers=self.headers,
            json={"accountId": account_id, "projectRole": "PROJECT_USER"},
        )
        self.assertEqual(201, member.status_code, member.text)
        login = self.client.post(
            "/aiyoloapi/auth/login",
            json={"username": username, "password": f"{username}-password-1"},
        )
        self.assertEqual(200, login.status_code, login.text)
        return {"Authorization": f"Bearer {login.json()['accessToken']}"}

    def test_owner_crud_preview_revisions_conflicts_and_audit(self):
        created = self.client.post(
            self.base, headers={**self.headers, "Idempotency-Key": "knowledge-create"},
            json=self._body(),
        )
        self.assertEqual(201, created.status_code, created.text)
        self.assertEqual(
            {"alertTypeId": "PPE_NO_HELMET", "recognitionCategoryId": "HEAD"},
            created.json()["matchKey"],
        )

        preview = self.client.post(
            f"{self.base}/match-preview", headers=self.headers,
            json={"alertTypeId": " PPE_no_HELMET ", "recognitionCategoryId": " head "},
        )
        self.assertEqual(200, preview.status_code, preview.text)
        self.assertTrue(preview.json()["matched"])
        no_match = self.client.post(
            f"{self.base}/match-preview", headers=self.headers,
            json={"alertTypeId": "PPE_NO_HELMET", "recognitionCategoryId": "PERSON"},
        )
        self.assertFalse(no_match.json()["matched"])

        duplicate = self.client.post(self.base, headers=self.headers, json=self._body("duplicate"))
        self.assertEqual(409, duplicate.status_code, duplicate.text)
        self.assertEqual("ACTIVE_MATCH_KEY_CONFLICT", duplicate.json()["detail"]["code"])

        replacement = self._body()
        replacement.pop("entryId")
        replacement.pop("alertTypeId")
        replacement.pop("recognitionCategoryId")
        replacement.pop("status")
        replacement["expectedRevision"] = 1
        replacement["title"] = "更新后的安全帽处置资料"
        updated = self.client.put(
            f"{self.base}/helmet-entry", headers={**self.headers, "Idempotency-Key": "knowledge-update"},
            json=replacement,
        )
        self.assertEqual(200, updated.status_code, updated.text)
        self.assertEqual(2, updated.json()["revision"])
        stale = self.client.put(f"{self.base}/helmet-entry", headers=self.headers, json=replacement)
        self.assertEqual(409, stale.status_code, stale.text)
        self.assertEqual("REVISION_CONFLICT", stale.json()["detail"]["code"])

        disabled = self.client.post(
            f"{self.base}/helmet-entry/status",
            headers={**self.headers, "Idempotency-Key": "knowledge-disable"},
            json={"status": "INACTIVE", "expectedRevision": 2},
        )
        self.assertEqual(200, disabled.status_code, disabled.text)
        history = self.client.get(f"{self.base}/helmet-entry/revisions", headers=self.headers)
        self.assertEqual([1, 2, 3], [row["revision"] for row in history.json()["revisions"]])
        self.assertEqual(["CREATE", "UPDATE", "DEACTIVATE"], [row["action"] for row in history.json()["revisions"]])

        actions = [row["action"] for row in memory_audits_for_tests()["project"]]
        self.assertIn("alert_advice_knowledge.create", actions)
        self.assertIn("alert_advice_knowledge.update", actions)
        self.assertIn("alert_advice_knowledge.deactivate", actions)

    def test_project_user_has_read_preview_only(self):
        self.assertEqual(201, self.client.post(self.base, headers=self.headers, json=self._body()).status_code)
        member = self._create_member()
        self.assertEqual(200, self.client.get(self.base, headers=member).status_code)
        self.assertEqual(200, self.client.get(f"{self.base}/helmet-entry", headers=member).status_code)
        self.assertEqual(200, self.client.get(f"{self.base}/helmet-entry/revisions", headers=member).status_code)
        self.assertEqual(200, self.client.post(
            f"{self.base}/match-preview", headers=member,
            json={"alertTypeId": "PPE_NO_HELMET", "recognitionCategoryId": "HEAD"},
        ).status_code)
        denied = self.client.post(self.base, headers=member, json=self._body("denied", "FIRE", "SMOKE"))
        self.assertEqual(403, denied.status_code, denied.text)
        self.assertEqual("project.alert_knowledge.manage", denied.json()["detail"]["capability"])
        self.assertEqual(403, self.client.post(
            f"{self.base}/helmet-entry/status", headers=member,
            json={"status": "INACTIVE", "expectedRevision": 1},
        ).status_code)

    def test_validation_not_found_and_project_isolation(self):
        self.assertEqual(201, self.client.post(self.base, headers=self.headers, json=self._body()).status_code)
        self.assertEqual(404, self.client.get(f"{self.base}/missing", headers=self.headers).status_code)
        invalid = self._body("media-entry", "FIRE", "SMOKE")
        invalid["imagePath"] = "C:\\secret\\alert.jpg"
        rejected = self.client.post(self.base, headers=self.headers, json=invalid)
        self.assertEqual(422, rejected.status_code, rejected.text)

        other = self.client.post(
            "/aiyoloapi/platform/accounts", headers=self.headers,
            json={"username": "other-owner", "password": "other-owner-password-1", "platformRole": "NORMAL_USER"},
        ).json()
        other_project = self.client.post(
            "/aiyoloapi/projects", headers=self.headers,
            json={"projectCode": "advice-other", "displayName": "Advice Other", "ownerAccountId": other["accountId"]},
        ).json()
        other_login = self.client.post(
            "/aiyoloapi/auth/login",
            json={"username": "other-owner", "password": "other-owner-password-1"},
        ).json()
        other_headers = {"Authorization": f"Bearer {other_login['accessToken']}"}
        other_base = f"/aiyoloapi/projects/{other_project['projectId']}/alert-advice/knowledge-entries"
        second = self.client.post(other_base, headers=other_headers, json=self._body())
        self.assertEqual(201, second.status_code, second.text)
        self.assertEqual(1, len(self.client.get(other_base, headers=other_headers).json()["entries"]))
        self.assertEqual(404, self.client.get(other_base, headers=self._create_member("isolated-member")).status_code)

        response_text = self.client.get(self.base, headers=self.headers).text.lower()
        for forbidden in ("c:\\\\", "access_token", "password", "secret"):
            self.assertNotIn(forbidden, response_text)


if __name__ == "__main__":
    unittest.main()
