"""Real catalog files + real assignment/scene transactions, not oracle I/O."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from sqlalchemy import select

from app.database import ProjectModelAssignmentRecord, ProjectRecord, DEFAULT_PROJECT_ID
from app.model_catalog import ModelCatalog
from app.model_parameters import ModelParameterStore
from app.project_model_assignments import ProjectModelAssignments
from app.project_scenes import ProjectScenes
from app.model_updates.models import Device, Inbox, DomainEvent, Change
from app.model_updates.projection import Projection, approved_artifact
from app.model_updates.service import ModelUpdateService
from app.model_updates.protocol import digest, now, validate
import test_model_updates as common
from test_project_model_assignments import release


class UpdateProjectionTests(unittest.TestCase):
    error = common.UpdateStoreTests.error
    def setUp(self):
        common.UpdateStoreTests.setUp(self)
        import tempfile
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root=Path(temp.name); models=self.root/'models';models.mkdir()
        self.registry=models/'registry.json'
        entries=[]
        for model_id, version in [('ppe','1.0.0'),('ppe','2.0.0'),('helmet','1.0.0')]:
            entry=release(models,model_id,version)
            entry.update(androidReady=True,androidConverted=True,signatureStatus='signed',
                         supportedTargets=['pc','mobile'],publishedTargets=['pc','mobile'])
            path=models/(model_id+'-'+version+'-manifest.json')
            path.write_text(json.dumps({'fixture':'control-plane-only','modelId':model_id,'version':version}),encoding='utf-8')
            entry['artifacts'].append(dict(artifactId='android-manifest',format='json',platform='android',
                path='models/'+path.name,sizeBytes=path.stat().st_size,sha256=ModelCatalog.sha256(path)))
            entries.append(entry)
        self.registry.write_text(json.dumps({'models':entries}),encoding='utf-8')
        self.catalog=ModelCatalog(self.registry)
        self.parameters=ModelParameterStore(models/'profiles.json',self.db)
        self.assignments=ProjectModelAssignments(self.db,self.catalog,self.parameters)
        self.scenes=ProjectScenes(self.db,self.catalog,self.assignments)
        self.projection=Projection(self.store,self.catalog,self.scenes)
        self.store.authority=self.projection.authorized
        with self.db.session() as session:
            if session.get(ProjectRecord,DEFAULT_PROJECT_ID) is None:
                session.add(ProjectRecord(project_id=DEFAULT_PROJECT_ID,project_code='default-lock',display_name='Lock'))
        self.saved=self.assignments.save('project-one','ppe','1.0.0','mobile',0,True,0)

    def upload(self, entries, revision=1):
        return self.store.inventory('account-one',self.device,dict(messageType='inventory_request',contractVersion=1,
            binding=self.binding,inventoryRevision=revision,entries=entries))

    def entry(self):
        artifact=approved_artifact(self.catalog.get('ppe','1.0.0'),self.assignments.snapshot('project-one','ppe','1.0.0','android'))
        return dict(entryId='retained-one',source=dict(projectId='project-one',kind='assignment',
            assignmentId=self.saved['assignmentId'],platform='mobile',sourceEpoch=1),retainedRevision=1,
            selectionGeneration=1,active=False,artifacts=[artifact])

    def current(self):
        return self.store.snapshot('account-one',self.device)['items']

    def test_publish_notice_is_not_install_permission_and_cold_bind_recovers(self):
        self.projection.one(self.device)
        notices=self.current()
        self.assertEqual(1,len(notices))
        self.assertEqual(('release_available','waiting_approval',None),
                         (notices[0]['kind'],notices[0]['stage'],notices[0]['target']))
        self.assertEqual('2.0.0',notices[0]['release']['version'])
        self.assertEqual([],self.db_inventory())

    def db_inventory(self):
        with self.db.session() as session:return session.get(Device,self.device).inventory

    def test_assignment_approval_generates_exact_target_and_scan_is_idempotent(self):
        approved = self.assignments.save('project-one','ppe','2.0.0','mobile',0,True,0)
        entry = self.entry()
        entry['source']['assignmentId'] = approved['assignmentId']
        self.upload([entry])
        self.projection.one(self.device)
        ready=[v for v in self.current() if v['kind']=='update_ready']
        self.assertEqual(1,len(ready))
        target=ready[0]['target'];self.assertEqual(1,target['approvalRevision'])
        self.assertEqual('installed',target['successCriteria'])
        self.assertEqual(0,target['artifacts'][0]['parameterRevision'])
        self.assertEqual('2.0.0',target['artifacts'][0]['version'])
        with self.db.session() as session:before=session.get(Device,self.device).sequence
        self.projection.one(self.device)
        with self.db.session() as session:self.assertEqual(before,session.get(Device,self.device).sequence)

    def test_inventory_without_approval_cannot_create_executable_target(self):
        entry=self.entry();entry['source']['assignmentId']='forged-assignment'
        self.upload([entry]);self.projection.one(self.device)
        self.assertFalse(any(v['target'] is not None for v in self.current()))

    def test_running_target_preserved_and_successors_coalesce_to_current_approval(self):
        approved = self.assignments.save('project-one', 'ppe', '2.0.0', 'mobile', 0, True, 0)
        entry = self.entry()
        entry['source']['assignmentId'] = approved['assignmentId']
        entry['artifacts'][0]['version'] = '0.9.0'
        self.upload([entry])
        self.projection.one(self.device)
        first = next(v for v in self.current() if v['kind'] == 'update_ready')
        report = dict(eventId='started', updateId=first['updateId'], itemRevision=1, attemptId='round-one',
            reportSeq=1, stage='downloading', digest=first['target']['targetDigest'], completedCriteria=None, errorCode=None)
        body = dict(messageType='report_request', contractVersion=1, binding=self.binding, reports=[report])
        self.assertEqual('accepted', self.store.reports('account-one', body)['results'][0]['outcome'])
        for revision in (1, 2, 3):
            self.assignments.save('project-one', 'ppe', '2.0.0', 'mobile', 0, True, revision)
            self.projection.one(self.device)
        current = [v for v in self.current() if v['kind'] == 'update_ready']
        self.assertEqual([4], [v['target']['approvalRevision'] for v in current])
        with self.db.session() as session:
            rows = session.scalars(select(Inbox).where(Inbox.device_id == self.device)).all()
            running = [row for row in rows if row.payload['stage'] == 'downloading']
            self.assertEqual([first['updateId']], [row.update_id for row in running])
            self.assertEqual(1, len([row for row in rows if row.is_current and row.payload['target']]))
            self.assertTrue(all(row.payload['stage'] == 'superseded' for row in rows
                if row.payload['target'] and row.payload['target']['approvalRevision'] in (2, 3)))
        stale_commit = dict(report, eventId='old-commit', reportSeq=2, stage='installed', completedCriteria='installed')
        self.assertEqual('target_changed', self.store.reports('account-one', body | {'reports': [stale_commit]})['results'][0]['errorCode'])
        cancelled = dict(report, eventId='old-cancelled', reportSeq=3, stage='superseded')
        self.assertEqual('accepted', self.store.reports('account-one', body | {'reports': [cancelled]})['results'][0]['outcome'])
        self.assertEqual('duplicate', self.store.reports('account-one', body | {'reports': [cancelled]})['results'][0]['outcome'])
        with self.db.session() as session:
            self.assertEqual('superseded', session.get(Inbox, (self.device, first['updateId'])).payload['stage'])
        self.upload([], 2)
        self.projection.one(self.device)
        with self.db.session() as session:
            self.assertFalse(any(row.payload['stage'] == 'downloading' for row in session.scalars(select(Inbox))))

    def test_parameter_digest_uses_existing_android_canonical_identity(self):
        from app.scene_parameter_digest import parameter_digest
        parameters = {'revision': 0, 'score': 0.0, 'threshold': 1.0, 'labels': ['安全帽']}
        artifact = approved_artifact(self.catalog.get('ppe', '1.0.0'), parameters)
        self.assertEqual(parameter_digest(parameters), artifact['parameterDigest'])
        self.assertNotEqual(digest(parameters), artifact['parameterDigest'])

    def test_scene_approved_latest_release_does_not_emit_waiting_approval(self):
        body = dict(name='Approved suite', inputTypes=['image'], enabled=True,
            models=[dict(memberId='ppe-member',
                         projectModelId=self.assignments.save('project-one', 'ppe', '2.0.0',
                             'mobile', 0, True, 0)['projectModelId'],
                         position=0, inputTypes=['image'], execution='single')])
        self.scenes.save('project-one', 'approved-suite', body, 0, creating=True)
        self.scenes.save('project-one', 'approved-suite', {'approved': True}, 1, approval_reason='internal test')
        self.projection.one(self.device)
        self.assertFalse(any(value['kind'] == 'release_available' and value['release']['version'] == '2.0.0'
                             for value in self.current()))

    def test_plan_expansion_does_not_silently_expand_original_selection(self):
        helmet = self.assignments.save('project-one', 'helmet', '1.0.0', 'mobile', 0, True, 0)
        members = [dict(memberId='ppe-member', projectModelId=self.saved['projectModelId'],
            position=0, inputTypes=['image'], execution='single'),
            dict(memberId='helmet-member', projectModelId=helmet['projectModelId'],
            position=1, inputTypes=['image'], execution='single')]
        plan = dict(planId='photo', name='Photo', inputTypes=['image'], memberIds=['ppe-member'],
                    execution='single', enabled=True)
        self.scenes.save('project-one', 'plan-suite', dict(name='Suite', inputTypes=['image'],
            enabled=True, models=members, plans=[plan]), 0, creating=True)
        self.scenes.save('project-one', 'plan-suite', {'approved': True}, 1, approval_reason='internal test')
        selection = dict(planIds=['photo'], memberIds=['ppe-member'])
        entry = self.entry()
        entry['source'] = dict(projectId='project-one', kind='scene', sceneId='plan-suite',
            platform='mobile', sourceEpoch=1, selection=selection, selectionDigest=digest(selection))
        entry['retainedRevision'] = 2
        self.upload([entry])
        plan.update(memberIds=['ppe-member', 'helmet-member'], execution='sync')
        self.scenes.save('project-one', 'plan-suite', {'plans': [plan]}, 2)
        self.scenes.save('project-one', 'plan-suite', {'approved': True}, 3, approval_reason='internal test')
        self.projection.one(self.device)
        self.assertFalse(any(value['kind'] == 'update_ready' for value in self.current()))
        self.assertEqual(selection, self.db_inventory()[0]['source']['selection'])

    def test_scan_uses_hundred_device_batches_and_restart_replays_failed_batch(self):
        from collections import Counter
        import threading
        with self.db.session() as session:
            original = session.get(Device, self.device)
            for index in range(204):
                session.add(Device(device_id='fleet-' + str(index).zfill(4),
                    installation_id=original.installation_id, epoch=index + 2,
                    account_id=original.account_id, origin=original.origin, capabilities=original.capabilities,
                    push_provider='none', notification_permission='denied'))
        sizes, visited, lock = [], [], threading.Lock()
        original_batch = self.projection._batch
        def batch(devices):
            with lock:
                sizes.append(len(devices))
            return original_batch(devices)
        def project(device_id):
            with lock:
                visited.append(device_id)
            return device_id != self.device
        with patch.object(self.projection, '_batch', side_effect=batch), \
                patch.object(self.projection, '_safe_one', side_effect=project):
            result = self.projection.scan()
        self.assertEqual([5, 100, 100], sorted(sizes))
        self.assertEqual((204, 1), (result['processedDevices'], result['failedDevices']))
        self.assertEqual(205, len(Counter(visited)))
        with self.db.session() as session:
            self.assertTrue(session.scalars(select(DomainEvent).where(DomainEvent.processed_at.is_(None))).all())
        self.db.close()
        with patch.object(self.projection, '_safe_one', return_value=True):
            self.assertEqual(0, self.projection.scan()['failedDevices'])
        with self.db.session() as session:
            self.assertFalse(session.scalars(select(DomainEvent).where(DomainEvent.processed_at.is_(None))).all())

    def test_retired_source_cannot_be_revived_by_newer_inventory_revision(self):
        entry = self.entry()
        self.upload([entry], 1)
        self.upload([], 2)
        self.db.close()
        self.error(409, lambda: self.upload([entry], 3))
        self.assertEqual([], self.db_inventory())
        entry['source']['sourceEpoch'] = 2
        self.upload([entry], 3)
        self.assertEqual(2, self.db_inventory()[0]['source']['sourceEpoch'])
        old = self.entry()
        self.error(409, lambda: self.upload([old], 4))

    def test_two_entries_cannot_alias_one_retained_source(self):
        first = self.entry(); second = deepcopy(first); second['entryId'] = 'duplicate'
        self.error(400, lambda: self.upload([first, second]))
        self.assertEqual([], self.db_inventory())

    def test_disabled_account_retires_binding_without_dispatching_old_token(self):
        from app.database import AccountRecord
        with self.db.session() as session:
            session.get(AccountRecord, 'account-one').enabled = False
        self.assertTrue(self.projection.one(self.device))
        with self.db.session() as session:
            self.assertTrue(session.get(Device, self.device).revoked)
            self.assertIsNone(session.get(Device, self.device).push_token)

    def test_authority_revocation_is_checked_before_periodic_scan(self):
        approved = self.assignments.save('project-one','ppe','2.0.0','mobile',0,True,0)
        entry = self.entry(); entry['source']['assignmentId'] = approved['assignmentId']
        self.upload([entry])
        self.projection.one(self.device)
        self.assignments.save('project-one','ppe','2.0.0','mobile',0,False,1)
        self.assertFalse(any(v['kind']=='update_ready' for v in self.current()))
        self.projection.one(self.device)
        self.assertTrue(any(v['stage']=='invalidated' for v in self.current()))

    def test_assignment_domain_event_rolls_back_with_business_write(self):
        with patch('app.model_updates.events.add_domain_event',side_effect=RuntimeError('outbox fault')):
            with self.assertRaises(RuntimeError):
                self.assignments.save('project-one','ppe','2.0.0','mobile',0,True,0)
        self.assertFalse(any(row['modelVersion'] == '2.0.0' for row in self.assignments.list('project-one')))

    def test_registry_failure_keeps_events_and_projection_then_restart_repairs(self):
        approved = self.assignments.save('project-one','ppe','2.0.0','mobile',0,True,0)
        entry = self.entry(); entry['source']['assignmentId'] = approved['assignmentId']
        self.upload([entry])
        with patch.object(self.catalog,'_load',side_effect=OSError('registry offline')):
            with self.assertRaises(OSError):self.projection.scan()
        with self.db.session() as session:
            self.assertTrue(session.scalars(select(DomainEvent).where(DomainEvent.processed_at.is_(None))).all())
            self.assertEqual(0,session.get(Device,self.device).sequence)
        self.db.close()
        result=self.projection.scan()
        self.assertEqual(0,result['failedDevices'])
        self.assertTrue(any(v['kind']=='update_ready' for v in self.current()))

    def test_original_scene_selection_not_expanded_by_new_member(self):
        body=dict(name='Safety',inputTypes=['image'],enabled=True,models=[dict(memberId='ppe-member',
            projectModelId=self.saved['projectModelId'],position=0,inputTypes=['image'],execution='single')])
        self.scenes.save('project-one','safety',body,0,creating=True)
        self.scenes.save('project-one','safety',{'approved':True},1,approval_reason='internal test')
        scene=self.scenes.get('project-one','safety')
        artifact=approved_artifact(self.catalog.get('ppe','1.0.0'),scene['models'][0]['parameterSnapshot'])
        selection=dict(planIds=[],memberIds=['ppe-member'])
        source=dict(projectId='project-one',kind='scene',sceneId='safety',selectionDigest=digest(selection),
                    platform='mobile',sourceEpoch=1,selection=selection)
        entry=dict(entryId='suite-one',source=source,retainedRevision=2,selectionGeneration=1,active=False,artifacts=[artifact])
        self.upload([entry])
        helmet = self.assignments.save('project-one', 'helmet', '1.0.0', 'mobile', 0, True, 0)
        body['models'].append(dict(memberId='helmet-member',projectModelId=helmet['projectModelId'],
                                   position=1,inputTypes=['image'],execution='single'))
        self.scenes.save('project-one','safety',body,2)
        self.scenes.save('project-one','safety',{'approved':True},3,approval_reason='internal test')
        self.projection.one(self.device)
        targets=[v['target'] for v in self.current() if v['kind']=='update_ready']
        self.assertEqual(1,len(targets))
        self.assertEqual(['ppe'],[a['modelId'] for a in targets[0]['artifacts']])
        self.assertEqual('revision_selected',targets[0]['successCriteria'])
        self.assertEqual(selection,targets[0]['source']['selection'])


@unittest.skipUnless(os.environ.get('RUN_POSTGRES_TESTS')=='1','requires isolated PostgreSQL')
class UpdateProjectionPostgreSqlTests(UpdateProjectionTests):
    use_postgresql=True
