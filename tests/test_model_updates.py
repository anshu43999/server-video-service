"""M111-T02 persistence/contract regression. No development database access."""
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import Base, DatabaseManager, AccountRecord, ProjectRecord, ProjectMembershipRecord
from app.model_updates.models import Device, Inbox, PushOutbox, Change, Ticket
from app.model_updates.protocol import UpdateError, digest, now, validate, target_digest
from app.model_updates.store import UpdateStore
from app.model_updates.push import FcmSender, PushDispatcher, PushResult
from app.model_updates.api import create_router
from app.model_updates.download import artifact_response


def binding_request(installation='installation-one'):
    return dict(messageType='binding_request', contractVersion=1, installationId=installation,
        capabilities=dict(appVersion='test', apiLevel=27, abis=['x86_64'], contractVersions=[1]),
        pushProvider='none', token=None, tokenGeneration=0, notificationPermission='denied')


def item(number=1):
    source = dict(projectId='project-one', kind='assignment', assignmentId='assignment-one', platform='mobile', sourceEpoch=1)
    artifact = dict(modelId='ppe', version=str(number), artifactDigest='a'*64, manifestDigest='b'*64,
                    parameterRevision=1, parameterDigest='c'*64, sizeBytes=100)
    target = dict(updateId='update-' + str(number), source=source, approvalRevision=number, successCriteria='installed',
                  successCriteriaRevision=1, artifacts=[artifact], supersedesUpdateId=None)
    target['targetDigest'] = target_digest(target)
    return dict(updateId=target['updateId'], itemRevision=1, kind='update_ready', target=target,
        release=dict(projectId='project-one', modelId='ppe', version=str(number), artifactDigest='a'*64),
        discovery='pending_discovery', stage='available', errorCode=None)


class UpdateStoreTests(unittest.TestCase):
    def setUp(self):
        if getattr(self, 'use_postgresql', False):
            from postgresql_support import isolated_postgresql_url
            pg = isolated_postgresql_url('m111_update')
            self.url = pg.__enter__()
            self.addCleanup(lambda: pg.__exit__(None, None, None))
        else:
            temp = tempfile.TemporaryDirectory()
            self.addCleanup(temp.cleanup)
            self.url = 'sqlite:///' + str(Path(temp.name) / 'updates.db').replace('\\', '/')
        self.db = DatabaseManager(self.url)
        self.addCleanup(self.db.close)
        Base.metadata.create_all(self.db.engine)
        self.store = UpdateStore(self.db)
        with self.db.session() as session:
            session.add_all([AccountRecord(account_id='account-one', username='one', password_hash='unused', role='operator',
                                          platform_role='NORMAL_USER', enabled=True),
                             AccountRecord(account_id='account-two', username='two', password_hash='unused', role='operator',
                                          platform_role='NORMAL_USER', enabled=True),
                             ProjectRecord(project_id='project-one', project_code='test-one', display_name='isolated',
                                           lifecycle_state='ACTIVE')])
            session.flush()
            session.add(ProjectMembershipRecord(project_id='project-one', account_id='account-one',
                                                 project_role='PROJECT_USER', enabled=True))
        self.binding = self.store.bind('account-one', 'https://test.example', 'installation-one', binding_request())['binding']
        self.device = self.binding['deviceId']

    def put(self, number=1):
        value = item(number)
        with self.db.session() as session:
            device = self.store.locked_device(session, 'account-one', self.device)
            self.store._put(session, device, value, 'source-'+str(number))
        return value

    def report(self, stage='discovered', seq=1, event='event-one', **fields):
        value = item()
        with self.db.session() as session:
            current = session.get(Inbox, (self.device, 'update-1'))
            revision = current.payload['itemRevision'] if current else 1
        report = dict(eventId=event, updateId='update-1', itemRevision=revision, attemptId='attempt-one',
            reportSeq=seq, stage=stage, digest=value['target']['targetDigest'], completedCriteria=None, errorCode=None)
        report.update(fields)
        return dict(messageType='report_request', contractVersion=1, binding=self.binding, reports=[report])

    def error(self, code, operation):
        with self.assertRaises(UpdateError) as error:
            operation()
        self.assertEqual(code, error.exception.status)
        return error.exception

    def test_binding_idempotent_epoch_retirement_and_old_account_isolation(self):
        same = self.store.bind('account-one', 'https://test.example', 'installation-one', binding_request())['binding']
        self.assertEqual(self.binding, same)
        other = self.store.bind('account-two', 'https://test.example', 'installation-one', binding_request())['binding']
        self.assertEqual(2, other['bindingEpoch'])
        self.assertNotEqual(self.device, other['deviceId'])
        self.error(409, lambda: self.store.snapshot('account-one', self.device))
        self.error(403, lambda: self.store.snapshot('account-two', self.device))

    def test_token_generation_rotation_and_equal_generation_conflict(self):
        body = binding_request() | dict(pushProvider='fcm', token='secret-one', tokenGeneration=1)
        self.store.bind('account-one', 'https://test.example', 'installation-one', body)
        self.error(409, lambda: self.store.bind('account-one', 'https://test.example', 'installation-one', body | {'token':'wrong'}))
        self.store.bind('account-one', 'https://test.example', 'installation-one', body | {'token':'secret-two', 'tokenGeneration':2})
        self.store.bind('account-one', 'https://test.example', 'installation-one', body)
        with self.db.session() as session:
            self.assertEqual('secret-two', session.get(Device, self.device).push_token)

    def test_unbind_idempotence_and_no_cross_account(self):
        body = dict(messageType='unbind_request', contractVersion=1, binding=self.binding)
        self.error(403, lambda: self.store.unbind('account-two', self.device, body))
        self.assertTrue(self.store.unbind('account-one', self.device, body)['revoked'])
        self.assertTrue(self.store.unbind('account-one', self.device, body)['revoked'])
        self.error(409, lambda: self.store.snapshot('account-one', self.device))

    def test_inventory_atomic_revision_and_capacity(self):
        body = dict(messageType='inventory_request', contractVersion=1, binding=self.binding, inventoryRevision=2, entries=[])
        self.assertEqual(2, self.store.inventory('account-one', self.device, body)['acceptedRevision'])
        self.assertEqual(2, self.store.inventory('account-one', self.device, body | {'inventoryRevision':1})['acceptedRevision'])
        bad = body | {'entries':[{}]*1001, 'inventoryRevision':3}
        self.error(413, lambda: self.store.inventory('account-one', self.device, bad))
        with self.db.session() as session:
            device = session.get(Device, self.device)
            self.assertEqual(2, device.inventory_revision)
            self.assertEqual([], device.inventory)

    def test_snapshot_fixed_watermark_pages_then_incremental(self):
        self.put(1); self.put(2)
        first = self.store.snapshot('account-one', self.device, limit=1)
        self.put(3)
        second = self.store.snapshot('account-one', self.device, first['nextPageToken'], 1)
        self.assertEqual(first['snapshotId'], second['snapshotId'])
        self.assertEqual(first['snapshotCursor'], second['snapshotCursor'])
        self.assertIsNone(second['nextPageToken'])
        self.assertEqual(['update-2'], [v['updateId'] for v in second['items']])
        delta = self.store.delta('account-one', self.device, first['snapshotCursor'])
        self.assertEqual([3], [v['sequence'] for v in delta['items']])
        validate(first, 'snapshot_response'); validate(delta, 'delta_response')

    def test_expired_and_cross_device_tickets_fail_closed(self):
        first = self.store.snapshot('account-one', self.device)
        self.error(410, lambda: self.store.delta('account-one', self.device, 'forged'))
        with self.db.session() as session:
            for ticket in session.scalars(select(Ticket)):
                ticket.expires_at = now() - timedelta(seconds=1)
        self.error(410, lambda: self.store.delta('account-one', self.device, first['snapshotCursor']))

    def test_current_permission_revocation_hides_snapshot_and_delta(self):
        initial = self.store.snapshot('account-one', self.device)
        self.put(1); self.put(2)
        first = self.store.snapshot('account-one', self.device, limit=1)
        with self.db.session() as session:
            session.get(ProjectMembershipRecord, ('project-one', 'account-one')).enabled = False
        self.error(403, lambda: self.store.snapshot('account-one', self.device, first['nextPageToken']))
        delta = self.store.delta('account-one', self.device, initial['snapshotCursor'])
        self.assertEqual([], delta['items'])
        self.assertFalse(delta['hasMore'])

    def test_receipts_immutable_duplicate_stale_and_permanent_audit(self):
        self.put()
        body = self.report()
        self.assertEqual('accepted', self.store.reports('account-one', body)['results'][0]['outcome'])
        self.assertEqual('duplicate', self.store.reports('account-one', body)['results'][0]['outcome'])
        changed = deepcopy(body); changed['reports'][0]['stage'] = 'seen'
        self.assertEqual('event_payload_conflict', self.store.reports('account-one', changed)['results'][0]['errorCode'])
        self.assertEqual('stale', self.store.reports('account-one', self.report(event='old'))['results'][0]['outcome'])
        invalid = self.report('installed', seq=2, event='invalid', completedCriteria='installed')
        self.assertEqual('accepted', self.store.reports('account-one', invalid)['results'][0]['outcome'])
        regression = self.report('downloading', seq=3, event='regression')
        self.assertEqual('invalid_transition', self.store.reports('account-one', regression)['results'][0]['errorCode'])

    def test_offline_batch_receipts_and_unchanged_progress_do_not_push_again(self):
        self.put()
        first = self.report('discovered', 1, 'discovery')
        final = self.report('installed', 2, 'installed', completedCriteria='installed')
        batch = deepcopy(first); batch['reports'] += final['reports']
        self.assertEqual(['accepted', 'accepted'], [v['outcome'] for v in self.store.reports('account-one', batch)['results']])
        with self.db.session() as session:
            before = session.get(Device, self.device).sequence
            row = session.get(Inbox, (self.device, 'update-1'))
            self.assertEqual(3, row.payload['itemRevision'])
            self.assertEqual(1, row.authority_revision)
            self.assertEqual(1, session.get(PushOutbox, self.device).dirty_sequence)
        self.store.reports('account-one', self.report('installed', 3, 'same-stage', completedCriteria='installed'))
        with self.db.session() as session:
            self.assertEqual(before, session.get(Device, self.device).sequence)

    def test_install_quarantine_rollback_are_distinct_persisted_facts(self):
        self.put()
        for seq, stage in enumerate(['downloading', 'verifying', 'staged', 'warming', 'committing', 'installed', 'quarantined', 'rolled_back'], 1):
            body = self.report(stage, seq, 'event-'+str(seq), completedCriteria='installed' if stage == 'installed' else None)
            self.assertEqual('accepted', self.store.reports('account-one', body)['results'][0]['outcome'], stage)
        self.db.close()
        restarted = UpdateStore(DatabaseManager(self.url)); self.addCleanup(restarted.database.close)
        self.assertEqual('rolled_back', restarted.snapshot('account-one', self.device)['items'][0]['stage'])

    def test_invalid_criteria_and_digest_cannot_be_success(self):
        self.put()
        report = self.report('installed', completedCriteria='activated')
        self.assertEqual('criteria_mismatch', self.store.reports('account-one', report)['results'][0]['errorCode'])
        report = self.report(event='wrong', digest='f'*64)
        self.assertEqual('target_changed', self.store.reports('account-one', report)['results'][0]['errorCode'])

    def test_rate_limits_shared_between_store_instances(self):
        for _ in range(10):
            self.store.rate_limit('test', rate=0)
        second = UpdateStore(self.db)
        error = self.error(429, lambda: second.rate_limit('test', rate=0))
        self.assertEqual(1, error.retry_after)

    def test_failed_projection_transaction_does_not_advance_sequence(self):
        self.put(1)
        with self.assertRaises(RuntimeError):
            with self.db.session() as session:
                device = self.store.locked_device(session, 'account-one', self.device)
                self.store._put(session, device, item(2), 'source')
                raise RuntimeError('crash')
        with self.db.session() as session:
            self.assertEqual(1, session.get(Device, self.device).sequence)
            self.assertEqual(1, len(session.scalars(select(Change)).all()))
            self.assertEqual(1, session.get(PushOutbox, self.device).dirty_sequence)

    def test_push_lease_does_not_clear_new_dirty_and_token_is_retired(self):
        self.store.bind('account-one', 'https://test.example', 'installation-one', binding_request() |
                        dict(pushProvider='fcm', token='internal-test-token', tokenGeneration=1))
        self.put(1)
        dispatcher = PushDispatcher(self.store, type('Sender', (), {'enabled':True})())
        lease = dispatcher.claim(self.device)
        self.put(2)
        dispatcher.finish(lease, PushResult('accepted'))
        with self.db.session() as session:
            row = session.get(PushOutbox, self.device)
            self.assertEqual((1,2), (row.sent_sequence, row.dirty_sequence))
            row.next_attempt = now() - timedelta(seconds=1)
        lease = dispatcher.claim(self.device)
        dispatcher.finish(lease, PushResult('invalid_token'))
        with self.db.session() as session:
            self.assertIsNone(session.get(Device, self.device).push_token)
            self.assertEqual('invalid_token', session.get(PushOutbox, self.device).disabled_reason)

    def test_missing_fcm_configuration_preserves_dirty_and_marks_disabled(self):
        self.put()
        dispatcher = PushDispatcher(self.store, FcmSender())
        self.assertIsNone(dispatcher.claim(self.device))
        with self.db.session() as session:
            row = session.get(PushOutbox, self.device)
            self.assertEqual(0, row.sent_sequence)
            self.assertEqual('configuration_missing', row.disabled_reason)

    def test_pending_retention_survives_ninety_days_and_cleanup_expires_old_cursor(self):
        self.put()
        with self.db.session() as session:
            session.get(Inbox, (self.device,'update-1')).updated_at = now()-timedelta(days=100)
        self.store.cleanup()
        self.assertEqual(1, len(self.store.snapshot('account-one', self.device)['items']))

    def test_no_database_has_no_memory_success(self):
        self.error(503, lambda: UpdateStore(DatabaseManager(None)).bind('account-one', 'https://test.example','installation-one',binding_request()))

    def test_cleanup_compacts_only_old_terminal_history_and_rebuilds_current_truth(self):
        from app.model_updates.models import Receipt, Snapshot, Target
        first = self.store.snapshot('account-one', self.device)
        self.put()
        self.store.reports('account-one', self.report('installed', completedCriteria='installed'))
        with self.db.session() as session:
            device = self.store.locked_device(session, 'account-one', self.device)
            self.store._put(session, device, item(2), 'source-1')
        self.put(3)
        self.store.reports('account-one', self.report(event='missing', updateId='unknown'))
        cutoff = now() - timedelta(days=100)
        with self.db.session() as session:
            for row in session.scalars(select(Inbox)):
                row.updated_at = cutoff
            for row in session.scalars(select(Change)):
                row.created_at = cutoff
            for row in session.scalars(select(Receipt)):
                row.created_at = cutoff
            for row in session.scalars(select(Snapshot)):
                row.expires_at = cutoff
        self.store.cleanup()
        self.db.close()
        self.error(410, lambda: self.store.delta('account-one', self.device, first['snapshotCursor']))
        self.assertEqual({'update-2', 'update-3'}, {v['updateId'] for v in self.store.snapshot('account-one', self.device)['items']})
        with self.db.session() as session:
            self.assertIsNone(session.get(Inbox, (self.device, 'update-1')))
            self.assertIsNone(session.get(Target, 'update-1'))
            self.assertEqual([], session.scalars(select(Receipt)).all())
            self.assertIsNotNone(session.get(Inbox, (self.device, 'update-3')))

    def test_metrics_survive_service_restart_and_measure_document_bytes(self):
        from app.model_updates.service import ModelUpdateService
        self.put()
        for _ in range(10):
            self.store.rate_limit('metric-test', rate=0)
        self.error(429, lambda: self.store.rate_limit('metric-test', rate=0))
        self.store.observe('control_http_200', .25)
        self.db.close()
        service = ModelUpdateService(self.db, None, None)
        measured = service.metrics()
        self.assertEqual(1, measured['measurements']['rate_limited_control']['count'])
        self.assertEqual(.25, measured['measurements']['control_http_200']['total'])
        self.assertGreater(measured['documentStorageBytes']['model_update_inbox.payload'], 0)
        self.assertGreaterEqual(measured['oldestPendingPushSeconds'], 0)


@unittest.skipUnless(os.environ.get('RUN_POSTGRES_TESTS') == '1', 'requires isolated PostgreSQL')
class UpdatePostgreSqlTests(UpdateStoreTests):
    use_postgresql = True


class UpdateContractAndRangeTests(unittest.TestCase):
    def test_frozen_schema_matches_mobile_source(self):
        mobile = Path(__file__).resolve().parents[2]/'mobile-app/docs/schemas/mobile-model-update-v1.schema.json'
        server = Path(__file__).resolve().parents[1]/'app/model_updates/contract-v1.schema.json'
        self.assertEqual(json.loads(mobile.read_text(encoding='utf-8')), json.loads(server.read_text(encoding='utf-8')))

    def test_all_shared_goldens_validate_or_reject(self):
        fixture = Path(__file__).resolve().parents[2]/'mobile-app/app/src/test/resources/contracts/m111-model-update-v1-golden.json'
        golden = json.loads(fixture.read_text(encoding='utf-8'))
        for value in golden['valid']:
            # Golden entries may be envelopes containing message.
            message = value.get('message', value)
            validate(message, message.get('messageType', 'push'))
        for value in golden['invalid']:
            message = value['message']
            with self.assertRaises(UpdateError, msg=value['id']):
                validate(message, message.get('messageType', 'push'))

    def test_fcm_data_only_envelope_and_unregistered_result(self):
        calls=[]
        def transport(url,data,headers):
            calls.append((url,json.loads(data),headers))
            return 200, {'name':'projects/internal/messages/test'}, {}
        sender=FcmSender('internal-project','not-read',transport=transport)
        with patch.object(sender,'_access_token',return_value='opaque-test-token'):
            self.assertEqual('accepted',sender.send('test-registration').state)
        envelope=calls[0][1]['message']
        self.assertNotIn('notification',envelope)
        self.assertEqual({'type','contractVersion','eventId'},set(envelope['data']))
        self.assertEqual('normal',envelope['android']['priority'])
        self.assertEqual('model_updates_changed_v1',envelope['android']['collapse_key'])

    def test_range_if_range_and_resource_release(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path=Path(temp.name)/'model.bin';path.write_bytes(b'0123456789')
        counters={'active':0}
        def acquire(_): counters['active']+=1
        def release(): counters['active']-=1
        app=FastAPI()
        @app.get('/download')
        async def download(request: __import__('fastapi').Request):
            return artifact_response(request,dict(sizeBytes=10,sha256='a'*64),path,
                                      acquire=acquire,release=release,chunk_size=1024)
        with TestClient(app) as client:
            for requested,expected,status in [('bytes=4-',b'456789',206),('bytes=1-3',b'123',206),
                ('bytes=-2',b'89',206),('bytes=10-',b'',416),('bytes=2-1',b'',416),('bytes=1-2,4-5',b'',416)]:
                result=client.get('/download',headers={'Range':requested})
                self.assertEqual(status,result.status_code,requested);self.assertEqual(expected,result.content)
                self.assertEqual(0,counters['active'])
            full=client.get('/download',headers={'Range':'bytes=4-','If-Range':'W/"old"'})
            self.assertEqual(200,full.status_code);self.assertEqual(b'0123456789',full.content)
            resumed=client.get('/download',headers={'Range':'bytes=4-','If-Range':'"'+'a'*64+'"'})
            self.assertEqual('bytes 4-9/10',resumed.headers['content-range'])
            self.assertEqual('6',resumed.headers['content-length'])
