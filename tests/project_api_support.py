from contextlib import ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.auth as auth_module
import app.main as main_module
from app.config import settings
from app.database import DatabaseManager
from app.project_auth import reset_memory_project_authorization_for_tests
from app.project_management import reset_memory_project_management_for_tests


class ProjectApiSupport:
    def start_project_api(self, code: str) -> None:
        self._project_isolation = ExitStack()
        # Register cleanup before any setup work so a failed setup cannot leak
        # patched auth/settings or a live TestClient into subsequent tests.
        add_cleanup = getattr(self, "addCleanup", None)
        if add_cleanup is not None:
            add_cleanup(self.stop_project_api)
        self._project_isolation.enter_context(
            patch("app.auth.database", DatabaseManager(None))
        )
        self._project_isolation.enter_context(
            patch.dict(auth_module._memory_accounts, {}, clear=True)
        )
        self._project_isolation.enter_context(
            patch.dict(auth_module._memory_sessions, {}, clear=True)
        )
        self._project_isolation.enter_context(
            patch.object(main_module.database, "verify_schema", return_value={"status": "ok"})
        )
        self._project_isolation.enter_context(
            patch.object(main_module.conversion_service, "start")
        )
        self._project_isolation.enter_context(
            patch.object(main_module.conversion_service, "close")
        )
        self._old_project_settings = (
            settings.deployment_env,
            settings.admin_token,
            settings.mobile_token,
        )
        settings.deployment_env = "production"
        settings.admin_token = None
        settings.mobile_token = None
        reset_memory_project_authorization_for_tests()
        reset_memory_project_management_for_tests()
        # TestClient closes its own partial context when startup fails. Do not
        # call __exit__ on a client that never finished __enter__.
        self.client = None
        client = TestClient(main_module.app)
        client.__enter__()
        self.client = client
        setup = self.client.post(
            "/aiyoloapi/auth/setup",
            json={"username": f"{code}-admin", "password": "temporary-test-password"},
        )
        if setup.status_code != 200:
            raise AssertionError(setup.text)
        self.headers = {"Authorization": f"Bearer {setup.json()['accessToken']}"}
        account_id = self.client.get(
            "/aiyoloapi/auth/me", headers=self.headers
        ).json()["accountId"]
        project = self.client.post(
            "/aiyoloapi/projects",
            headers=self.headers,
            json={
                "projectCode": code,
                "displayName": code.title(),
                "ownerAccountId": account_id,
            },
        )
        if project.status_code != 201:
            raise AssertionError(project.text)
        self.account_id = account_id
        self.project_id = project.json()["projectId"]
        self.project_path = f"/aiyoloapi/projects/{self.project_id}"

    def stop_project_api(self) -> None:
        client = getattr(self, "client", None)
        if client is not None:
            client.__exit__(None, None, None)
            self.client = None
        old_settings = getattr(self, "_old_project_settings", None)
        if old_settings is not None:
            (
                settings.deployment_env,
                settings.admin_token,
                settings.mobile_token,
            ) = old_settings
            self._old_project_settings = None
        reset_memory_project_authorization_for_tests()
        reset_memory_project_management_for_tests()
        stack = getattr(self, "_project_isolation", None)
        if stack is not None:
            stack.close()
            self._project_isolation = None
