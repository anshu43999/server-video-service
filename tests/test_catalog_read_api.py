import asyncio
import json
import os
import threading
import unittest
from dataclasses import replace
from unittest.mock import patch

import httpx
import app.auth as auth
import app.main as main
from app.catalog_reads import CatalogReads
from app.project_auth import set_memory_membership, set_memory_project
from test_catalog_reads import until
from test_project_model_assignments import ModelApiFixture


class CatalogReadApiTests(ModelApiFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.reader = CatalogReads()
        self.addCleanup(self.reader.close)
        self.patches.enter_context(patch.object(main, 'catalog_reads', self.reader))

    def test_list_routes_preserve_contract_and_cross_project_isolation(self):
        self.assertEqual(200, self._assign().status_code)
        platform = self.client.get('/aiyoloapi/models', headers=self.headers)
        self.assertEqual(200, platform.status_code)
        self.assertEqual(json.loads(json.dumps(main.model_catalog.list_models())), platform.json()['models'])
        for route in (self.project_path + '/models', '/aiyoloapi/models'):
            headers = dict(self.user, **{'X-Project-Id': self.project_id})
            response = self.client.get(route, headers=headers)
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual(['helmet'], [m['modelId'] for m in response.json()['models']])
            self.assertEqual(['1.0.0'], response.json()['models'][0]['availableVersions'])
        other = self.client.get('/aiyoloapi/projects/' + self.other_id + '/models', headers=self.headers)
        self.assertEqual({'models': []}, other.json())
        denied = self.client.get('/aiyoloapi/projects/' + self.other_id + '/models', headers=self.user)
        self.assertEqual(404, denied.status_code)
        self.assertEqual(403, self.client.get(self.project_path + '/models/available', headers=self.user).status_code)
        self.assertEqual(200, self.client.get(self.project_path + '/models/available', headers=self.owner).status_code)

    def test_real_file_is_rehashed_after_same_size_tamper_and_missing_file(self):
        route = '/aiyoloapi/models'
        original = self.client.get(route, headers=self.headers).json()['models'][0]
        self.assertTrue(original['hashValid'])
        path = main.model_catalog.project_root / self.entries[0]['path']
        path.write_bytes(b'x' * path.stat().st_size)
        changed = self.client.get(route, headers=self.headers).json()['models'][0]
        self.assertFalse(changed['hashValid']); self.assertFalse(changed['serverReady'])
        path.unlink()
        missing = self.client.get(route, headers=self.headers).json()['models'][0]
        self.assertFalse(missing['exists']); self.assertFalse(missing['hashValid'])

    def test_assignment_guard_does_not_hash_or_change_public_display_fields(self):
        self.assertEqual(200, self._assign().status_code)
        with patch.object(main.model_catalog, 'get', wraps=main.model_catalog.get) as inspect:
            snapshot = main.project_model_assignments.list(self.project_id, include_display=False)
            self.assertEqual(1, len(snapshot))
            self.assertNotIn('modelName', snapshot[0])
            inspect.assert_not_called()
            display = main.project_model_assignments.list(self.project_id)
            self.assertEqual('helmet', display[0]['modelName'])
            inspect.assert_called_once()

    def test_each_list_request_hashes_each_file_once_without_cross_request_reuse(self):
        self.assertEqual(200, self._assign().status_code)
        routes = [('/aiyoloapi/models', self.headers, 6),
                  (self.project_path + '/models', self.user, 2),
                  ('/aiyoloapi/models', dict(self.user, **{'X-Project-Id': self.project_id}), 2),
                  (self.project_path + '/models/available', self.owner, 6)]
        for route, headers, expected in routes:
            with self.subTest(route=route, project=bool(headers.get('X-Project-Id'))):
                original = main.model_catalog.sha256
                with patch.object(main.model_catalog, 'sha256', wraps=original) as compute:
                    for request_count in (1, 2):
                        response = self.client.get(route, headers=headers)
                        self.assertEqual(200, response.status_code, response.text)
                        self.assertEqual(expected * request_count, compute.call_count)

    def test_changed_file_after_list_computed_returns_conflict_not_old_success(self):
        def tamper():
            path = main.model_catalog.project_root / self.entries[0]['path']
            info = path.stat()
            path.write_bytes(b'x' * info.st_size)
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        self._during_read('/aiyoloapi/models', self.headers, tamper, 409, 'catalog_changed')

    def test_deleted_file_after_list_computed_returns_conflict(self):
        self._during_read('/aiyoloapi/models', self.headers,
            lambda: (main.model_catalog.project_root / self.entries[0]['path']).unlink(),
            409, 'catalog_changed')

    def test_list_digest_does_not_make_later_download_or_activation_trust_tampered_file(self):
        response = self.client.get('/aiyoloapi/models', headers=self.headers)
        self.assertEqual(200, response.status_code)
        model = next(row for row in response.json()['models'] if row['modelId'] == 'secret')
        artifact = next(row for row in model['artifacts'] if row['platform'] == 'server')
        path = main.model_catalog.project_root / self.entries[2]['path']
        info = path.stat()
        path.write_bytes(b'x' * info.st_size)
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        downloaded = self.client.get(artifact['versionedUrl'], headers=self.headers)
        self.assertEqual(409, downloaded.status_code, downloaded.text)
        activated = self.client.post('/aiyoloapi/models/secret/activate', headers=self.headers)
        self.assertEqual(409, activated.status_code, activated.text)

    def test_parallel_reads_reject_overflow_and_unrelated_auth_remains_responsive(self):
        async def scenario():
            release = threading.Event()
            entered = 0
            lock = threading.Lock()
            original = main.model_catalog.list_models
            def held():
                nonlocal entered
                with lock: entered += 1
                release.wait(3)
                return original()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://fixture') as client:
                with patch.object(main.model_catalog, 'list_models', held):
                    tasks = [asyncio.create_task(client.get('/aiyoloapi/models', headers=self.headers)) for _ in range(2)]
                    try:
                        await until(lambda: entered == 2)
                        response = await asyncio.wait_for(client.get('/aiyoloapi/models', headers=self.headers), 1)
                        self.assertEqual(503, response.status_code)
                        self.assertEqual('catalog_busy', response.json()['detail']['code'])
                        self.assertEqual('1', response.headers['retry-after'])
                        self.assertEqual(200, (await asyncio.wait_for(client.get('/aiyoloapi/auth/status'), 1)).status_code)
                        self.assertEqual(2, entered)
                    finally:
                        release.set()
                        responses = await asyncio.gather(*tasks)
                    self.assertTrue(all(r.status_code == 200 for r in responses))
        asyncio.run(scenario())

    def _during_read(self, route, headers, change, expected, code=None, operation='list_models'):
        async def scenario():
            release, started = threading.Event(), threading.Event()
            original = getattr(main.model_catalog, operation)
            def held(*args, **kwargs):
                result = original(*args, **kwargs)
                started.set(); release.wait(3)
                return result
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://fixture') as client:
                with patch.object(main.model_catalog, operation, held):
                    task = asyncio.create_task(client.get(route, headers=headers))
                    try:
                        await until(started.is_set)
                        change()
                    finally:
                        release.set()
                    response = await task
                    self.assertEqual(expected, response.status_code, response.text)
                    self.assertNotIn('models', response.json())
                    if code: self.assertEqual(code, response.json()['detail']['code'])
        asyncio.run(scenario())

    def test_logout_during_inspection_discards_private_result(self):
        self._during_read('/aiyoloapi/models', self.headers, lambda: auth._memory_sessions.clear(), 401)

    def test_platform_demotion_during_inspection_discards_result(self):
        def demote():
            key = next(key for key, account in auth._memory_accounts.items() if account.account_id == self.account_id)
            auth._memory_accounts[key] = replace(auth._memory_accounts[key], platform_role='NORMAL_USER')
        self._during_read('/aiyoloapi/models', self.headers, demote, 403)

    def test_membership_removal_during_project_read_discards_result(self):
        self.assertEqual(200, self._assign().status_code)
        user_id = self.client.get('/aiyoloapi/auth/me', headers=self.user).json()['accountId']
        self._during_read(self.project_path + '/models', self.user,
            lambda: set_memory_membership(self.project_id, user_id, 'PROJECT_USER', enabled=False, revision=2), 404, operation='get')

    def test_owner_demotion_during_available_read_discards_selection(self):
        owner_id = self.client.get('/aiyoloapi/auth/me', headers=self.owner).json()['accountId']
        self._during_read(self.project_path + '/models/available', self.owner,
            lambda: set_memory_membership(self.project_id, owner_id, 'PROJECT_USER', revision=2), 403)

    def test_project_revision_change_during_read_discards_projection(self):
        self.assertEqual(200, self._assign().status_code)
        self._during_read(self.project_path + '/models', self.user,
            lambda: set_memory_project(self.project_id, 'model-assignment', revision=2), 403, operation='get')

    def test_cancelled_http_waiter_never_returns_late_catalog_or_frees_worker_early(self):
        async def scenario():
            self.reader.close()
            reader = CatalogReads(workers=1)
            release, started = threading.Event(), threading.Event()
            def held():
                started.set(); release.wait(3)
                return []
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://fixture') as client:
                with patch.object(main, 'catalog_reads', reader), patch.object(main.model_catalog, 'list_models', held):
                    task = asyncio.create_task(client.get('/aiyoloapi/models', headers=self.headers))
                    try:
                        await until(started.is_set)
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                        response = await client.get('/aiyoloapi/models', headers=self.headers)
                        self.assertEqual(503, response.status_code)
                        self.assertEqual('catalog_busy', response.json()['detail']['code'])
                    finally:
                        release.set()
                        await asyncio.to_thread(reader._executor.shutdown, wait=True)
                        reader.close()
        asyncio.run(scenario())

    def test_assignment_change_during_project_read_rejects_old_projection(self):
        self.assertEqual(200, self._assign().status_code)
        from app.project_business import _memory_model_assignments
        self._during_read(self.project_path + '/models', self.user,
            lambda: _memory_model_assignments.clear(), 409, 'catalog_changed', operation='get')

    def test_registry_change_during_read_rejects_old_snapshot(self):
        def change():
            path = main.model_catalog.registry_path
            path.write_text(path.read_text(encoding='utf-8') + ' ', encoding='utf-8')
        self._during_read('/aiyoloapi/models', self.headers, change, 409, 'catalog_changed')

    def test_timeout_returns_retryable_status_and_preserves_worker_bound(self):
        self.reader.timeout = .02
        release = threading.Event()
        self.addCleanup(release.set)
        def held():
            release.wait(3)
            return []
        with patch.object(main.model_catalog, 'list_models', held):
            try:
                response = self.client.get('/aiyoloapi/models', headers=self.headers)
                self.assertEqual(503, response.status_code)
                self.assertEqual('catalog_timeout', response.json()['detail']['code'])
                self.assertEqual('1', response.headers['retry-after'])
            finally:
                release.set()
                self.reader._executor.shutdown(wait=True)
