from types import SimpleNamespace
from unittest.mock import patch
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import Principal
from app.model_updates.api import create_router
from app.model_updates.models import Device, Inbox
from app.model_updates.service import ModelUpdateService
from app.project_auth import PROJECT_MODELS_ASSIGN
import test_model_updates as fixtures
from test_model_updates import binding_request


class UpdateApiTests(unittest.TestCase):
    put = fixtures.UpdateStoreTests.put
    error = fixtures.UpdateStoreTests.error

    def setUp(self):
        fixtures.UpdateStoreTests.setUp(self)
        self.service = ModelUpdateService(self.db, None, None)
        # Direct fixture inbox records are used for HTTP protocol tests; genuine
        # catalog/approval authority is exercised separately in projection tests.
        del self.service.store.authority
        self.service.projection.one = lambda _: True
        app = FastAPI(); app.include_router(create_router(lambda:self.service))
        self.client = TestClient(app, base_url='https://test.example')
        self.addCleanup(self.client.close)
        self.principal = Principal('account-one','one','operator','NORMAL_USER')
        self.auth = patch('app.model_updates.api.auth.authenticate',return_value=self.principal)
        self.auth.start(); self.addCleanup(self.auth.stop)

    def test_unauthenticated_is_401_and_legacy_credentials_cannot_bind(self):
        for user in (None, Principal('legacy:admin','old','admin','PLATFORM_ADMIN',legacy=True)):
            with patch('app.model_updates.api.auth.authenticate', return_value=user):
                result = self.client.put('/aiyoloapi/mobile/model-update-devices/test',json=binding_request('test'))
            self.assertEqual(401,result.status_code)
            self.assertEqual('login_required',result.json()['errorCode'])

    def test_bind_unknown_fields_account_spoof_and_route_mismatch_rejected(self):
        path='/aiyoloapi/mobile/model-update-devices/installation-one'
        for body in (binding_request()|{'accountId':'account-two'},binding_request('other')):
            self.assertEqual(400,self.client.put(path,json=body).status_code)
        result=self.client.put(path,json=binding_request())
        self.assertEqual(200,result.status_code,result.text)
        self.assertEqual(self.binding,result.json()['binding'])

    def test_unauthenticated_report_is_rejected_before_json_validation(self):
        with patch('app.model_updates.api.auth.authenticate', return_value=None):
            result = self.client.post('/aiyoloapi/mobile/model-update-reports', content=b'{broken')
        self.assertEqual(401, result.status_code)

    def test_malformed_duplicate_json_and_byte_limits_are_atomic(self):
        path='/aiyoloapi/mobile/model-update-devices/'+self.device+'/inventory'
        self.assertEqual(400,self.client.put(path,content=b'{"a":1,"a":2}').status_code)
        self.assertEqual(413,self.client.put(path,content=b' '* (2*1024*1024+1)).status_code)
        with self.db.session() as session:
            self.assertEqual(0,session.get(Device,self.device).inventory_revision)

    def test_query_limit_duplicate_and_forged_cursor_errors(self):
        path='/aiyoloapi/mobile/model-updates'
        self.assertEqual(400,self.client.get(path,params={'deviceId':self.device,'cursor':'x','limit':201}).status_code)
        self.assertEqual(400,self.client.get(path+'?deviceId=x&deviceId=y&cursor=x').status_code)
        self.assertEqual(410,self.client.get(path,params={'deviceId':self.device,'cursor':'forged'}).status_code)

    def test_wrong_collection_types_return_400_not_internal_error(self):
        base = dict(messageType='inventory_request', contractVersion=1, binding=self.binding, inventoryRevision=1)
        path = '/aiyoloapi/mobile/model-update-devices/'+self.device+'/inventory'
        for entries in (None, 7, 'invalid', {}):
            self.assertEqual(400, self.client.put(path, json=base | {'entries': entries}).status_code)
        body = dict(messageType='report_request', contractVersion=1, binding=self.binding, reports=None)
        self.assertEqual(400, self.client.post('/aiyoloapi/mobile/model-update-reports', json=body).status_code)

    def test_status_denies_member_and_pages_for_manager_without_mobile_installation(self):
        self.put(1); self.put(2)
        path='/aiyoloapi/projects/project-one/model-update-status'
        member=SimpleNamespace(capabilities=frozenset(),platform_entry=False)
        with patch('app.model_updates.api.resolve_project_context',return_value=member):
            self.assertEqual(403,self.client.get(path).status_code)
        manager=SimpleNamespace(capabilities={PROJECT_MODELS_ASSIGN},platform_entry=False)
        # Manager has no registered mobile device.
        with self.db.session() as session:
            session.get(Device,self.device).account_id='account-two'
            from app.database import ProjectMembershipRecord
            session.get(ProjectMembershipRecord, ('project-one', 'account-one')).project_role = 'PROJECT_OWNER'
            session.add(ProjectMembershipRecord(project_id='project-one',account_id='account-two',project_role='PROJECT_USER',enabled=True))
        with patch('app.model_updates.api.resolve_project_context',return_value=manager):
            first=self.client.get(path,params={'limit':1})
            self.assertEqual(200,first.status_code,first.text)
            self.assertIsNotNone(first.json()['nextPageToken'])
            second=self.client.get(path,params={'limit':1,'pageToken':first.json()['nextPageToken']})
            self.assertEqual(200,second.status_code,second.text)
            self.assertNotEqual(first.json()['items'],second.json()['items'])
        self.assertNotIn('pushToken',str(first.json()))
        self.assertNotIn('installationId',str(first.json()))

    def test_rate_limited_response_has_retry_after(self):
        for _ in range(10): self.service.store.rate_limit(self.device,rate=0)
        result=self.client.get('/aiyoloapi/mobile/model-updates/snapshot',params={'deviceId':self.device})
        self.assertEqual(429,result.status_code);self.assertEqual('1',result.headers['retry-after'])
