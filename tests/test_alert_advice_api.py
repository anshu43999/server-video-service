from knowledge_support import helmet_mock_seed
import copy
import unittest
from unittest.mock import patch

import app.main as main_module
from app.alert_advice_knowledge import AlertAdviceKnowledgeStore
from app.project_management import memory_audits_for_tests
from app.system_alert_knowledge import SystemKnowledgeStore
from project_api_support import ProjectApiSupport


class AlertAdviceApiTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        self.start_project_api("advice-api")
        self.system = SystemKnowledgeStore()
        self.store = AlertAdviceKnowledgeStore(system=self.system)
        self._project_isolation.enter_context(patch.object(main_module, "alert_advice_knowledge_store", self.store))
        self.base = self.project_path + "/alert-advice/knowledge-entries"
        self.platform = "/aiyoloapi/platform/alert-advice"
        self.entry_id = "system:mock-ppe-no-helmet-head"

    @staticmethod
    def _body():
        return {"entryId": "new-system-entry", "alertTypeId": "CUSTOM", "recognitionCategoryId": "HEAD",
                "status": "ACTIVE", **copy.deepcopy(helmet_mock_seed()["payload"])}

    def _member(self, name, role="PROJECT_USER"):
        account = self.client.post("/aiyoloapi/platform/accounts", headers=self.headers,
            json={"username": name, "password": name + "-temporary-password", "platformRole": "NORMAL_USER"})
        self.assertEqual(201, account.status_code, account.text)
        member = self.client.post(self.project_path + "/members", headers=self.headers,
            json={"accountId": account.json()["accountId"], "projectRole": role})
        self.assertEqual(201, member.status_code, member.text)
        login = self.client.post("/aiyoloapi/auth/login", json={"username": name, "password": name + "-temporary-password"})
        self.assertEqual(200, login.status_code, login.text)
        return {"Authorization": "Bearer " + login.json()["accessToken"]}

    def test_all_project_roles_read_but_cannot_write_even_through_legacy_routes(self):
        roles = [self.headers, self._member("knowledge-member"), self._member("knowledge-owner", "PROJECT_OWNER")]
        original = self.system.catalog()
        before_audits = copy.deepcopy(memory_audits_for_tests())
        for headers in roles:
            listed = self.client.get(self.base, headers=headers)
            self.assertEqual(200, listed.status_code, listed.text)
            self.assertEqual(1, listed.json()["systemVersion"])
            self.assertTrue(all(e["origin"] == "SYSTEM" for e in listed.json()["entries"]))
            self.assertEqual(200, self.client.get(self.base + "/" + self.entry_id, headers=headers).status_code)
            for method, url in [("POST", self.base), ("PUT", self.base + "/" + self.entry_id),
                                ("POST", self.base + "/" + self.entry_id + "/status"),
                                ("POST", self.project_path + "/alert-advice/knowledge-overrides"),
                                ("POST", self.project_path + "/alert-advice/base/upgrade")]:
                response = self.client.request(method, url, headers=headers, json={})
                self.assertEqual(410, response.status_code, response.text)
                self.assertEqual("PROJECT_KNOWLEDGE_READ_ONLY", response.json()["detail"]["code"])
        self.assertEqual(original, self.system.catalog())
        self.assertFalse(hasattr(self.store, "local_list"))
        self.assertEqual(before_audits, memory_audits_for_tests())

    def test_platform_draft_crud_publish_cas_and_status_are_the_only_write_path(self):
        response = self.client.post(self.platform + "/knowledge-entries", headers=self.headers, json=self._body())
        self.assertEqual(201, response.status_code, response.text)
        body = self._body()
        replacement = {k: v for k, v in body.items() if k not in {"entryId", "alertTypeId", "recognitionCategoryId", "status"}}
        replacement.update({"title": "Unified system material", "expectedRevision": 1})
        url = self.platform + "/knowledge-entries/new-system-entry"
        self.assertEqual(200, self.client.put(url, headers=self.headers, json=replacement).status_code)
        stale = self.client.put(url, headers=self.headers, json=replacement)
        self.assertEqual(409, stale.status_code)
        key = {"alertTypeId": " custom ", "recognitionCategoryId": " head "}
        self.assertFalse(self.client.post(self.base + "/match-preview", headers=self.headers, json=key).json()["matched"])
        catalog = self.client.get(self.platform + "/knowledge-entries", headers=self.headers).json()
        published = self.client.post(self.platform + "/publish", headers=self.headers,
                                    json={"expectedRevision": catalog["revision"], "notes": "Global publication"})
        self.assertEqual(201, published.status_code, published.text)
        self.assertEqual(409, self.client.post(self.platform + "/publish", headers=self.headers,
            json={"expectedRevision": catalog["revision"], "notes": "Stale publication"}).status_code)
        match = self.client.post(self.base + "/match-preview", headers=self.headers, json=key).json()
        self.assertTrue(match["matched"])
        self.assertEqual(2, match["entry"]["systemVersion"])
        self.assertEqual(200, self.client.post(url + "/status", headers=self.headers,
                                             json={"status": "INACTIVE", "expectedRevision": 2}).status_code)
        self.assertTrue(self.client.post(self.base + "/match-preview", headers=self.headers, json=key).json()["matched"])
        self.system.publish(self.system.catalog()["revision"], "Disable globally", self.account_id)
        self.assertFalse(self.client.post(self.base + "/match-preview", headers=self.headers, json=key).json()["matched"])
        history = self.client.get(url + "/revisions", headers=self.headers).json()["revisions"]
        self.assertEqual(["CREATE", "UPDATE", "DEACTIVATE"], [row["action"] for row in history])
        actions = [row["action"] for row in memory_audits_for_tests()["platform"]
                   if row["action"].startswith("system_alert_knowledge.")]
        self.assertEqual(["system_alert_knowledge.create", "system_alert_knowledge.replace",
                          "system_alert_knowledge.publish", "system_alert_knowledge.set_status"], actions)

    def test_members_cannot_manage_system_and_unavailable_or_foreign_context_fails_closed(self):
        member = self._member("isolated-knowledge")
        self.assertEqual(403, self.client.get(self.platform + "/knowledge-entries", headers=member).status_code)
        self.assertEqual(403, self.client.post(self.platform + "/knowledge-entries", headers=member, json=self._body()).status_code)
        self.assertEqual(403, self.client.post(self.platform + "/publish", headers=member,
            json={"expectedRevision": 1, "notes": "Forbidden"}).status_code)
        self.client.cookies.clear()
        self.assertEqual(401, self.client.get(self.base).status_code)
        self.assertEqual(401, self.client.post(self.base, json={}).status_code)
        other = self.client.post("/aiyoloapi/projects", headers=self.headers,
            json={"projectCode": "knowledge-other", "displayName": "Other", "ownerAccountId": self.account_id}).json()
        path = "/aiyoloapi/projects/" + other["projectId"] + "/alert-advice/knowledge-entries"
        self.assertEqual(404, self.client.get(path, headers=member).status_code)
        self.assertEqual(404, self.client.post(path, headers=member, json={}).status_code)
        own = self.client.get(self.base, headers=self.headers).json()["entries"]
        other_rows = self.client.get(path, headers=self.headers).json()["entries"]
        self.assertEqual([e["title"] for e in own], [e["title"] for e in other_rows])
        self.assertTrue(all(e["projectId"] == other["projectId"] for e in other_rows))
        self.store.system = None
        self.assertEqual(503, self.client.get(self.base, headers=self.headers).status_code)

    def test_revoked_membership_and_logout_block_knowledge_reads_and_retired_writes(self):
        member = self._member("knowledge-revoked")
        account_id = self.client.get("/aiyoloapi/auth/me", headers=member).json()["accountId"]
        self.assertEqual(200, self.client.get(self.base, headers=member).status_code)
        revoked = self.client.patch(self.project_path + "/members/" + account_id, headers=self.headers,
                                   json={"enabled": False, "expectedRevision": 1})
        self.assertEqual(200, revoked.status_code, revoked.text)
        self.assertEqual(404, self.client.get(self.base, headers=member).status_code)
        self.assertEqual(404, self.client.post(self.base, headers=member, json={}).status_code)
        logged_out = self._member("knowledge-logout")
        self.assertEqual(200, self.client.post("/aiyoloapi/auth/logout", headers=logged_out).status_code)
        self.assertEqual(401, self.client.get(self.base, headers=logged_out).status_code)
        self.assertEqual(401, self.client.post(self.base, headers=logged_out, json={}).status_code)

    def test_validation_exact_preview_and_published_revision_do_not_expose_drafts(self):
        self.assertEqual(404, self.client.get(self.base + "/missing", headers=self.headers).status_code)
        self.assertEqual(422, self.client.get(self.base + "?alertTypeId=PPE_NO_HELMET", headers=self.headers).status_code)
        self.assertEqual(422, self.client.get(self.base + "?alertTypeId=%20&recognitionCategoryId=HEAD", headers=self.headers).status_code)
        invalid = self._body(); invalid["imagePath"] = "forbidden-media"
        self.assertEqual(422, self.client.post(self.platform + "/knowledge-entries", headers=self.headers, json=invalid).status_code)
        response = self.client.post(self.base + "/match-preview", headers=self.headers,
            json={"alertTypeId": "PPE_NO_HELMET", "recognitionCategoryId": "PERSON"})
        self.assertFalse(response.json()["matched"])
        history = self.client.get(self.base + "/" + self.entry_id + "/revisions", headers=self.headers).json()["revisions"]
        self.assertEqual("PUBLISHED", history[0]["action"])
        self.assertEqual(1, history[0]["systemVersion"])
        self.assertNotIn("baseRevision", history[0]["snapshot"])
        base = self.client.get(self.project_path + "/alert-advice/base", headers=self.headers).json()
        self.assertEqual("SYSTEM", base["mode"])
        self.assertEqual([], base["versions"])
