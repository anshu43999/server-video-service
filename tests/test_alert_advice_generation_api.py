import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import app.main as main_module
from app.alert_advice_generation import AlertAdviceGenerationStore
from app.alert_advice_knowledge import AlertAdviceKnowledgeStore, helmet_mock_seed
from app.alert_advice_service import AlertAdviceService, MockAdviceGenerator, MockKnowledgeRetriever
from app.alerts.disposition import AlertDispositionStore
from app.database import Base, DatabaseManager, ProjectRecord
from app.project_auth import memory_platform_entry_audits
from app.project_management import memory_audits_for_tests
from project_api_support import ProjectApiSupport


class AlertAdviceGenerationApiTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        self.start_project_api("advice-generation")
        self.knowledge = AlertAdviceKnowledgeStore()
        self.knowledge.ensure_mock_seed(self.project_id)
        self.generations = AlertAdviceGenerationStore()
        self.events = AlertDispositionStore()
        self.events.register({
            "eventId": "event-helmet-1", "projectId": self.project_id,
            "alertTypeId": "PPE_NO_HELMET", "recognitionCategoryId": "HEAD",
            "ruleId": "PPE_NO_HELMET", "label": "HEAD",
            "evidence": {"snapshotDataUrl": "data:image/jpeg;base64,private"},
            "disposition": {"status": "OPEN", "actor": None, "actedAtUs": None},
        }, project_id=self.project_id)
        self._project_isolation.enter_context(patch.object(
            main_module, "alert_advice_knowledge_store", self.knowledge
        ))
        self._project_isolation.enter_context(patch.object(main_module, "alert_advice_generation_store", self.generations))
        self._project_isolation.enter_context(patch.object(main_module, "alert_disposition_store", self.events))
        self._project_isolation.enter_context(patch.object(
            main_module, "alert_advice_service",
            AlertAdviceService(MockKnowledgeRetriever(self.knowledge), MockAdviceGenerator()),
        ))
        self.base = f"{self.project_path}/alerts/event-helmet-1/advice-generations"

    def _create_project_user(self, username):
        created = self.client.post(
            "/aiyoloapi/platform/accounts", headers=self.headers,
            json={"username": username, "password": f"{username}-password-1", "platformRole": "NORMAL_USER"},
        )
        self.assertEqual(201, created.status_code, created.text)
        account_id = created.json()["accountId"]
        membership = self.client.post(
            f"{self.project_path}/members", headers=self.headers,
            json={"accountId": account_id, "projectRole": "PROJECT_USER"},
        )
        self.assertEqual(201, membership.status_code, membership.text)
        login = self.client.post(
            "/aiyoloapi/auth/login",
            json={"username": username, "password": f"{username}-password-1"},
        )
        self.assertEqual(200, login.status_code, login.text)
        return account_id, {"Authorization": f"Bearer {login.json()['accessToken']}"}

    def test_generate_replay_history_retry_and_disposition_independence(self):
        key = "11111111-1111-4111-8111-111111111111"
        created = self.client.post(self.base, headers={**self.headers, "Idempotency-Key": key}, json={})
        self.assertEqual(201, created.status_code, created.text)
        result = created.json()
        self.assertEqual("GENERATED", result["status"])
        self.assertNotIn("snapshotDataUrl", created.text)
        self.assertEqual("OPEN", self.events.get("event-helmet-1", self.project_id)["disposition"]["status"])

        replay = self.client.post(self.base, headers={**self.headers, "Idempotency-Key": key}, json={})
        self.assertEqual(200, replay.status_code, replay.text)
        self.assertEqual(result, replay.json())
        conflict = self.client.post(
            self.base, headers={**self.headers, "Idempotency-Key": key},
            json={"retryOfGenerationId": result["generationId"]},
        )
        self.assertEqual(409, conflict.status_code, conflict.text)

        payload = copy.deepcopy(helmet_mock_seed()["payload"])
        payload["title"] = "知识已修改但旧快照不应变化"
        self.knowledge.replace(self.project_id, "mock-ppe-no-helmet-head", payload, "owner", 1)
        detail = self.client.get(f"{self.base}/{result['generationId']}", headers=self.headers)
        self.assertEqual(result, detail.json())
        latest = self.client.get(f"{self.base}/latest", headers=self.headers)
        self.assertEqual(result["generationId"], latest.json()["generationId"])

        retry = self.client.post(
            self.base,
            headers={**self.headers, "Idempotency-Key": "22222222-2222-4222-8222-222222222222"},
            json={"retryOfGenerationId": result["generationId"]},
        )
        self.assertEqual(201, retry.status_code, retry.text)
        self.assertEqual(result["generationId"], retry.json()["retryOfGenerationId"])
        history = self.client.get(self.base, headers=self.headers)
        self.assertEqual(2, len(history.json()["generations"]))
        self.assertEqual("OPEN", self.events.get("event-helmet-1", self.project_id)["disposition"]["status"])
        advice_audits = [row for row in memory_audits_for_tests()["project"]
                         if row["action"] == "alert_advice_generation.create"]
        self.assertEqual(2, len(advice_audits))
        audit_text = str(advice_audits).lower()
        for secret in ("snapshotdataurl", "private", "access_token", "internalprompt", "api_key"):
            self.assertNotIn(secret, audit_text)

    def test_missing_event_invalid_key_and_cross_project_are_rejected(self):
        missing = self.client.post(
            f"{self.project_path}/alerts/missing/advice-generations",
            headers={**self.headers, "Idempotency-Key": str(uuid4())}, json={},
        )
        self.assertEqual(404, missing.status_code, missing.text)
        self.assertEqual("EVENT_NOT_FOUND", missing.json()["detail"]["code"])
        invalid = self.client.post(self.base, headers={**self.headers, "Idempotency-Key": "not-uuid"}, json={})
        self.assertEqual(422, invalid.status_code, invalid.text)
        no_header = self.client.post(self.base, headers=self.headers, json={})
        self.assertEqual(422, no_header.status_code, no_header.text)

        other = self.client.post(
            "/aiyoloapi/platform/accounts", headers=self.headers,
            json={"username": "generation-other", "password": "generation-other-password-1", "platformRole": "NORMAL_USER"},
        ).json()
        other_project = self.client.post(
            "/aiyoloapi/projects", headers=self.headers,
            json={"projectCode": "generation-other", "displayName": "Other", "ownerAccountId": other["accountId"]},
        ).json()
        login = self.client.post(
            "/aiyoloapi/auth/login",
            json={"username": "generation-other", "password": "generation-other-password-1"},
        ).json()
        forbidden = self.client.get(self.base, headers={"Authorization": f"Bearer {login['accessToken']}"})
        self.assertEqual(404, forbidden.status_code, forbidden.text)

    def test_lifecycle_keeps_read_only_history_but_blocks_generation_and_knowledge_changes(self):
        generated = self.client.post(
            self.base,
            headers={**self.headers, "Idempotency-Key": "44444444-4444-4444-8444-444444444444"},
            json={},
        )
        self.assertEqual(201, generated.status_code, generated.text)

        suspended = self.client.post(
            f"{self.project_path}/suspend", headers=self.headers, json={"expectedRevision": 1},
        )
        self.assertEqual(200, suspended.status_code, suspended.text)
        self.assertEqual(200, self.client.get(f"{self.base}/latest", headers=self.headers).status_code)
        self.assertEqual(200, self.client.get(self.base, headers=self.headers).status_code)
        knowledge_base = f"{self.project_path}/alert-advice/knowledge-entries"
        self.assertEqual(200, self.client.get(knowledge_base, headers=self.headers).status_code)
        denied_generate = self.client.post(
            self.base,
            headers={**self.headers, "Idempotency-Key": "55555555-5555-4555-8555-555555555555"},
            json={},
        )
        self.assertEqual(403, denied_generate.status_code, denied_generate.text)
        self.assertEqual("project.alert_advice.generate", denied_generate.json()["detail"]["capability"])
        denied_manage = self.client.post(
            f"{knowledge_base}/mock-ppe-no-helmet-head/status", headers=self.headers,
            json={"status": "INACTIVE", "expectedRevision": 1},
        )
        self.assertEqual(403, denied_manage.status_code, denied_manage.text)
        self.assertEqual("project.alert_knowledge.manage", denied_manage.json()["detail"]["capability"])

        archived = self.client.post(
            f"{self.project_path}/archive", headers=self.headers, json={"expectedRevision": 2},
        )
        self.assertEqual(200, archived.status_code, archived.text)
        self.assertEqual(200, self.client.get(f"{self.base}/latest", headers=self.headers).status_code)
        self.assertEqual(200, self.client.get(knowledge_base, headers=self.headers).status_code)
        self.assertEqual(403, self.client.post(
            self.base,
            headers={**self.headers, "Idempotency-Key": "66666666-6666-4666-8666-666666666666"},
            json={},
        ).status_code)

        platform_entries = [row for row in memory_platform_entry_audits()
                            if row["action"] == "project.platform_entry"
                            and row["projectId"] == self.project_id]
        self.assertGreaterEqual(len(platform_entries), 1)

    def test_membership_revocation_and_logout_take_effect_on_next_advice_request(self):
        account_id, member_headers = self._create_project_user("advice-revoked")
        generated = self.client.post(
            self.base,
            headers={**member_headers, "Idempotency-Key": "77777777-7777-4777-8777-777777777777"},
            json={},
        )
        self.assertEqual(201, generated.status_code, generated.text)
        revoked = self.client.patch(
            f"{self.project_path}/members/{account_id}", headers=self.headers,
            json={"enabled": False, "expectedRevision": 1},
        )
        self.assertEqual(200, revoked.status_code, revoked.text)
        self.assertEqual(404, self.client.get(f"{self.base}/latest", headers=member_headers).status_code)
        self.assertEqual(404, self.client.post(
            self.base,
            headers={**member_headers, "Idempotency-Key": "88888888-8888-4888-8888-888888888888"},
            json={},
        ).status_code)

        _, logout_headers = self._create_project_user("advice-logout")
        self.assertEqual(200, self.client.get(self.base, headers=logout_headers).status_code)
        self.assertEqual(200, self.client.post("/aiyoloapi/auth/logout", headers=logout_headers).status_code)
        self.assertEqual(401, self.client.get(self.base, headers=logout_headers).status_code)

    def test_same_event_and_idempotency_key_are_isolated_between_projects(self):
        first = self.client.post(
            self.base,
            headers={**self.headers, "Idempotency-Key": "99999999-9999-4999-8999-999999999999"},
            json={},
        )
        self.assertEqual(201, first.status_code, first.text)

        owner = self.client.post(
            "/aiyoloapi/platform/accounts", headers=self.headers,
            json={"username": "advice-second-owner", "password": "advice-second-owner-password-1",
                  "platformRole": "NORMAL_USER"},
        )
        self.assertEqual(201, owner.status_code, owner.text)
        second_project = self.client.post(
            "/aiyoloapi/projects", headers=self.headers,
            json={"projectCode": "advice-second", "displayName": "Advice Second",
                  "ownerAccountId": owner.json()["accountId"]},
        )
        self.assertEqual(201, second_project.status_code, second_project.text)
        second_project_id = second_project.json()["projectId"]
        second_login = self.client.post(
            "/aiyoloapi/auth/login",
            json={"username": "advice-second-owner", "password": "advice-second-owner-password-1"},
        )
        self.assertEqual(200, second_login.status_code, second_login.text)
        second_headers = {"Authorization": f"Bearer {second_login.json()['accessToken']}"}
        self.events.register({
            "eventId": "event-helmet-1", "projectId": second_project_id,
            "alertTypeId": "PPE_NO_HELMET", "recognitionCategoryId": "HEAD",
            "ruleId": "PPE_NO_HELMET", "label": "HEAD",
            "evidence": {"snapshotDataUrl": "data:image/jpeg;base64,other-private"},
            "disposition": {"status": "OPEN", "actor": None, "actedAtUs": None},
        }, project_id=second_project_id)
        self.knowledge.ensure_mock_seed(second_project_id)
        second_base = (f"/aiyoloapi/projects/{second_project_id}/alerts/"
                       "event-helmet-1/advice-generations")
        second = self.client.post(
            second_base,
            headers={**second_headers, "Idempotency-Key": "99999999-9999-4999-8999-999999999999"},
            json={},
        )
        self.assertEqual(201, second.status_code, second.text)
        self.assertNotEqual(first.json()["generationId"], second.json()["generationId"])
        self.assertEqual(1, len(self.client.get(self.base, headers=self.headers).json()["generations"]))
        self.assertEqual(1, len(self.client.get(second_base, headers=second_headers).json()["generations"]))
        self.assertEqual(404, self.client.get(
            f"{second_base}/{first.json()['generationId']}", headers=second_headers,
        ).status_code)
        self.assertEqual(404, self.client.get(
            f"{self.base}/{second.json()['generationId']}", headers=self.headers,
        ).status_code)
        combined = (first.text + second.text).lower()
        for forbidden in ("snapshotdataurl", "other-private", "data:image", "access_token", "api_key"):
            self.assertNotIn(forbidden, combined)


class AlertAdviceGenerationPersistenceTests(unittest.TestCase):
    def test_restart_restores_immutable_generation_snapshot(self):
        temporary_root = Path(__file__).resolve().parents[1] / ".test-db"
        temporary_root.mkdir(exist_ok=True)
        temporary = tempfile.NamedTemporaryFile(suffix=".db", dir=temporary_root, delete=False)
        temporary.close()
        database_path = Path(temporary.name)
        try:
            database = DatabaseManager(f"sqlite+pysqlite:///{database_path.as_posix()}")
            Base.metadata.create_all(database.engine)
            project_id = str(uuid4())
            event_id = "persistent-event"
            with database.session() as session:
                session.add(ProjectRecord(project_id=project_id, project_code="persistent-advice", display_name="Persistent"))
            events = AlertDispositionStore(database)
            events.register({
                "eventId": event_id, "projectId": project_id,
                "alertTypeId": "PPE_NO_HELMET", "recognitionCategoryId": "HEAD",
            }, project_id=project_id)
            knowledge = AlertAdviceKnowledgeStore(database)
            knowledge.ensure_mock_seed(project_id)
            result = AlertAdviceService(MockKnowledgeRetriever(knowledge), MockAdviceGenerator()).generate(
                project_id, events.get(event_id, project_id)
            )
            first = AlertAdviceGenerationStore(database)
            snapshot, created = first.create(
                project_id, event_id, "operator", "33333333-3333-4333-8333-333333333333", None, result
            )
            self.assertTrue(created)

            reopened = AlertAdviceGenerationStore(DatabaseManager(database.url))
            try:
                self.assertEqual(snapshot, reopened.get(project_id, event_id, snapshot["generationId"]))
                self.assertEqual(snapshot, reopened.latest(project_id, event_id))
            finally:
                reopened.database.close()
                database.close()
        finally:
            database_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
