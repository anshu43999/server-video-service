import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier, RLock
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select, text

import app.main as main
from app.auth import Principal
from app.database import (Base, DatabaseManager, DEFAULT_PROJECT_ID, AccountRecord, ProjectRecord,
    ProjectMembershipRecord, ProjectSceneMemberRecord, ProjectScenePlanRecord, ProjectAuditEventRecord,
    PlatformAuditEventRecord, ResourceLifecycleOperationRecord, ResourceLifecycleEventRecord)
from app.model_catalog import ModelCatalog
from app.model_parameters import ModelParameterStore
from app.project_model_assignments import ProjectModelAssignments
from app.project_scenes import ProjectScenes
from app.model_removal import ModelRemoval
from app.resource_lifecycle import guard_model_write
from app.stream_config import StreamConfigStore, StreamConfiguration
from test_project_model_assignments import ModelApiFixture, release


class LifecycleApiTests(ModelApiFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.store = ProjectScenes(None, main.model_catalog, main.project_model_assignments)
        self.patches.enter_context(patch.object(main, 'project_scenes', self.store))
        self.scenes = self.project_path + '/scenes'
        self.scene = {'sceneId': 'safety', 'name': 'Safety', 'inputTypes': ['image'],
            'enabled': True, 'expectedRevision': 0, 'models': []}
        self.project_model_id = None
        self.release_path = '/aiyoloapi/models/helmet/versions/1.0.0'

    def scene_payload(self, **changes):
        if self.project_model_id is None:
            assigned = self._assign()
            self.assertEqual(200, assigned.status_code, assigned.text)
            self.project_model_id = assigned.json()['projectModelId']
        return {**self.scene, 'models': [{
            'memberId': 'helmet', 'projectModelId': self.project_model_id,
            'position': 0, 'execution': 'single',
        }], **changes}

    def create(self, **changes):
        response = self.client.post(self.scenes, headers=self.owner, json=self.scene_payload(**changes))
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def remove(self, path, revision, key='operation-1', headers=None):
        return self.client.delete(path, headers={**(headers or self.owner),
            'If-Match': f'"{revision}"', 'Idempotency-Key': key})

    def test_scene_soft_delete_replay_terminal_identity_and_no_cascade(self):
        self.create()
        self.create(sceneId='other')
        approved = self.client.post(self.scenes+'/safety/approval', headers=self.owner,
            json={'expectedRevision': 1, 'approved': True, 'reason': 'verified'})
        self.assertEqual(200, approved.status_code, approved.text)
        before = main.model_catalog._load()
        impact = self.client.get(self.scenes+'/safety/removal-impact', headers=self.owner)
        self.assertEqual(2, impact.json()['expectedRevision'])
        removed = self.remove(self.scenes+'/safety', 2)
        self.assertEqual(200, removed.status_code, removed.text)
        self.assertEqual(removed.json(), self.remove(self.scenes+'/safety', 2).json())
        self.assertEqual(409, self.remove(self.scenes+'/safety', 3).status_code)
        self.assertEqual(before, main.model_catalog._load())
        self.assertEqual(1, len(self.store.get(self.project_id, 'safety')['models']))
        self.assertEqual(1, len(self.store.get(self.project_id, 'safety')['plans']))
        for headers in (self.owner, self.user):
            response = self.client.get(self.scenes, headers=headers)
            self.assertNotIn('safety', [row['sceneId'] for row in response.json()['scenes']])
        self.assertEqual(404, self.client.post(self.scenes+'/safety/resolve', headers=self.user,
            json={'expectedRevision': 2, 'target': 'pc', 'inputType': 'image'}).status_code)
        self.assertEqual(409, self.client.patch(self.scenes+'/safety', headers=self.owner,
            json={'expectedRevision': 3, 'enabled': True}).status_code)
        self.assertEqual(409, self.client.post(
            self.scenes, headers=self.owner, json=self.scene_payload()).status_code)
        self.create(sceneId='new-identity')

    def test_permissions_and_strict_preconditions_no_legacy_bypass(self):
        self.create()
        path = self.scenes+'/safety'
        self.assertEqual(403, self.client.get(path+'/removal-impact', headers=self.user).status_code)
        self.assertEqual(403, self.remove(path, 1, headers=self.user).status_code)
        self.assertEqual(428, self.client.delete(path, headers=self.owner).status_code)
        self.assertEqual(428, self.client.delete(self.release_path, headers=self.headers).status_code)
        self.assertEqual(403, self.client.get(self.release_path+'/removal-impact', headers=self.owner).status_code)
        self.assertEqual(403, self.remove(self.release_path, 1).status_code)
        for revision in ('1', 'W/"1"', '"0"', '"true"'):
            response = self.client.delete(path, headers={**self.owner, 'If-Match': revision, 'Idempotency-Key': 'test'})
            self.assertEqual(400, response.status_code, response.text)
        self.assertEqual(409, self.remove(path, 9).status_code)
        body = self.client.request('DELETE', path, headers={**self.owner, 'If-Match': '"1"', 'Idempotency-Key': 'body'}, json={'cascade': True})
        self.assertEqual(400, body.status_code)
        other=f'/aiyoloapi/projects/{self.other_id}/scenes/safety'
        self.assertEqual(404, self.remove(other, 1).status_code)

    def test_disabled_unapproved_scene_still_blocks_model_and_preview_is_not_lock(self):
        preview = self.client.get(self.release_path+'/removal-impact', headers=self.headers).json()
        self.assertTrue(preview['safeToRemove'])
        self.create(enabled=False)
        impact = self.client.get(self.release_path+'/removal-impact', headers=self.headers).json()
        self.assertEqual(1, impact['dependentCounts']['scenes'])
        self.assertEqual(1, impact['dependentCounts']['plans'])
        result = self.remove(self.release_path, preview['expectedRevision'], headers=self.headers)
        self.assertEqual(409, result.status_code, result.text)
        self.assertEqual('model_in_use', result.json()['detail']['code'])
        self.assertEqual(200, self.remove(self.scenes+'/safety', 1).status_code)
        self.assertEqual(409, self.client.delete(
            f'{self.project_path}/model-assignments/{self.project_model_id}',
            headers=self.owner, params={'expectedRevision': 1}).status_code)
        result = self.remove(self.release_path, preview['expectedRevision'], key='remove-model', headers=self.headers)
        self.assertEqual(409, result.status_code, result.text)
        self.assertEqual('model_in_use', result.json()['detail']['code'])

    def test_scene_audit_failure_does_not_leave_tombstone(self):
        self.create()
        with patch('app.project_scenes.audit_change', side_effect=RuntimeError('audit failed')):
            with self.assertRaisesRegex(RuntimeError, 'audit failed'):
                self.remove(self.scenes+'/safety', 1)
        self.assertNotIn('deletedAt', self.store.get(self.project_id, 'safety'))
        self.assertEqual(200, self.remove(self.scenes+'/safety', 1).status_code)

    def test_scene_removal_denies_existing_runtime_grant_and_download(self):
        self.create()
        self.assertEqual(200,self.client.post(self.scenes+'/safety/approval',headers=self.owner,
            json={'expectedRevision':1,'approved':True,'reason':'review'}).status_code)
        path=self.scenes+'/safety/plans/default/runtime-grants'
        body={'planId':'default','expectedRevision':2,'target':'pc','inputType':'image',
              'clientContractVersion':3,'supportedExecutionModes':['single']}
        grant=self.client.post(path,headers=self.user,json=body)
        self.assertEqual(200,grant.status_code,grant.text)
        self.assertEqual(200,self.remove(self.scenes+'/safety',2).status_code)
        renew=self.client.post(path,headers=self.user,json={**body,'operation':'renew',
            'grantToken':grant.json()['runtimeGrant']})
        self.assertIn(renew.status_code,(403,404,409))
        self.assertNotEqual(200,self.client.post(path,headers=self.user,json=body).status_code)
        download=self.scenes+'/safety/models/helmet/versions/1.0.0/artifacts/server/download?expectedRevision=2'
        self.assertEqual(404,self.client.get(download,headers=self.user).status_code)


class LifecyclePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        models=root/'models';models.mkdir()
        self.registry=models/'registry.json'
        self.registry.write_text(json.dumps({'models': [release(models, 'helmet', '1.0.0'),
            release(models, 'ppe', '1.0.0')]}), encoding='utf-8')
        if getattr(self, 'use_postgresql', False):
            from postgresql_support import isolated_postgresql_url
            self.pg=isolated_postgresql_url('m112_lifecycle')
            url=self.pg.__enter__();self.addCleanup(lambda:self.pg.__exit__(None,None,None))
        else:
            url=f'sqlite:///{(root/"lifecycle.db").as_posix()}'
        self.db=DatabaseManager(url);self.addCleanup(self.db.close)
        Base.metadata.create_all(self.db.engine)
        with self.db.session() as session:
            if session.get(ProjectRecord, DEFAULT_PROJECT_ID) is None:
                session.add(ProjectRecord(project_id=DEFAULT_PROJECT_ID,project_code='default-lock',display_name='Lock',lifecycle_state='ACTIVE'))
            session.add(ProjectRecord(project_id='test-project',project_code='lifecycle-test',display_name='Test',lifecycle_state='ACTIVE'))
            session.add(AccountRecord(account_id='test-admin',username='lifecycle-admin',password_hash='not-login',role='admin',platform_role='PLATFORM_ADMIN',enabled=True))
        self.principal=Principal('test-admin','lifecycle-admin','admin','PLATFORM_ADMIN')
        self.context=SimpleNamespace(project_id='test-project',project_role='PROJECT_OWNER',principal=self.principal)
        self.catalog=ModelCatalog(self.registry)
        self.parameters=ModelParameterStore(models/'profiles.json',self.db)
        self.streams=StreamConfigStore(self.db)
        self.assignments=ProjectModelAssignments(self.db,self.catalog,self.parameters,self.streams)
        self.scenes=ProjectScenes(self.db,self.catalog,self.assignments)
        self.removal=ModelRemoval(self.db,self.catalog,self.assignments,self.scenes,self.streams,{})
        self.scene={'name':'Safety','inputTypes':['image'],'enabled':True,'models':[]}

    def scene_payload(self):
        if not hasattr(self, 'project_model_id'):
            assigned = self.assignments.save('test-project', 'helmet', '1.0.0', 'pc', 0, True, 0,
                                             context=self.context)
            self.project_model_id = assigned['projectModelId']
        return {'name': 'Safety', 'inputTypes': ['image'], 'enabled': True,
                'models': [{'memberId': 'helmet', 'projectModelId': self.project_model_id,
                            'position': 0, 'execution': 'single'}]}

    def test_scene_tombstone_audit_outbox_members_and_replay_survive_restart(self):
        self.scenes.save('test-project','safety',self.scene_payload(),0,creating=True,context=self.context)
        result=self.scenes.soft_delete('test-project','safety',1,'delete-1',context=self.context)
        self.db.close()
        reopened=ProjectScenes(self.db,self.catalog,self.assignments)
        self.assertEqual(result,reopened.soft_delete('test-project','safety',1,'delete-1',context=self.context))
        with self.db.session() as session:
            self.assertEqual(1,len(session.scalars(select(ProjectSceneMemberRecord)).all()))
            self.assertEqual(1,len(session.scalars(select(ProjectScenePlanRecord)).all()))
            self.assertEqual(1,len(session.scalars(select(ProjectAuditEventRecord).where(ProjectAuditEventRecord.action=='scene.remove')).all()))
            self.assertEqual(1,len(session.scalars(select(ResourceLifecycleEventRecord).where(ResourceLifecycleEventRecord.operation_id==result['operationId'])).all()))
        with self.assertRaises(HTTPException):
            reopened.save('test-project','safety',{'enabled':True},2,context=self.context)

    def test_scene_transaction_rolls_back_on_outbox_failure(self):
        self.scenes.save('test-project','safety',self.scene_payload(),0,creating=True,context=self.context)
        with patch('app.project_scenes.add_event',side_effect=RuntimeError('outbox failed')):
            with self.assertRaises(RuntimeError):
                self.scenes.soft_delete('test-project','safety',1,'delete-1',context=self.context)
        self.assertNotIn('deletedAt',self.scenes.get('test-project','safety'))
        with self.db.session() as session:
            self.assertEqual([],session.scalars(select(ResourceLifecycleOperationRecord)).all())
            self.assertEqual([],session.scalars(select(ProjectAuditEventRecord).where(ProjectAuditEventRecord.action=='scene.remove')).all())

    def test_model_prepared_intent_blocks_new_assignment_then_recovers(self):
        preview=self.removal.impact('helmet','1.0.0',self.principal)
        with patch.object(self.catalog,'uninstall',side_effect=OSError('crash before registry commit')):
            with self.assertRaises(OSError):
                self.removal.execute('helmet','1.0.0',preview['expectedRevision'],'delete-model',self.principal)
        self.assertIsNotNone(self.catalog.get('helmet','1.0.0'))
        with self.assertRaises(HTTPException) as error:
            self.assignments.save('test-project','helmet','1.0.0','pc',0,True,0,context=self.context)
        self.assertIn(error.exception.detail['code'], {'model_removal_in_progress', 'model_target_not_supported'})
        self.assertEqual([], self.assignments.list('test-project'))
        self.db.close()
        self.removal.recover()
        result=self.removal.execute('helmet','1.0.0',preview['expectedRevision'],'delete-model',self.principal)
        self.assertTrue(result['uninstalled'])
        with self.db.session() as session:
            self.assertEqual('confirmed',session.scalar(select(ResourceLifecycleOperationRecord)).stage)
            self.assertEqual(1,len(session.scalars(select(PlatformAuditEventRecord)).all()))
            self.assertEqual(1,len(session.scalars(select(ResourceLifecycleEventRecord)).all()))
        self.assertEqual(1,len([row for row in self.catalog._load()['modelHistory'] if row['status']=='UNINSTALLED']))
        self.assertEqual('ppe',self.catalog.get('ppe','1.0.0')['modelId'])

    def test_model_registry_commit_and_failed_audit_recovers_without_duplicate_tombstone(self):
        with patch('app.model_removal.audit_change',side_effect=RuntimeError('DB projection failed')):
            with self.assertRaises(RuntimeError):
                self.removal.execute('helmet','1.0.0',1,'remove',self.principal)
        with self.assertRaises(KeyError):self.catalog.get('helmet','1.0.0')
        self.db.close();self.removal.recover();self.removal.recover()
        with self.db.session() as session:
            self.assertEqual(1,len(session.scalars(select(PlatformAuditEventRecord)).all()))
        self.assertEqual(1,len(self.catalog._load()['modelHistory']))

    def test_replay_rechecks_current_authority(self):
        self.removal.execute('helmet','1.0.0',1,'remove',self.principal)
        with self.db.session() as session:session.get(AccountRecord,'test-admin').enabled=False
        with self.assertRaises(HTTPException) as error:
            self.removal.execute('helmet','1.0.0',1,'remove',self.principal)
        self.assertEqual(403,error.exception.status_code)

    def test_status_crash_after_registry_commit_replays_once(self):
        original = self.catalog.set_release_status
        def crash(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('crash after atomic status commit')
        with patch.object(self.catalog, 'set_release_status', side_effect=crash):
            with self.assertRaises(RuntimeError):
                self.removal.execute('helmet','1.0.0',1,'revoke',self.principal,action='REVOKED')
        self.removal.recover()
        result=self.removal.execute('helmet','1.0.0',1,'revoke',self.principal,action='REVOKED')
        self.assertEqual(2,result['revision'])
        self.assertEqual(1,len(self.catalog._load()['modelHistory']))
        with self.assertRaises(HTTPException):
            self.removal.execute('helmet','1.0.0',2,'deprecate',self.principal,action='DEPRECATED')
        with self.db.session() as session:
            self.assertEqual(1,len(session.scalars(select(ResourceLifecycleOperationRecord)).all()))

    def test_pending_intent_blocks_direct_runtime_download_and_registry_mutation(self):
        with patch.object(self.catalog,'uninstall',side_effect=OSError('retry later')):
            with self.assertRaises(OSError):
                self.removal.execute('helmet','1.0.0',1,'remove',self.principal)
        for resolve in (lambda:self.catalog.resolve_server_model('helmet','1.0.0'),
                        lambda:self.catalog.get_artifact('helmet','server','1.0.0')):
            with self.assertRaisesRegex(ValueError,'pending'):resolve()
        # Simulate the crash window before the registry mirror was persisted.
        registry=self.catalog._load();registry.pop('lifecycleRequests')
        self.registry.write_text(json.dumps(registry),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'pending'):
            self.catalog.set_release_status('helmet','1.0.0','REVOKED')
        self.removal.recover()

    def test_cleanup_failure_recovers_without_cascade_or_duplicate_facts(self):
        blocked=self.catalog._artifact_path(self.catalog._find_entry(self.catalog._load(),'helmet','1.0.0'))
        unlink=Path.unlink
        def limited(path,*args,**kwargs):
            if path==blocked:raise PermissionError('file in use')
            return unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',limited):
            result=self.removal.execute('helmet','1.0.0',1,'remove',self.principal)
        self.assertTrue(result['cleanupFailures']);self.assertTrue(blocked.exists())
        self.removal.recover();self.assertFalse(blocked.exists())
        result=self.removal.execute('helmet','1.0.0',1,'remove',self.principal)
        self.assertEqual([],result['cleanupFailures'])
        self.assertEqual('ppe',self.catalog.get('ppe','1.0.0')['modelId'])
        with self.db.session() as session:
            self.assertEqual(1,len(session.scalars(select(PlatformAuditEventRecord)).all()))
            self.assertEqual(1,len(session.scalars(select(ResourceLifecycleEventRecord)).all()))

    def test_confirmed_database_and_failed_final_registry_ack_recovers(self):
        save=self.catalog._save
        def crash(registry):
            if any(row.get('stage')=='confirmed' for row in registry.get('lifecycleRequests',{}).values()):
                raise OSError('crash before final registry acknowledgement')
            return save(registry)
        with patch.object(self.catalog,'_save',side_effect=crash):
            with self.assertRaises(OSError):
                self.removal.execute('helmet','1.0.0',1,'revoke',self.principal,action='REVOKED')
        self.removal.recover()
        self.assertEqual('confirmed',next(iter(self.catalog._load()['lifecycleRequests'].values()))['stage'])
        self.assertEqual(1,len(self.catalog._load()['modelHistory']))

    def test_recovery_reads_stage_after_waiting_for_catalog_lock(self):
        with patch.object(self.catalog,'uninstall',side_effect=OSError('crash')):
            with self.assertRaises(OSError):
                self.removal.execute('helmet','1.0.0',1,'remove',self.principal)
        original = self.catalog.mutation_guard
        completed = []
        @contextmanager
        def finish_before_lock(*args, **kwargs):
            if not completed:
                completed.append(True)
                # Emulate a different worker completing while recovery waits for its lock.
                self.removal.execute('helmet','1.0.0',1,'remove',self.principal)
            with original(*args, **kwargs):
                yield
        with patch.object(self.catalog,'mutation_guard',side_effect=finish_before_lock), \
                patch.object(self.removal,'_finish',wraps=self.removal._finish) as finish:
            self.removal.recover()
        self.assertEqual(1,finish.call_count)
        with self.db.session() as session:
            self.assertEqual('confirmed',session.scalar(select(ResourceLifecycleOperationRecord)).stage)
            self.assertEqual(1,len(session.scalars(select(ResourceLifecycleEventRecord)).all()))

    def test_prepared_and_confirmed_revocation_block_late_stream_bind(self):
        config=StreamConfiguration(stream_id='late',display_name='Late',source_type='websocket',
            source_url=None,model_id='helmet',model_version='1.0.0',yolo_enabled=True,
            confidence=.25,max_fps=10,overlay_enabled=True,project_id='test-project')
        with patch.object(self.catalog,'set_release_status',side_effect=OSError('crash')):
            with self.assertRaises(OSError):
                self.removal.execute('helmet','1.0.0',1,'revoke',self.principal,action='REVOKED')
        with self.assertRaises(HTTPException):self.streams.create(config)
        self.removal.recover()
        with self.assertRaises(HTTPException):self.streams.create(config)
        self.assertEqual([],self.streams.list('test-project'))

    @unittest.skipUnless(os.environ.get('RUN_POSTGRES_TESTS')=='1','requires PostgreSQL row locks')
    def test_independent_writer_race_never_leaves_deleted_release_dependency(self):
        if not getattr(self,'use_postgresql',False):self.skipTest('PostgreSQL variant only')
        # Independent process-local locks leave only the shared PG boundary to arbitrate.
        writer=ProjectScenes(self.db,self.catalog,self.assignments);writer._lock=RLock()
        params=ModelParameterStore(self.registry.parent/'race-profiles.json',self.db)
        params._import_legacy_once()
        writer.assignments=ProjectModelAssignments(self.db,self.catalog,params,self.streams)
        writer.assignments._lock=RLock()
        start=Barrier(2)
        def create():
            start.wait(timeout=5)
            try:
                writer.save('test-project','safety',self.scene_payload(),0,creating=True,context=self.context)
                return 'created'
            except HTTPException:return 'blocked'
        def remove():
            start.wait(timeout=5)
            try:
                self.removal.execute('helmet','1.0.0',1,'race',self.principal)
                return 'removed'
            except HTTPException:return 'blocked'
        with ThreadPoolExecutor(max_workers=2) as executor:
            left,right=executor.submit(create),executor.submit(remove)
            outcome=(left.result(timeout=15),right.result(timeout=15))
        self.assertIn(outcome,(('created','blocked'),('blocked','removed')))


@unittest.skipUnless(os.environ.get('RUN_POSTGRES_TESTS')=='1','requires isolated PostgreSQL schema')
class LifecyclePostgreSqlTests(LifecyclePersistenceTests):
    use_postgresql=True
