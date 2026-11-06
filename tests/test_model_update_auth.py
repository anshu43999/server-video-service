"""Actual password/session authentication backed by an isolated database."""
import os
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.auth as auth
from app.database import AccountRecord, ProjectMembershipRecord
from app.model_updates.api import create_router
from app.model_updates.service import ModelUpdateService
import test_model_updates as common


class UpdateAuthenticationTests(unittest.TestCase):
    def setUp(self):
        common.UpdateStoreTests.setUp(self)
        with self.db.session() as session:
            for account_id in ('account-one', 'account-two'):
                session.get(AccountRecord, account_id).password_hash = auth._hash_password('fixture-only-password')
            session.get(ProjectMembershipRecord, ('project-one', 'account-one')).project_role = 'PROJECT_OWNER'
        self.patch = patch('app.auth.database', self.db)
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.service = ModelUpdateService(self.db, None, None)
        del self.service.store.authority
        self.service.projection.one = lambda _: True
        app = FastAPI()
        app.include_router(auth.create_auth_router())
        app.include_router(create_router(lambda: self.service))
        self.client = TestClient(app, base_url='https://test.example')
        self.addCleanup(self.client.close)

    def login(self, username):
        result = self.client.post('/aiyoloapi/auth/login', json=dict(username=username, password='fixture-only-password'))
        self.assertEqual(200, result.status_code, result.text)
        return {'X-Video-Service-Token': result.json()['accessToken']}

    def test_real_login_account_switch_cannot_read_other_binding(self):
        one = self.login('one')
        path = '/aiyoloapi/mobile/model-updates/snapshot'
        self.assertEqual(200, self.client.get(path, params={'deviceId': self.device}, headers=one).status_code)
        two = self.login('two')
        self.assertEqual(403, self.client.get(path, params={'deviceId': self.device}, headers=two).status_code)
        with self.db.session() as session:
            session.get(AccountRecord, 'account-one').enabled = False
        self.client.cookies.clear()
        self.assertEqual(401, self.client.get(path, params={'deviceId': self.device}, headers=one).status_code)

    def test_real_project_owner_permission_and_revocation_apply_to_status(self):
        one = self.login('one')
        path = '/aiyoloapi/projects/project-one/model-update-status'
        self.assertEqual(200, self.client.get(path, headers=one).status_code)
        with self.db.session() as session:
            session.get(ProjectMembershipRecord, ('project-one', 'account-one')).project_role = 'PROJECT_USER'
        self.assertEqual(403, self.client.get(path, headers=one).status_code)
        with self.db.session() as session:
            session.get(ProjectMembershipRecord, ('project-one', 'account-one')).enabled = False
        self.assertEqual(403, self.client.get(path, headers=one).status_code)


@unittest.skipUnless(os.environ.get('RUN_POSTGRES_TESTS') == '1', 'requires isolated PostgreSQL')
class UpdateAuthenticationPostgreSqlTests(UpdateAuthenticationTests):
    use_postgresql = True
