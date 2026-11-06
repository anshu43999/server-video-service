import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app import auth
from app.auth import reset_memory_auth_for_tests
from app.config import settings
from app.database import (
    Base,
    PlatformAuditEventRecord,
    ProjectAuditEventRecord,
    database,
)
from app.project_auth import reset_memory_project_authorization_for_tests
from app.project_management import (
    create_project_management_router,
    memory_audits_for_tests,
    reset_memory_project_management_for_tests,
)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth.create_auth_router())
    app.include_router(create_project_management_router())
    return app


class ProjectManagementDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.old_url = database.url
        self.old_env = settings.deployment_env
        self.old_admin_token = settings.admin_token
        self.old_mobile_token = settings.mobile_token
        temporary = tempfile.NamedTemporaryFile(suffix=".db", dir=Path(__file__).parent, delete=False)
        temporary.close()
        self.path = Path(temporary.name)
        database.close()
        database.url = f"sqlite:///{self.path.as_posix()}"
        Base.metadata.create_all(database.engine)
        settings.deployment_env = "production"
        settings.admin_token = None
        settings.mobile_token = None
        self._reset_memory()
        self.client = TestClient(_app())
        setup = self.client.post(
            "/aiyoloapi/auth/setup",
            json={"username": "admin", "password": "admin-password-1"},
        )
        self.assertEqual(200, setup.status_code)
        self.admin = {"Authorization": f"Bearer {setup.json()['accessToken']}"}
        self.admin_id = self.client.get("/aiyoloapi/auth/me", headers=self.admin).json()["accountId"]

    def tearDown(self):
        self.client.close()
        database.close()
        database.url = self.old_url
        self.path.unlink(missing_ok=True)
        settings.deployment_env = self.old_env
        settings.admin_token = self.old_admin_token
        settings.mobile_token = self.old_mobile_token
        self._reset_memory()

    @staticmethod
    def _reset_memory():
        reset_memory_auth_for_tests()
        reset_memory_project_authorization_for_tests()
        reset_memory_project_management_for_tests()

    def _create_account(self, username: str, role: str = "NORMAL_USER") -> dict:
        response = self.client.post(
            "/aiyoloapi/platform/accounts",
            headers={**self.admin, "X-Request-Id": f"create-{username}"},
            json={"username": username, "password": f"{username}-password-1", "platformRole": role},
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def _login(self, username: str) -> dict:
        response = self.client.post(
            "/aiyoloapi/auth/login",
            json={"username": username, "password": f"{username}-password-1"},
        )
        self.assertEqual(200, response.status_code, response.text)
        return {"Authorization": f"Bearer {response.json()['accessToken']}"}

    def _create_project(self, owner_id: str, code: str = "project-alpha") -> dict:
        response = self.client.post(
            "/aiyoloapi/projects",
            headers={**self.admin, "X-Request-Id": f"create-{code}"},
            json={"projectCode": code, "displayName": "Alpha", "ownerAccountId": owner_id},
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def test_member_creation_supplies_timestamps_for_pre_release_migrated_schemas(self):
        owner = self._create_account("timestamp-owner")
        member = self._create_account("timestamp-user")
        project = self._create_project(owner["accountId"])
        inserts = []

        def capture(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("INSERT INTO PROJECT_MEMBERSHIPS"):
                inserts.append(statement.split("VALUES", 1)[0])

        event.listen(database.engine, "before_cursor_execute", capture)
        try:
            response = self.client.post(f"/aiyoloapi/projects/{project['projectId']}/members",
                headers=self.admin, json={"accountId": member["accountId"], "projectRole": "PROJECT_USER"})
            self.assertEqual(201, response.status_code)
            self.assertEqual(1, len(inserts))
            self.assertIn("created_at", inserts[0])
            self.assertIn("updated_at", inserts[0])
        finally:
            event.remove(database.engine, "before_cursor_execute", capture)

    def test_project_account_and_lifecycle_crud_use_revisions_and_audit(self):
        owner = self._create_account("owner")
        project = self._create_project(owner["accountId"])
        project_id = project["projectId"]

        duplicate = self.client.post(
            "/aiyoloapi/projects",
            headers=self.admin,
            json={"projectCode": "project-alpha", "displayName": "Other", "ownerAccountId": owner["accountId"]},
        )
        self.assertEqual(409, duplicate.status_code)
        self.assertEqual("project_code_exists", duplicate.json()["detail"]["code"])

        changed = self.client.patch(
            f"/aiyoloapi/projects/{project_id}",
            headers={**self.admin, "X-Request-Id": "rename-project"},
            json={"expectedRevision": 1, "displayName": "Alpha Updated"},
        )
        self.assertEqual(200, changed.status_code)
        self.assertEqual(2, changed.json()["revision"])

        stale = self.client.patch(
            f"/aiyoloapi/projects/{project_id}", headers={**self.admin, "X-Request-Id": "stale-project"},
            json={"expectedRevision": 1, "displayName": "Stale"},
        )
        self.assertEqual(409, stale.status_code)
        self.assertEqual("revision_conflict", stale.json()["detail"]["code"])

        suspended = self.client.post(
            f"/aiyoloapi/projects/{project_id}/suspend", headers=self.admin,
            json={"expectedRevision": 2},
        )
        self.assertEqual("SUSPENDED", suspended.json()["lifecycleState"])
        self.assertEqual(3, suspended.json()["revision"])
        suspended_capabilities = self.client.get("/aiyoloapi/auth/projects", headers=self.admin).json()["projects"][0]["capabilities"]
        self.assertNotIn("project.inspection.use", suspended_capabilities)
        self.assertNotIn("project.streams.manage", suspended_capabilities)
        self.assertIn("project.members.manage", suspended_capabilities)
        repeated = self.client.post(
            f"/aiyoloapi/projects/{project_id}/suspend", headers=self.admin,
            json={"expectedRevision": 2},
        )
        self.assertEqual(200, repeated.status_code)
        self.assertEqual(3, repeated.json()["revision"])

        archived = self.client.post(
            f"/aiyoloapi/projects/{project_id}/archive", headers=self.admin,
            json={"expectedRevision": 3},
        )
        self.assertEqual("ARCHIVED", archived.json()["lifecycleState"])
        restored = self.client.post(
            f"/aiyoloapi/projects/{project_id}/restore", headers=self.admin,
            json={"expectedRevision": 4},
        )
        self.assertEqual("ACTIVE", restored.json()["lifecycleState"])
        self.assertEqual(5, restored.json()["revision"])

        account_changed = self.client.patch(
            f"/aiyoloapi/platform/accounts/{owner['accountId']}", headers=self.admin,
            json={"expectedRevision": 1, "platformRole": "PLATFORM_ADMIN"},
        )
        self.assertEqual(200, account_changed.status_code)
        self.assertEqual(2, account_changed.json()["revision"])
        self.assertEqual("PLATFORM_ADMIN", account_changed.json()["platformRole"])

        with database.session() as session:
            platform_audits = session.query(PlatformAuditEventRecord).all()
            project_audits = session.query(ProjectAuditEventRecord).all()
        self.assertGreaterEqual(len(platform_audits), 2)
        self.assertGreaterEqual(len(project_audits), 5)
        self.assertTrue(any(item.request_id == "create-owner" for item in platform_audits))
        self.assertTrue(any(
            item.request_id == "stale-project" and item.outcome == "DENIED"
            and item.failure_code == "revision_conflict"
            for item in platform_audits
        ))
        self.assertTrue(any(item.request_id == "rename-project" for item in project_audits))
        audit_text = str([item.change_summary for item in platform_audits + project_audits])
        self.assertNotIn("password", audit_text.lower())
        self.assertNotIn("owner-password-1", audit_text)

    def test_member_authority_owner_transfer_last_owner_and_disabled_session(self):
        owner = self._create_account("owner")
        user = self._create_account("member")
        project = self._create_project(owner["accountId"])
        project_id = project["projectId"]
        owner_headers = self._login("owner")
        member_headers = self._login("member")

        added = self.client.post(
            f"/aiyoloapi/projects/{project_id}/members",
            headers={**owner_headers, "X-Request-Id": "owner-add-member"},
            json={"accountId": user["accountId"], "projectRole": "PROJECT_USER"},
        )
        self.assertEqual(201, added.status_code, added.text)
        self.assertEqual("PROJECT_USER", added.json()["projectRole"])
        repeated = self.client.post(
            f"/aiyoloapi/projects/{project_id}/members", headers=owner_headers,
            json={"accountId": user["accountId"], "projectRole": "PROJECT_USER"},
        )
        self.assertEqual(201, repeated.status_code)
        self.assertEqual(1, repeated.json()["revision"])

        escalation = self.client.patch(
            f"/aiyoloapi/projects/{project_id}/members/{user['accountId']}", headers=owner_headers,
            json={"expectedRevision": 1, "projectRole": "PROJECT_OWNER"},
        )
        self.assertEqual(403, escalation.status_code)
        self.assertEqual("project_role_escalation_forbidden", escalation.json()["detail"]["code"])
        self.assertEqual(
            403,
            self.client.delete(
                f"/aiyoloapi/projects/{project_id}/members/{owner['accountId']}",
                headers=owner_headers, params={"expectedRevision": 1},
            ).status_code,
        )
        last_owner = self.client.delete(
            f"/aiyoloapi/projects/{project_id}/members/{owner['accountId']}",
            headers={**self.admin, "X-Request-Id": "remove-last-owner"}, params={"expectedRevision": 1},
        )
        self.assertEqual(409, last_owner.status_code)
        self.assertEqual("last_project_owner", last_owner.json()["detail"]["code"])
        with database.session() as session:
            denial = session.query(ProjectAuditEventRecord).filter_by(
                request_id="remove-last-owner", action="membership.delete", outcome="DENIED"
            ).one()
        self.assertEqual("DENIED", denial.outcome)
        self.assertEqual("last_project_owner", denial.failure_code)

        transferred = self.client.post(
            f"/aiyoloapi/projects/{project_id}/transfer-owner",
            headers={**owner_headers, "X-Request-Id": "transfer-owner"},
            json={
                "fromAccountId": owner["accountId"], "toAccountId": user["accountId"],
                "expectedFromRevision": 1, "expectedToRevision": 1,
            },
        )
        self.assertEqual(200, transferred.status_code, transferred.text)
        self.assertEqual("PROJECT_USER", transferred.json()["from"]["projectRole"])
        self.assertEqual("PROJECT_OWNER", transferred.json()["to"]["projectRole"])
        self.assertEqual(403, self.client.get(f"/aiyoloapi/projects/{project_id}/members", headers=owner_headers).status_code)
        self.assertEqual(200, self.client.get(f"/aiyoloapi/projects/{project_id}/members", headers=member_headers).status_code)

        disabled = self.client.patch(
            f"/aiyoloapi/platform/accounts/{owner['accountId']}", headers=self.admin,
            json={"expectedRevision": 1, "enabled": False},
        )
        self.assertEqual(200, disabled.status_code, disabled.text)
        self.assertFalse(disabled.json()["enabled"])
        self.assertEqual(401, self.client.get("/aiyoloapi/auth/me", headers=owner_headers).status_code)

        refuse_disable_last_owner = self.client.patch(
            f"/aiyoloapi/platform/accounts/{user['accountId']}", headers=self.admin,
            json={"expectedRevision": 1, "enabled": False},
        )
        self.assertEqual(409, refuse_disable_last_owner.status_code)
        self.assertEqual("last_project_owner", refuse_disable_last_owner.json()["detail"]["code"])

    def test_accessible_projects_respect_membership_role_and_archive(self):
        owner = self._create_account("owner")
        user = self._create_account("member")
        project = self._create_project(owner["accountId"])
        project_id = project["projectId"]
        self.client.post(
            f"/aiyoloapi/projects/{project_id}/members", headers=self.admin,
            json={"accountId": user["accountId"], "projectRole": "PROJECT_USER"},
        )
        owner_headers = self._login("owner")
        member_headers = self._login("member")

        owner_projects = self.client.get("/aiyoloapi/auth/projects", headers=owner_headers).json()["projects"]
        user_projects = self.client.get("/aiyoloapi/auth/projects", headers=member_headers).json()["projects"]
        self.assertEqual("PROJECT_OWNER", owner_projects[0]["projectRole"])
        self.assertIn("project.members.manage", owner_projects[0]["capabilities"])
        self.assertEqual("PROJECT_USER", user_projects[0]["projectRole"])
        self.assertNotIn("project.members.manage", user_projects[0]["capabilities"])

        archived = self.client.post(
            f"/aiyoloapi/projects/{project_id}/archive", headers=self.admin,
            json={"expectedRevision": 1},
        )
        self.assertEqual(200, archived.status_code)
        self.assertEqual(1, len(self.client.get("/aiyoloapi/auth/projects", headers=owner_headers).json()["projects"]))
        self.assertEqual([], self.client.get("/aiyoloapi/auth/projects", headers=member_headers).json()["projects"])
        admin_projects = self.client.get("/aiyoloapi/auth/projects", headers=self.admin).json()["projects"]
        self.assertTrue(admin_projects[0]["platformEntry"])
        self.assertEqual({
            "project.read", "project.alerts.read", "project.audit.read",
            "project.alert_knowledge.read", "project.alert_advice.read",
            "project.alert_advice.history.read",
        }, set(admin_projects[0]["capabilities"]))
        entered = self.client.get(
            f"/aiyoloapi/projects/{project_id}",
            headers={**self.admin, "X-Request-Id": "platform-entry"},
        )
        self.assertEqual(200, entered.status_code)
        with database.session() as session:
            audit = session.query(ProjectAuditEventRecord).filter_by(request_id="platform-entry").one()
        self.assertEqual("project.platform_entry", audit.action)
        self.assertEqual("HTTP", audit.change_summary["transport"])

    def test_management_aliases_and_audit_scope_pagination(self):
        owner = self._create_account('owner')
        user = self._create_account('member')
        other = self._create_account('other')
        project = self._create_project(owner['accountId'])
        project_b = self._create_project(other['accountId'], 'project-beta')
        project_id = project['projectId']
        owner_headers = self._login('owner')
        user_headers = self._login('member')
        self.client.post(f'/aiyoloapi/projects/{project_id}/members', headers=self.admin,
                         json={'accountId': user['accountId']})
        for endpoint in ['/platform/projects', '/platform/accounts', '/platform/audit']:
            self.assertEqual(403, self.client.get('/aiyoloapi' + endpoint, headers=owner_headers).status_code)
        self.assertEqual(403, self.client.patch(f'/aiyoloapi/platform/projects/{project_id}',
                         headers=owner_headers, json={'expectedRevision': 1, 'displayName': 'forbidden'}).status_code)
        self.assertEqual(403, self.client.get(f'/aiyoloapi/projects/{project_id}/audit', headers=user_headers).status_code)
        self.assertEqual(404, self.client.get(f"/aiyoloapi/projects/{project_b['projectId']}/audit", headers=owner_headers).status_code)
        self.assertEqual(200, self.client.get('/aiyoloapi/platform/projects', headers=self.admin).status_code)
        changed = self.client.patch(f'/aiyoloapi/platform/projects/{project_id}', headers=self.admin,
                                   json={'expectedRevision': 1, 'displayName': 'Alias Updated'})
        self.assertEqual(200, changed.status_code, changed.text)
        self.assertEqual(2, changed.json()['revision'])
        cursor = None
        ids = []
        for _ in range(20):
            result = self.client.get(f'/aiyoloapi/projects/{project_id}/audit', headers=owner_headers,
                                     params={'limit': 1, **({'cursor': cursor} if cursor else {})})
            self.assertEqual(200, result.status_code, result.text)
            page = result.json()
            for event in page['events']:
                self.assertEqual(project_id, event['projectId'])
                self.assertNotIn('changeSummary', event)
                ids.append(event['auditId'])
            cursor = page['nextCursor']
            if not cursor:
                break
        else:
            self.fail('pagination failed to terminate')
        self.assertGreaterEqual(len(ids), 3)
        self.assertEqual(len(ids), len(set(ids)))
        platform = self.client.get('/aiyoloapi/platform/audit', headers=self.admin, params={'limit': 1}).json()
        self.assertTrue(platform['nextCursor'])
        self.assertNotIn('password', str(platform).lower())
        self.assertEqual(422, self.client.get(f'/aiyoloapi/projects/{project_id}/audit', headers=owner_headers,
                         params={'cursor': platform['nextCursor']}).status_code)
        for params in [{'cursor': '%%%invalid'}, {'limit': 101}, {'limit': 0}]:
            self.assertEqual(422, self.client.get('/aiyoloapi/platform/audit', headers=self.admin, params=params).status_code)
        self.client.post(f'/aiyoloapi/platform/projects/{project_id}/archive', headers=self.admin, json={'expectedRevision': 2})
        self.assertEqual(200, self.client.get(f'/aiyoloapi/projects/{project_id}/audit', headers=owner_headers).status_code)
        self.assertEqual(403, self.client.get(f'/aiyoloapi/projects/{project_id}/members', headers=owner_headers).status_code)

    def test_last_platform_admin_cannot_be_disabled_or_demoted(self):
        response = self.client.patch(
            f"/aiyoloapi/platform/accounts/{self.admin_id}", headers=self.admin,
            json={"expectedRevision": 1, "enabled": False},
        )
        self.assertEqual(409, response.status_code)
        self.assertEqual("last_platform_admin", response.json()["detail"]["code"])

    def test_concurrent_project_updates_allow_one_revision_winner(self):
        owner = self._create_account("owner")
        project = self._create_project(owner["accountId"])
        project_id = project["projectId"]

        def update(display_name: str):
            with TestClient(_app()) as client:
                return client.patch(
                    f"/aiyoloapi/projects/{project_id}",
                    headers={**self.admin, "X-Request-Id": f"concurrent-{display_name}"},
                    json={"expectedRevision": 1, "displayName": display_name},
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(update, ("Winner A", "Winner B")))
        self.assertEqual([200, 409], sorted(response.status_code for response in responses))
        current = self.client.get(f"/aiyoloapi/projects/{project_id}", headers=self.admin)
        self.assertEqual(2, current.json()["revision"])
        self.assertIn(current.json()["displayName"], {"Winner A", "Winner B"})


class ProjectManagementMemoryTests(unittest.TestCase):
    def setUp(self):
        self.old_url = database.url
        self.old_env = settings.deployment_env
        database.close()
        database.url = None
        settings.deployment_env = "production"
        reset_memory_auth_for_tests()
        reset_memory_project_authorization_for_tests()
        reset_memory_project_management_for_tests()
        self.client = TestClient(_app())
        setup = self.client.post(
            "/aiyoloapi/auth/setup",
            json={"username": "admin", "password": "admin-password-1"},
        ).json()
        self.admin = {"Authorization": f"Bearer {setup['accessToken']}"}

    def tearDown(self):
        self.client.close()
        database.close()
        database.url = self.old_url
        settings.deployment_env = self.old_env
        reset_memory_auth_for_tests()
        reset_memory_project_authorization_for_tests()
        reset_memory_project_management_for_tests()

    def test_memory_backend_supports_same_account_project_member_and_audit_flow(self):
        owner = self.client.post(
            "/aiyoloapi/platform/accounts", headers={**self.admin, "X-Request-Id": "memory-account"},
            json={"username": "owner", "password": "owner-password-1", "platformRole": "NORMAL_USER"},
        )
        self.assertEqual(201, owner.status_code)
        project = self.client.post(
            "/aiyoloapi/projects", headers={**self.admin, "X-Request-Id": "memory-project"},
            json={"projectCode": "memory-project", "displayName": "Memory", "ownerAccountId": owner.json()["accountId"]},
        )
        self.assertEqual(201, project.status_code)
        login = self.client.post(
            "/aiyoloapi/auth/login", json={"username": "owner", "password": "owner-password-1"},
        ).json()
        owner_headers = {"Authorization": f"Bearer {login['accessToken']}"}
        projects = self.client.get("/aiyoloapi/auth/projects", headers=owner_headers)
        self.assertEqual(200, projects.status_code)
        self.assertEqual("PROJECT_OWNER", projects.json()["projects"][0]["projectRole"])
        audits = memory_audits_for_tests()
        self.assertEqual("memory-account", audits["platform"][0]["requestId"])
        self.assertEqual("memory-project", audits["project"][0]["requestId"])
        project_id = project.json()['projectId']
        self.client.get(f'/aiyoloapi/projects/{project_id}', headers=self.admin)
        page = self.client.get(f'/aiyoloapi/projects/{project_id}/audit', headers=owner_headers, params={'limit': 1}).json()
        self.assertEqual('project.platform_entry', page['events'][0]['action'])
        self.assertTrue(page['nextCursor'])
        older = self.client.get(f'/aiyoloapi/projects/{project_id}/audit', headers=owner_headers, params={'cursor': page['nextCursor']}).json()
        self.assertEqual('project.create', older['events'][0]['action'])
        self.assertIsNone(older['nextCursor'])
        self.assertEqual(403, self.client.get('/aiyoloapi/platform/audit', headers=owner_headers).status_code)
        self.assertNotIn('changeSummary', self.client.get('/aiyoloapi/platform/audit', headers=self.admin).text)


if __name__ == "__main__":
    unittest.main()
