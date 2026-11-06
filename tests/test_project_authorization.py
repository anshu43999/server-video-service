import tempfile
import unittest
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app import auth
from app.auth import reset_memory_auth_for_tests, update_memory_account_for_tests
from app.config import settings
from app.database import (
    AccountRecord,
    Base,
    ProjectMembershipRecord,
    ProjectRecord,
    database,
)
from app.project_auth import (
    PLATFORM_ACCOUNTS_MANAGE,
    PROJECT_ALERTS_DISPOSE,
    PROJECT_ALERTS_READ,
    PROJECT_ALERT_ADVICE_GENERATE,
    PROJECT_ALERT_ADVICE_HISTORY_READ,
    PROJECT_ALERT_ADVICE_READ,
    PROJECT_ALERT_KNOWLEDGE_MANAGE,
    PROJECT_ALERT_KNOWLEDGE_READ,
    PROJECT_ARCHIVED,
    PROJECT_AUDIT_READ,
    PROJECT_EXPORTS_CREATE,
    PROJECT_INSPECTION_USE,
    PROJECT_MEMBERS_MANAGE,
    PROJECT_MODELS_ASSIGN,
    PROJECT_OWNER,
    PROJECT_OWNER_CAPABILITIES,
    PROJECT_READ,
    PROJECT_RULES_MANAGE,
    PROJECT_SETTINGS_MANAGE,
    PROJECT_SERVICE_PRINCIPALS_MANAGE,
    PROJECT_STREAMS_MANAGE,
    PROJECT_STREAMS_VIEW,
    PROJECT_SUSPENDED,
    PROJECT_USER,
    PROJECT_USER_CAPABILITIES,
    require_platform_capability,
    require_project_capability,
    reset_memory_project_authorization_for_tests,
    resolve_websocket_project_context,
    set_memory_membership_for_tests,
    set_memory_project_for_tests,
)


def create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth.create_auth_router())

    @app.get("/platform/accounts")
    async def platform_accounts(
        principal=Depends(require_platform_capability(PLATFORM_ACCOUNTS_MANAGE)),
    ):
        return {"accountId": principal.account_id, "platformRole": principal.platform_role}

    @app.get("/legacy/admin")
    async def legacy_admin(principal=Depends(auth.require_admin)):
        return {"legacy": principal.legacy}

    @app.get("/projects/{project_id}/read")
    async def project_read(context=Depends(require_project_capability(PROJECT_READ))):
        return _context_payload(context)

    @app.post("/projects/{project_id}/streams")
    async def project_streams(context=Depends(require_project_capability(PROJECT_STREAMS_MANAGE))):
        return _context_payload(context)

    @app.post("/projects/{project_id}/rules")
    async def project_rules(context=Depends(require_project_capability(PROJECT_RULES_MANAGE))):
        return _context_payload(context)

    @app.post("/projects/{project_id}/alerts/dispose")
    async def dispose_alert(context=Depends(require_project_capability(PROJECT_ALERTS_DISPOSE))):
        return _context_payload(context)

    @app.get("/compat/project")
    async def compatibility_project(context=Depends(require_project_capability(PROJECT_READ))):
        return _context_payload(context)

    return app


def _context_payload(context) -> dict:
    return {
        "accountId": context.principal.account_id,
        "projectId": context.project_id,
        "projectCode": context.project_code,
        "projectRole": context.project_role,
        "membershipRevision": context.membership_revision,
        "projectRevision": context.project_revision,
        "platformEntry": context.platform_entry,
    }


class _WebSocketLike:
    def __init__(self, token: str, project_id: str):
        self.headers = Headers({"authorization": f"Bearer {token}"})
        self.cookies = {}
        self.path_params = {"project_id": project_id}


class DatabaseProjectAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.old_database_url = database.url
        self.old_deployment_env = settings.deployment_env
        self.old_admin_token = settings.admin_token
        self.old_mobile_token = settings.mobile_token
        temporary_database = tempfile.NamedTemporaryFile(suffix=".db", dir=Path(__file__).parent, delete=False)
        temporary_database.close()
        self.database_path = Path(temporary_database.name)
        database.close()
        database.url = f"sqlite:///{self.database_path.as_posix()}"
        Base.metadata.create_all(database.engine)
        settings.deployment_env = "production"
        settings.admin_token = "static-admin"
        settings.mobile_token = "static-mobile"
        reset_memory_auth_for_tests()
        reset_memory_project_authorization_for_tests()
        self.client = TestClient(create_test_app())

    def tearDown(self):
        self.client.close()
        database.close()
        database.url = self.old_database_url
        self.database_path.unlink(missing_ok=True)
        settings.deployment_env = self.old_deployment_env
        settings.admin_token = self.old_admin_token
        settings.mobile_token = self.old_mobile_token
        reset_memory_auth_for_tests()
        reset_memory_project_authorization_for_tests()

    def _setup_admin(self) -> tuple[dict, dict]:
        response = self.client.post(
            "/aiyoloapi/auth/setup",
            json={"username": "admin", "password": "correct-horse-1"},
        )
        self.assertEqual(200, response.status_code)
        return response.json(), {"Authorization": f"Bearer {response.json()['accessToken']}"}

    def _create_user(self, admin_headers: dict, username: str = "operator") -> tuple[dict, dict]:
        created = self.client.post(
            "/aiyoloapi/auth/users",
            headers=admin_headers,
            json={"username": username, "password": "operator-pass-1", "role": "operator"},
        )
        self.assertEqual(200, created.status_code)
        login = self.client.post(
            "/aiyoloapi/auth/login",
            json={"username": username, "password": "operator-pass-1"},
        )
        self.assertEqual(200, login.status_code)
        return created.json(), {"Authorization": f"Bearer {login.json()['accessToken']}"}

    def _seed_project(self, project_id: str, code: str, *, lifecycle_state: str = "ACTIVE") -> None:
        with database.session() as session:
            session.add(
                ProjectRecord(
                    project_id=project_id,
                    project_code=code,
                    display_name=code,
                    lifecycle_state=lifecycle_state,
                    revision=1,
                )
            )

    def _set_membership(
        self,
        project_id: str,
        account_id: str,
        role: str,
        *,
        enabled: bool = True,
        revision: int = 1,
    ) -> None:
        with database.session() as session:
            membership = session.get(ProjectMembershipRecord, (project_id, account_id))
            if membership is None:
                session.add(
                    ProjectMembershipRecord(
                        project_id=project_id,
                        account_id=account_id,
                        project_role=role,
                        enabled=enabled,
                        revision=revision,
                    )
                )
            else:
                membership.project_role = role
                membership.enabled = enabled
                membership.revision = revision

    def test_principal_has_immutable_account_id_and_current_platform_role(self):
        setup, admin_headers = self._setup_admin()
        me = self.client.get("/aiyoloapi/auth/me", headers=admin_headers)
        self.assertEqual(200, me.status_code)
        self.assertEqual(setup["user"]["username"], me.json()["username"])
        self.assertEqual("PLATFORM_ADMIN", me.json()["platformRole"])
        self.assertEqual("m33-v1", me.json()["contractVersion"])
        self.assertTrue(me.json()["accountId"])

        with database.session() as session:
            account = session.scalar(
                session.query(AccountRecord).filter(AccountRecord.username == "admin").statement
            )
            account.platform_role = "NORMAL_USER"

        changed = self.client.get("/aiyoloapi/auth/me", headers=admin_headers)
        self.assertEqual(200, changed.status_code)
        self.assertEqual(me.json()["accountId"], changed.json()["accountId"])
        self.assertEqual("NORMAL_USER", changed.json()["platformRole"])
        self.assertEqual(403, self.client.get("/platform/accounts", headers=admin_headers).status_code)

    def test_disabling_account_invalidates_existing_session_immediately(self):
        _, headers = self._setup_admin()
        with database.session() as session:
            account = session.query(AccountRecord).filter_by(username="admin").one()
            account.enabled = False
        self.assertEqual(401, self.client.get("/aiyoloapi/auth/me", headers=headers).status_code)

    def test_missing_credentials_context_visibility_and_capability_have_distinct_errors(self):
        _, admin_headers = self._setup_admin()
        created, user_headers = self._create_user(admin_headers)
        self._seed_project("project-a", "alpha")
        self._seed_project("project-b", "beta")
        self._set_membership("project-a", created["accountId"], PROJECT_USER)

        with TestClient(create_test_app()) as anonymous:
            self.assertEqual(401, anonymous.get("/projects/project-a/read").status_code)
        missing_context = self.client.get("/compat/project", headers=user_headers)
        self.assertEqual(400, missing_context.status_code)
        self.assertEqual("project_context_required", missing_context.json()["detail"]["code"])
        self.assertEqual(404, self.client.get("/projects/missing/read", headers=user_headers).status_code)
        self.assertEqual(404, self.client.get("/projects/project-b/read", headers=user_headers).status_code)
        denied = self.client.post("/projects/project-a/streams", headers=user_headers)
        self.assertEqual(403, denied.status_code)
        self.assertEqual("project.streams.manage", denied.json()["detail"]["capability"])
        self.assertEqual(
            200,
            self.client.get("/compat/project", headers={**user_headers, "X-Project-Id": "project-a"}).status_code,
        )

    def test_membership_role_disable_and_multi_project_roles_are_live(self):
        _, admin_headers = self._setup_admin()
        created, user_headers = self._create_user(admin_headers)
        account_id = created["accountId"]
        self._seed_project("project-a", "alpha")
        self._seed_project("project-b", "beta")
        self._set_membership("project-a", account_id, PROJECT_OWNER, revision=1)
        self._set_membership("project-b", account_id, PROJECT_USER, revision=3)

        owner = self.client.post("/projects/project-a/rules", headers=user_headers)
        self.assertEqual(200, owner.status_code)
        self.assertEqual("PROJECT_OWNER", owner.json()["projectRole"])
        self.assertEqual(403, self.client.post("/projects/project-b/rules", headers=user_headers).status_code)
        self.assertEqual(200, self.client.post("/projects/project-b/alerts/dispose", headers=user_headers).status_code)

        self._set_membership("project-a", account_id, PROJECT_USER, revision=2)
        self.assertEqual(403, self.client.post("/projects/project-a/rules", headers=user_headers).status_code)
        self._set_membership("project-a", account_id, PROJECT_USER, enabled=False, revision=3)
        self.assertEqual(404, self.client.get("/projects/project-a/read", headers=user_headers).status_code)

    def test_project_lifecycle_changes_are_live(self):
        _, admin_headers = self._setup_admin()
        created, user_headers = self._create_user(admin_headers)
        self._seed_project("project-a", "alpha")
        self._set_membership("project-a", created["accountId"], PROJECT_OWNER)
        self.assertEqual(200, self.client.post("/projects/project-a/streams", headers=user_headers).status_code)

        with database.session() as session:
            project = session.get(ProjectRecord, "project-a")
            project.lifecycle_state = PROJECT_SUSPENDED
            project.revision = 2
        self.assertEqual(403, self.client.post("/projects/project-a/streams", headers=user_headers).status_code)
        self.assertEqual(200, self.client.get("/projects/project-a/read", headers=user_headers).status_code)

        with database.session() as session:
            project = session.get(ProjectRecord, "project-a")
            project.lifecycle_state = PROJECT_ARCHIVED
            project.revision = 3
        archived = self.client.get("/projects/project-a/read", headers=user_headers)
        self.assertEqual(200, archived.status_code)
        self.assertEqual(3, archived.json()["projectRevision"])

    def test_platform_admin_entry_is_explicit_and_not_a_membership(self):
        _, admin_headers = self._setup_admin()
        self._seed_project("project-a", "alpha")
        self.assertEqual(400, self.client.get("/compat/project", headers=admin_headers).status_code)
        entered = self.client.post("/projects/project-a/streams", headers=admin_headers)
        self.assertEqual(200, entered.status_code)
        self.assertTrue(entered.json()["platformEntry"])
        self.assertIsNone(entered.json()["projectRole"])

    def test_production_static_tokens_cannot_create_principals(self):
        self._seed_project("project-a", "alpha")
        self.assertEqual(
            401,
            self.client.get("/platform/accounts", headers={"X-Admin-Token": "static-admin"}).status_code,
        )

    def test_development_static_token_is_only_a_legacy_compatibility_identity(self):
        settings.deployment_env = "development"
        self._seed_project("project-a", "alpha")
        static_headers = {"X-Admin-Token": "static-admin"}
        legacy = self.client.get("/legacy/admin", headers=static_headers)
        self.assertEqual(200, legacy.status_code)
        self.assertTrue(legacy.json()["legacy"])
        self.assertEqual(401, self.client.get("/platform/accounts", headers=static_headers).status_code)
        self.assertEqual(401, self.client.get("/projects/project-a/read", headers=static_headers).status_code)
        self.assertEqual(
            401,
            self.client.get(
                "/projects/project-a/read",
                headers={"X-Video-Service-Token": "static-mobile"},
            ).status_code,
        )

    def test_websocket_resolver_reloads_membership(self):
        _, admin_headers = self._setup_admin()
        created, user_headers = self._create_user(admin_headers)
        self._seed_project("project-a", "alpha")
        self._set_membership("project-a", created["accountId"], PROJECT_OWNER)
        websocket = _WebSocketLike(user_headers["Authorization"].split(" ", 1)[1], "project-a")
        self.assertEqual(
            "project-a",
            resolve_websocket_project_context(websocket, PROJECT_STREAMS_MANAGE).project_id,
        )
        self._set_membership("project-a", created["accountId"], PROJECT_USER, revision=2)
        with self.assertRaisesRegex(Exception, "403"):
            resolve_websocket_project_context(websocket, PROJECT_STREAMS_MANAGE)


class MemoryProjectAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.old_database_url = database.url
        self.old_deployment_env = settings.deployment_env
        self.old_admin_token = settings.admin_token
        database.close()
        database.url = None
        settings.deployment_env = "production"
        settings.admin_token = "static-admin"
        reset_memory_auth_for_tests()
        reset_memory_project_authorization_for_tests()
        self.client = TestClient(create_test_app())

    def tearDown(self):
        self.client.close()
        database.close()
        database.url = self.old_database_url
        settings.deployment_env = self.old_deployment_env
        settings.admin_token = self.old_admin_token
        reset_memory_auth_for_tests()
        reset_memory_project_authorization_for_tests()

    def test_memory_backend_matches_live_principal_and_project_semantics(self):
        setup = self.client.post(
            "/aiyoloapi/auth/setup",
            json={"username": "admin", "password": "correct-horse-1"},
        ).json()
        headers = {"Authorization": f"Bearer {setup['accessToken']}"}
        me = self.client.get("/aiyoloapi/auth/me", headers=headers)
        self.assertEqual(200, me.status_code)
        account_id = me.json()["accountId"]
        self.assertEqual("PLATFORM_ADMIN", me.json()["platformRole"])

        set_memory_project_for_tests("project-a", "alpha")
        entered = self.client.get("/projects/project-a/read", headers=headers)
        self.assertEqual(200, entered.status_code)
        self.assertEqual(account_id, entered.json()["accountId"])
        self.assertTrue(entered.json()["platformEntry"])

        update_memory_account_for_tests(account_id, platform_role="NORMAL_USER")
        self.assertEqual(404, self.client.get("/projects/project-a/read", headers=headers).status_code)
        set_memory_membership_for_tests("project-a", account_id, PROJECT_USER, revision=2)
        member = self.client.get("/projects/project-a/read", headers=headers)
        self.assertEqual(200, member.status_code)
        self.assertEqual("PROJECT_USER", member.json()["projectRole"])
        self.assertEqual(2, member.json()["membershipRevision"])
        self.assertEqual(403, self.client.post("/projects/project-a/streams", headers=headers).status_code)

        set_memory_project_for_tests(
            "project-a",
            "alpha",
            lifecycle_state=PROJECT_ARCHIVED,
            revision=3,
        )
        self.assertEqual(404, self.client.get("/projects/project-a/read", headers=headers).status_code)
        set_memory_membership_for_tests("project-a", account_id, PROJECT_OWNER, revision=3)
        archived_owner = self.client.get("/projects/project-a/read", headers=headers)
        self.assertEqual(200, archived_owner.status_code)
        self.assertEqual(3, archived_owner.json()["projectRevision"])

        update_memory_account_for_tests(account_id, enabled=False)
        self.assertEqual(401, self.client.get("/aiyoloapi/auth/me", headers=headers).status_code)


class CapabilityMatrixTests(unittest.TestCase):
    def test_frozen_owner_and_user_capability_matrix(self):
        self.assertEqual(
            {
                PROJECT_READ,
                PROJECT_INSPECTION_USE,
                PROJECT_STREAMS_VIEW,
                PROJECT_ALERTS_READ,
                PROJECT_ALERTS_DISPOSE,
                PROJECT_ALERT_KNOWLEDGE_READ,
                PROJECT_ALERT_ADVICE_GENERATE,
                PROJECT_ALERT_ADVICE_READ,
                PROJECT_ALERT_ADVICE_HISTORY_READ,
            },
            set(PROJECT_USER_CAPABILITIES),
        )
        self.assertEqual(
            {
                *PROJECT_USER_CAPABILITIES,
                PROJECT_MEMBERS_MANAGE,
                PROJECT_STREAMS_MANAGE,
                PROJECT_RULES_MANAGE,
                PROJECT_MODELS_ASSIGN,
                "project.scenes.manage",
                "project.scenes.approve",
                PROJECT_SETTINGS_MANAGE,
                PROJECT_ALERT_KNOWLEDGE_MANAGE,
                PROJECT_EXPORTS_CREATE,
                PROJECT_AUDIT_READ,
                PROJECT_SERVICE_PRINCIPALS_MANAGE,
            },
            set(PROJECT_OWNER_CAPABILITIES),
        )


if __name__ == "__main__":
    unittest.main()
