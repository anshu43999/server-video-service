"""M112 production projection/router + actual catalog/DB regressions, no oracle."""
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.database import ProjectMembershipRecord, ProjectRecord, ProjectSceneRecord
from app.auth import Principal
from app.model_updates.models import Device, Change, Receipt, Inbox, PushOutbox
from app.model_updates.protocol import digest, now, timestamp, validate
from app.model_updates.projection import Projection
from app.model_updates.store import UpdateStore
from app.model_updates.service import ModelUpdateService
from app.model_updates.api import create_router
import test_model_update_projection as fixtures
from test_model_updates import binding_request


class LifecycleTests(unittest.TestCase):
    error = fixtures.UpdateProjectionTests.error

    def setUp(self):
        fixtures.UpdateProjectionTests.setUp(self)
        request = binding_request()
        request['capabilities']['resourceLifecycleVersions'] = [1]
        bound = self.store.bind('account-one', 'https://test.example', 'installation-one', request)
        self.assertEqual(1, bound['resourceLifecycleVersion'])
        self.binding, self.device = bound['binding'], bound['binding']['deviceId']

    def entry(self, ident='retained-model', model='ppe', target='mobile', source=None):
        artifact = next(a for a in self.catalog.get(model, '1.0.0')['artifacts']
                        if a.get('platform') == ('android' if target == 'mobile' else 'server'))
        return dict(inventoryEntryId=ident, sourceEpoch=1, localRetentionState='retained',
                    resourceKey=dict(kind='model_release', projectId='project-one', target=target,
                        modelId=model, version='1.0.0', artifactId=artifact['artifactId'],
                        artifactSha256=artifact['sha256'].lower(),
                        grantSource=source or dict(kind='standalone', assignmentId=self.saved['assignmentId'])))

    def upload(self, entries, revision=1, updates=None):
        return self.store.inventory('account-one', self.device, dict(messageType='inventory_request', contractVersion=1,
            binding=self.binding, inventoryRevision=revision, entries=updates or [], lifecycleEntries=entries))

    def snapshot(self, limit=100):
        page = self.store.snapshot('account-one', self.device, limit=limit)
        result, indices, cursor = [], [], page['snapshotCursor']
        while True:
            covered = page['lifecycleSnapshot']; validate(covered, 'lifecycle_snapshotPage')
            result.extend(covered['items']); indices.append(covered['pageIndex'])
            self.assertEqual(len(result), covered['coveredCount'])
            self.assertEqual(cursor, covered['snapshotCursor'])
            if page['nextPageToken'] is None:
                self.assertEqual(len(result), covered['inventoryCount']); break
            page = self.store.snapshot('account-one', self.device, page['nextPageToken'], limit)
        self.assertEqual(list(range(len(indices))), indices)
        self.assertEqual(len(result), len({fact['inventoryEntryId'] for fact in result}))
        return result, cursor

    def facts(self):
        return self.snapshot()[0]

    def project(self):
        self.assertTrue(self.projection.one(self.device))

    def report(self, fact, stage='discovered', seq=1, event='life-report', **fields):
        report = dict(reportKind='resource_lifecycle', eventId=event, binding=deepcopy(fact['binding']),
            inventoryEntryId=fact['inventoryEntryId'], sourceEpoch=fact['sourceEpoch'], reportSeq=seq,
            stage=stage, lifecycleItemId=fact['lifecycleItemId'], lifecycleRevision=fact['lifecycleRevision'])
        report.update(fields)
        return dict(messageType='report_request', contractVersion=1, binding=self.binding, reports=[report])

    def test_no_update_needed_none_and_notifications_denied(self):
        self.upload([self.entry()]); self.project(); fact = self.facts()[0]
        self.assertEqual('current', fact['result']['reasonCode']); self.assertNotIn('updateId', fact)
        with self.db.session() as s:
            self.assertEqual(1, len(s.scalars(select(Change).where(Change.update_id.is_(None))).all()))
            self.assertEqual('none', s.get(Device, self.device).push_provider)
            self.assertEqual(s.get(Device, self.device).sequence, s.get(PushOutbox, self.device).dirty_sequence)
            self.assertFalse(any(r.payload['kind'] == 'update_ready' for r in s.scalars(select(Inbox))))

    def test_revocation_delta_and_noop_revision(self):
        self.upload([self.entry()]); self.project(); before, cursor = self.snapshot()
        self.project(); self.assertEqual(before, self.facts())
        self.assignments.save('project-one', 'ppe', '1.0.0', 'mobile', 0, False, 1); self.project()
        delta = self.store.delta('account-one', self.device, cursor)
        fact = next(r['item'] for r in delta['items'] if r['operation'] == 'lifecycle')
        self.assertEqual('project_grant_removed', fact['result']['reasonCode'])
        self.assertEqual(2, fact['lifecycleRevision'])

    def test_unknown_legacy_and_registry_absence(self):
        known = self.entry(); known['resourceKey']['version'] = 'missing'
        unknown = dict(inventoryEntryId='legacy', sourceEpoch=0, localRetentionState='unknown_legacy', resourceKey=None)
        self.upload([known, unknown]); self.project()
        for fact in self.facts():
            self.assertEqual('unknown', fact['result']['reasonCode']); self.assertIsNone(fact['result']['confirmedAt'])

    def test_exact_snapshot_coverage_staging_and_update_pages(self):
        entries = [self.entry('resource-' + str(i)) for i in range(7)]; entries[0]['localRetentionState'] = 'staging'
        self.upload(entries, updates=[fixtures.UpdateProjectionTests.entry(self)]); self.project()
        facts, _ = self.snapshot(limit=2)
        self.assertEqual({e['inventoryEntryId'] for e in entries}, {f['inventoryEntryId'] for f in facts})

    def test_inventory_revision_change_and_snapshot_expiration(self):
        entries = [self.entry('one'), self.entry('two')]; self.upload(entries); self.project()
        first = self.store.snapshot('account-one', self.device, limit=1); self.upload(entries, 2)
        self.error(410, lambda: self.store.snapshot('account-one', self.device, first['nextPageToken']))
        self.project(); second = self.store.snapshot('account-one', self.device, limit=1)
        with patch('app.model_updates.store.now', return_value=now() + timedelta(minutes=11)):
            self.error(410, lambda: self.store.snapshot('account-one', self.device, second['nextPageToken']))

    def test_inventory_reupload_changes_envelope_only(self):
        self.upload([self.entry()]); self.project(); first, cursor = self.snapshot()
        self.upload([self.entry()], 2); self.project(); second, _ = self.snapshot()
        self.assertEqual(first[0]['lifecycleRevision'], second[0]['lifecycleRevision'])
        self.assertEqual(first[0]['result'], second[0]['result']); self.assertEqual(2, second[0]['inventoryRevision'])
        self.error(410, lambda: self.store.delta('account-one', self.device, cursor))

    def test_permission_change_no_old_details_before_scan(self):
        self.upload([self.entry('one'), self.entry('two')]); self.project()
        first = self.store.snapshot('account-one', self.device, limit=1)
        with self.db.session() as s: s.get(ProjectMembershipRecord, ('project-one', 'account-one')).enabled = False
        self.error(410, lambda: self.store.snapshot('account-one', self.device, first['nextPageToken']))
        self.project()
        for fact in self.facts():
            self.assertEqual(dict(visibility='opaque', authorizationState='denied', reasonCode='scope_inaccessible'), fact['result'])
            self.assertNotIn('project-one', json.dumps(fact))
        self.error(403, lambda: self.store.snapshot('account-two', self.device))

    def test_epoch_retirement_and_changed_identity_atomic_rejection(self):
        entry = self.entry(); self.upload([entry]); self.project(); self.upload([], 2)
        self.error(409, lambda: self.upload([entry], 3))
        entry['sourceEpoch'] = 2; self.upload([entry], 3); self.project()
        wrong = deepcopy(entry); wrong['resourceKey']['version'] = '2.0.0'
        self.error(409, lambda: self.upload([wrong], 4)); self.error(409, lambda: self.upload([entry], 2))
        self.assertEqual(3, self.facts()[0]['inventoryRevision'])

    def test_old_binding_and_inner_report_binding(self):
        self.upload([self.entry()]); self.project(); body = self.report(self.facts()[0])
        body['reports'][0]['binding']['bindingEpoch'] = 2
        self.assertEqual('rejected', self.store.reports('account-one', body)['results'][0]['outcome'])
        self.store.bind('account-two', 'https://test.example', 'installation-one', binding_request())
        self.error(409, lambda: self.store.snapshot('account-one', self.device))

    def test_receipts_without_update_id_idempotency_and_stage_order(self):
        self.upload([self.entry()]); self.project(); fact = self.facts()[0]; body = self.report(fact)
        send = lambda b: self.store.reports('account-one', b)['results'][0]
        self.assertEqual('accepted', send(body)['outcome']); self.assertEqual('duplicate', send(body)['outcome'])
        conflict = deepcopy(body); conflict['reports'][0]['reportSeq'] = 2
        self.assertEqual('event_payload_conflict', send(conflict)['errorCode'])
        self.assertEqual('accepted', send(self.report(fact, 'files_cleaned', 2, 'cleaned', freedBytes=12))['outcome'])
        self.assertEqual('stale', send(self.report(fact, seq=3, event='late'))['outcome'])
        with self.db.session() as s: self.assertTrue(all(r.update_id is None for r in s.scalars(select(Receipt))))
        invalid = self.report(fact); invalid['reports'][0]['updateId'] = 'fake'
        self.error(400, lambda: send(invalid))

    def test_413_and_429_preserve_inventory(self):
        self.upload([self.entry()]); self.project(); original = self.facts()
        entry = self.entry(); entries = [dict(entry, inventoryEntryId='entry-' + str(i)) for i in range(1001)]
        self.error(413, lambda: self.upload(entries, 2)); self.assertEqual(original, self.facts())
        for _ in range(10): self.store.rate_limit(self.device)
        self.assertEqual(1, self.error(429, lambda: self.store.rate_limit(self.device)).retry_after)
        self.assertEqual(original, self.facts())

    def test_legacy_client_payload_and_unnegotiated_inventory(self):
        self.store.bind('account-one', 'https://test.example', 'installation-one', binding_request())
        self.error(409, lambda: self.upload([self.entry()]))
        self.assertNotIn('lifecycleSnapshot', self.store.snapshot('account-one', self.device))

    def remove_release(self):
        self.catalog.uninstall('ppe', '1.0.0', operation_id='test-removal')

    def test_incomplete_legacy_tombstone_is_unknown(self):
        entry = self.entry(); registry = self.catalog._load()
        registry['models'] = [m for m in registry['models'] if (m['modelId'], m['version']) != ('ppe', '1.0.0')]
        registry.setdefault('modelHistory', []).append(dict(modelId='ppe', version='1.0.0', status='UNINSTALLED'))
        self.catalog._save(registry); self.upload([entry]); self.project()
        self.assertEqual('unknown', self.facts()[0]['result']['reasonCode'])

    def test_90_day_compaction_restart_and_fresh_binding_rebuild_terminal(self):
        self.upload([self.entry()]); self.project(); _, cursor = self.snapshot(); saved_entry = self.entry()
        self.remove_release(); self.project(); removed = self.facts()[0]
        self.assertEqual('release_removed', removed['result']['reasonCode'])
        with patch('app.model_updates.store.now', return_value=now() + timedelta(days=91)):
            self.store.cleanup(); self.error(410, lambda: self.store.delta('account-one', self.device, cursor))
        self.db.close(); self.store = UpdateStore(self.db); self.projection = Projection(self.store, self.catalog, self.scenes)
        self.project(); self.assertEqual(removed['result'], self.facts()[0]['result'])
        request = binding_request('fresh-install'); request['capabilities']['resourceLifecycleVersions'] = [1]
        self.binding = self.store.bind('account-one', 'https://test.example', 'fresh-install', request)['binding']
        self.device = self.binding['deviceId']; self.upload([saved_entry]); self.project()
        self.assertEqual('release_removed', self.facts()[0]['result']['reasonCode'])

    def test_deleted_release_with_m111_retained_inventory_does_not_rollback_lifecycle(self):
        self.upload([self.entry()], updates=[fixtures.UpdateProjectionTests.entry(self)])
        self.project(); self.remove_release(); self.project()
        self.assertEqual('release_removed', self.facts()[0]['result']['reasonCode'])

    def test_projection_failure_rolls_back_sequence_and_facts(self):
        self.upload([self.entry()])
        with patch.object(self.store, '_dirty_lifecycle', side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError): self.projection.one(self.device)
        with self.db.session() as s:
            self.assertEqual({}, s.get(Device, self.device).lifecycle_facts); self.assertEqual(0, s.get(Device, self.device).sequence)
        self.project(); self.assertEqual('current', self.facts()[0]['result']['reasonCode'])

    def suite_entries(self, multiple_plans=False):
        members = [dict(memberId='ppe-member', projectModelId=self.saved['projectModelId'],
                        position=0, execution='single', inputTypes=['image'])]
        plan = dict(planId='photo', name='Photo', memberIds=['ppe-member'], execution='single',
                    inputTypes=['image'], enabled=True)
        plans = [plan] + ([dict(plan, planId='photo-two', name='Photo two')] if multiple_plans else [])
        self.scenes.save('project-one', 'suite', dict(sceneId='suite', name='isolated', inputTypes=['image'],
            enabled=True, models=members, plans=plans), 0, creating=True)
        self.scenes.save('project-one', 'suite', dict(approved=True), 1, approval_reason='internal test')
        selection = digest(dict(planIds=sorted(p['planId'] for p in plans), memberIds=['ppe-member']))
        source = dict(kind='suite', sceneId='suite', sceneRevision=2, planId='photo', selectionDigest=selection)
        scene = dict(inventoryEntryId='scene', sourceEpoch=1, localRetentionState='retained',
            resourceKey=dict(kind='scene_revision', projectId='project-one', target='mobile', sceneId='suite',
                incarnation='suite', sceneRevision=2, selectionDigest=selection, grantSource=source))
        model = self.entry('member', source=dict(source, memberId='ppe-member'))
        return [scene, model]

    def test_multi_plan_selection_reuses_m111_inventory_without_update_id(self):
        entries = self.suite_entries(multiple_plans=True)
        selection = dict(planIds=['photo', 'photo-two'], memberIds=['ppe-member'])
        update_entry = fixtures.UpdateProjectionTests.entry(self)
        update_entry['source'] = dict(projectId='project-one', kind='scene', sceneId='suite', platform='mobile',
            sourceEpoch=1, selection=selection, selectionDigest=digest(selection))
        update_entry['retainedRevision'] = 2
        self.upload(entries, updates=[update_entry]); self.project()
        self.assertTrue(all(f['result']['reasonCode'] == 'current' for f in self.facts()))
        self.upload(entries, 2); self.project()
        self.assertTrue(all(f['result']['reasonCode'] == 'unknown' for f in self.facts()))

    def test_scene_disable_remove_and_shared_standalone_scope(self):
        entries = self.suite_entries() + [self.entry('standalone')]
        self.upload(entries); self.project()
        self.assertTrue(all(f['result']['reasonCode'] == 'current' for f in self.facts()))
        self.scenes.save('project-one', 'suite', dict(enabled=False), 2); self.project()
        reasons = {f['inventoryEntryId']: f['result']['reasonCode'] for f in self.facts()}
        self.assertEqual(dict(scene='scene_disabled', member='project_grant_removed', standalone='current'), reasons)
        context = SimpleNamespace(project_id='project-one', project_role='PROJECT_OWNER',
                                  principal=Principal('account-one', 'one', 'operator', 'NORMAL_USER'))
        with self.db.session() as s:
            s.get(ProjectMembershipRecord, ('project-one', 'account-one')).project_role = 'PROJECT_OWNER'
        self.scenes.soft_delete('project-one', 'suite', 3, 'remove-suite', context=context)
        self.project()
        self.assertEqual('scene_removed', next(f for f in self.facts() if f['inventoryEntryId'] == 'scene')['result']['reasonCode'])

    def test_terminal_and_confirmed_denial_never_resurrect_from_unknown_or_registry_restore(self):
        entry = self.entry(); original_registry = self.catalog._load()
        raw_release = next(row for row in original_registry['models'] if row['modelId'] == 'ppe' and row['version'] == '1.0.0')
        original_files = {path: path.read_bytes() for path in self.catalog._model_paths(raw_release) if path.is_file()}
        self.upload([entry]); self.project(); self.remove_release(); self.project(); removed = self.facts()[0]
        # Corrupt external restoration must not resurrect the retired identity.
        # Fault injection deliberately bypasses the catalog's own identity guard.
        self.registry.write_text(json.dumps(original_registry), encoding='utf-8')
        for path, payload in original_files.items():
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(payload)
        self.project(); self.assertEqual(removed, self.facts()[0])
        self.upload([entry, self.entry('another')], 2); self.project()
        self.assignments.save('project-one', 'ppe', '1.0.0', 'mobile', 0, False, 1); self.project()
        denied = next(f for f in self.facts() if f['inventoryEntryId'] == 'another')
        registry = self.catalog._load(); registry['models'] = [m for m in registry['models'] if m['modelId'] != 'ppe']
        self.catalog._save(registry); self.project()
        self.assertEqual(denied['result'], next(f for f in self.facts() if f['inventoryEntryId'] == 'another')['result'])

    def test_pc_mobile_exact_assignments_are_independent(self):
        pc = self.assignments.save('project-one', 'ppe', '1.0.0', 'pc', 0, True, 0)
        entries = [self.entry('mobile'), self.entry('pc', target='pc', source=dict(kind='standalone', assignmentId=pc['assignmentId']))]
        self.upload(entries); self.project()
        self.assertTrue(all(f['result']['reasonCode'] == 'current' for f in self.facts()))
        self.assignments.save('project-one', 'ppe', '1.0.0', 'mobile', 0, False, 1); self.project()
        self.assertEqual(dict(mobile='project_grant_removed', pc='current'),
                         {f['inventoryEntryId']: f['result']['reasonCode'] for f in self.facts()})

    def test_older_available_delta_rejected_after_revocation(self):
        self.upload([]); self.project(); _, cursor = self.snapshot()
        self.upload([self.entry()], 2); self.project()
        # Cursor with the current inventory but before the first lifecycle change.
        with self.db.session() as s:
            d = self.store.locked_device(s, 'account-one', self.device)
            cursor = self.store.ticket(s, d, 'cursor', dict(sequence=0))
        self.assignments.save('project-one', 'ppe', '1.0.0', 'mobile', 0, False, 1); self.project()
        self.error(410, lambda: self.store.delta('account-one', self.device, cursor))

    def test_schema_golden_and_invalid_reports_use_frozen_m112_definitions(self):
        golden = json.loads((Path(__file__).resolve().parents[2] /
            'mobile-app/app/src/test/resources/contracts/m112-lifecycle-v1-golden.json').read_text(encoding='utf-8'))
        for entry in golden['entries']:
            validate(entry, 'lifecycle_inventoryEntry')
        for fact in golden['facts'].values():
            validate(fact, 'lifecycle_fact')
        self.upload([self.entry()]); self.project(); fact = self.facts()[0]
        body = self.report(fact); body['reports'][0]['freedBytes'] = 2
        self.error(400, lambda: self.store.reports('account-one', body))
        body = self.report(fact); body['reports'][0].pop('lifecycleRevision')
        self.error(400, lambda: self.store.reports('account-one', body))

    def test_two_accounts_projects_devices_keep_facts_and_receipts_isolated(self):
        with self.db.session() as s:
            s.add(ProjectRecord(project_id='project-two', project_code='test-two', display_name='second', lifecycle_state='ACTIVE'))
            s.flush()
            s.add(ProjectMembershipRecord(project_id='project-two', account_id='account-two', project_role='PROJECT_USER', enabled=True))
        saved = self.assignments.save('project-two', 'ppe', '1.0.0', 'mobile', 0, True, 0)
        request = binding_request('installation-two'); request['capabilities']['resourceLifecycleVersions'] = [1]
        second = self.store.bind('account-two', 'https://test.example', 'installation-two', request)['binding']
        entry = self.entry(); other = deepcopy(entry)
        other['resourceKey'].update(projectId='project-two', grantSource=dict(kind='standalone', assignmentId=saved['assignmentId']))
        self.upload([entry]); self.project()
        self.store.inventory('account-two', second['deviceId'], dict(messageType='inventory_request', contractVersion=1,
            binding=second, inventoryRevision=1, entries=[], lifecycleEntries=[other]))
        self.assertTrue(self.projection.one(second['deviceId']))
        first, cursor = self.snapshot()
        second_page = self.store.snapshot('account-two', second['deviceId'])
        second_fact = second_page['lifecycleSnapshot']['items'][0]
        self.assertNotEqual(first[0]['lifecycleItemId'], second_fact['lifecycleItemId'])
        self.error(410, lambda: self.store.delta('account-two', second['deviceId'], cursor))
        self.error(403, lambda: self.store.snapshot('account-one', second['deviceId']))
        with self.db.session() as s:
            s.get(ProjectMembershipRecord, ('project-one', 'account-one')).enabled = False
        self.project(); self.assertTrue(self.projection.one(second['deviceId']))
        self.assertEqual('opaque', self.facts()[0]['result']['visibility'])
        self.assertEqual(second_fact, self.store.snapshot('account-two', second['deviceId'])['lifecycleSnapshot']['items'][0])
        wrong = self.report(second_fact)
        self.assertEqual('rejected', self.store.reports('account-one', wrong)['results'][0]['outcome'])

    def http_client(self):
        service = ModelUpdateService(self.db, self.catalog, self.scenes)
        self.store, self.projection = service.store, service.projection
        app = FastAPI(); app.include_router(create_router(lambda: service))
        client = TestClient(app, base_url='https://test.example'); self.addCleanup(client.close)
        auth = patch('app.model_updates.api.auth.authenticate', return_value=Principal('account-one', 'one', 'operator', 'NORMAL_USER'))
        auth.start(); self.addCleanup(auth.stop)
        return client

    def test_http_negotiation_inventory_pages_delta_and_receipts(self):
        client = self.http_client(); request = binding_request()
        request['capabilities']['resourceLifecycleVersions'] = [1]
        bound = client.put('/aiyoloapi/mobile/model-update-devices/installation-one', json=request)
        self.assertEqual(200, bound.status_code, bound.text)
        self.assertEqual(1, bound.json()['resourceLifecycleVersion'])
        inventory = dict(messageType='inventory_request', contractVersion=1, binding=self.binding,
            inventoryRevision=1, entries=[], lifecycleEntries=[self.entry('one'), self.entry('two')])
        path = '/aiyoloapi/mobile/model-update-devices/' + self.device + '/inventory'
        uploaded = client.put(path, json=inventory); self.assertEqual(200, uploaded.status_code, uploaded.text)
        self.project()
        params = dict(deviceId=self.device, limit=1)
        first = client.get('/aiyoloapi/mobile/model-updates/snapshot', params=params)
        self.assertEqual(200, first.status_code, first.text)
        page = first.json(); validate(page, 'snapshot_response')
        pages = [page]
        while pages[-1]['nextPageToken'] is not None:
            following = client.get('/aiyoloapi/mobile/model-updates/snapshot', params=params | dict(pageToken=pages[-1]['nextPageToken']))
            self.assertEqual(200, following.status_code, following.text); pages.append(following.json())
        self.assertEqual(2, pages[-1]['lifecycleSnapshot']['coveredCount'])
        fact = next(f for p in pages for f in p['lifecycleSnapshot']['items'])
        receipt = client.post('/aiyoloapi/mobile/model-update-reports', json=self.report(fact))
        self.assertEqual(200, receipt.status_code, receipt.text)
        self.assertEqual('accepted', receipt.json()['results'][0]['outcome'])
        self.assignments.save('project-one', 'ppe', '1.0.0', 'mobile', 0, False, 1); self.project()
        delta = client.get('/aiyoloapi/mobile/model-updates', params=dict(deviceId=self.device, cursor=page['snapshotCursor']))
        self.assertEqual(200, delta.status_code, delta.text); validate(delta.json(), 'delta_response')
        self.assertEqual({'project_grant_removed'}, {c['item']['result']['reasonCode'] for c in delta.json()['items']})

    def test_http_capacity_and_rate_limit_preserve_last_inventory(self):
        client = self.http_client(); self.upload([self.entry()]); self.project()
        body = dict(messageType='inventory_request', contractVersion=1, binding=self.binding, inventoryRevision=2,
            entries=[], lifecycleEntries=[self.entry('entry-' + str(i)) for i in range(1001)])
        response = client.put('/aiyoloapi/mobile/model-update-devices/' + self.device + '/inventory', json=body)
        self.assertEqual(413, response.status_code, response.text)
        for _ in range(9): self.store.rate_limit(self.device, rate=0)
        response = client.get('/aiyoloapi/mobile/model-updates/snapshot', params=dict(deviceId=self.device))
        self.assertEqual(429, response.status_code, response.text); self.assertEqual('1', response.headers['retry-after'])
        with self.db.session() as s:
            self.assertEqual(1, s.get(Device, self.device).inventory_revision)


@unittest.skipUnless(os.environ.get('RUN_POSTGRES_TESTS') == '1', 'requires isolated PostgreSQL')
class LifecyclePostgreSqlTests(LifecycleTests):
    use_postgresql = True

    def test_actual_postgresql_restart_retains_inventory_and_fact(self):
        data = os.environ.get('M112_POSTGRES_TEST_DATA_DIR')
        if not data: self.skipTest('runner-owned instance required for actual restart')
        expected = Path(data).resolve()
        self.assertEqual(Path(__file__).resolve().parents[1] / '.tmp', expected.parent.parent)
        self.assertTrue(expected.parent.name.startswith('m112-sync-'))
        with self.db.session() as s:
            self.assertEqual(expected, Path(s.scalar(text('SHOW data_directory'))).resolve())
        self.upload([self.entry()]); self.project(); self.remove_release(); self.project(); before = self.facts()[0]
        self.db.close()
        # Windows descendants may inherit an otherwise-unused pipe handle even
        # when postgres redirects its own output. A file has no EOF wait.
        with (expected.parent / 'restart.log').open('ab') as log:
            subprocess.run([r'D:\PostgreSQL\bin\pg_ctl.exe', '-D', str(expected),
                            '-l', str(expected.parent / 'postgres.log'), '-m', 'fast', '-w', 'restart'],
                           check=True, timeout=60, stdout=log, stderr=log)
        self.store = UpdateStore(self.db); self.projection = Projection(self.store, self.catalog, self.scenes)
        self.project(); self.assertEqual(before, self.facts()[0])
