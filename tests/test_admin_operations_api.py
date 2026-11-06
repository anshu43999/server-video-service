"""Authenticated project rule CRUD, capability checks and audit contracts."""
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from fastapi.testclient import TestClient
import app.main as main
from app.alerts.rules import RuleRegistry
from app.stream_config import StreamConfigStore
from project_api_support import ProjectApiSupport


class AdminOperationsApiTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        self.registry = RuleRegistry()
        self.patch_rules = patch('app.main.rule_registry', self.registry)
        self.patch_sources = patch('app.main.streams', main.ProjectStreamRegistry())
        self.patch_config = patch('app.main.stream_config_store', StreamConfigStore(None))
        for item in (self.patch_rules, self.patch_sources, self.patch_config):
            item.start()
            self.addCleanup(item.stop)
        self.start_project_api('operations-project')
        self.addCleanup(self.stop_project_api)
        self.caps = ['BOX']
        main.streams[(self.project_id, 'gate')] = SimpleNamespace(
            model_metadata=lambda: {'modelId': 'helmet-model', 'capabilities': self.caps},
            close=AsyncMock())
        self.rules = self.project_path + '/rules'
        self.rule = {'ruleId': 'helmet', 'name': 'Helmet rule', 'operator': 'PRESENCE',
                     'subjectKind': 'track', 'enabled': True, 'requires': ['BOX'],
                     'targetLabels': ['head'], 'thresholds': {'minimumConfidence': 0.55}}

    def test_cookie_authenticated_create_edit_bind_audit_and_delete(self):
        created = self.client.post(self.rules, json=self.rule)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()['ruleVersion'], 1)
        self.assertEqual(self.client.post(self.rules, json=self.rule).status_code, 409)
        updated = self.client.put(self.rules + '/helmet', json={**self.rule, 'name': 'Updated', 'expectedRevision': 1})
        self.assertEqual(updated.json()['ruleVersion'], 2)
        source = {'sourceId': 'gate', 'modelId': 'helmet-model', 'capabilities': ['BOX']}
        self.caps = []
        missing = self.client.post(self.rules + '/helmet/validate', json=source)
        self.assertEqual(missing.status_code, 200)
        self.assertFalse(missing.json()['accepted'])
        self.assertEqual(self.client.post(self.rules + '/helmet/bindings', json={**source, 'expectedRevision': 2}).status_code, 409)
        self.caps = ['BOX']
        self.assertTrue(self.client.post(self.rules + '/helmet/validate', json={**source, 'capabilities': []}).json()['accepted'])
        bound = self.client.post(self.rules + '/helmet/bindings', json={**source, 'expectedRevision': 3})
        self.assertTrue(bound.json()['accepted'])
        self.assertEqual(bound.json()['ruleVersion'], 4)
        self.assertEqual(len(self.client.get(self.rules + '/helmet/bindings').json()['bindings']), 1)
        actions = [a['action'] for a in self.client.get(self.rules + '/audit').json()['audit']]
        self.assertEqual(actions, ['create', 'update', 'reject', 'bind'])
        removed = self.client.delete(self.rules + '/helmet/bindings/gate?expectedRevision=4')
        self.assertEqual(removed.json()['ruleVersion'], 5)
        self.assertEqual(self.client.get(self.rules + '/helmet/bindings').json()['bindings'], [])
        self.assertEqual(self.client.delete(self.rules + '/helmet?expectedRevision=5').status_code, 204)
        self.assertEqual(self.client.get(self.rules + '/helmet').status_code, 404)

    def test_unsupported_combination_and_invalid_geometry_are_explicit(self):
        self.assertEqual(self.client.post(self.rules, json={**self.rule, 'operator': 'COMPOSITE'}).status_code, 201)
        result = self.client.post(self.rules + '/helmet/validate', json={'sourceId': 'gate', 'capabilities': ['BOX']})
        self.assertFalse(result.json()['accepted'])
        self.assertEqual(result.json()['code'], 'OPERATOR_NOT_IMPLEMENTED')
        invalid = self.client.post(self.rules, json={**self.rule, 'ruleId': 'invalid', 'roi': {'shape': 'POLYGON', 'points': []}})
        self.assertEqual(invalid.status_code, 422)

    def test_operator_and_anonymous_cannot_write_rules(self):
        account = self.client.post('/aiyoloapi/platform/accounts', headers=self.headers, json={
            'username': 'operations-user', 'password': 'temporary-test-password', 'platformRole': 'NORMAL_USER',
        }).json()
        self.client.post(self.project_path + '/members', headers=self.headers, json={
            'accountId': account['accountId'], 'projectRole': 'PROJECT_USER'})
        operator = TestClient(main.app)
        self.addCleanup(operator.close)
        self.assertEqual(operator.post('/aiyoloapi/auth/login', json={
            'username': 'operations-user', 'password': 'temporary-test-password',
        }).status_code, 200)
        self.assertEqual(operator.post(self.rules, json=self.rule).status_code, 403)
        anonymous = TestClient(main.app)
        self.addCleanup(anonymous.close)
        self.assertEqual(anonymous.get(self.rules).status_code, 401)
