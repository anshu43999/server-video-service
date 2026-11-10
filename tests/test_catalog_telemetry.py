import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import app.auth as auth
import app.main as main
from app.catalog_hashes import CatalogFileHashes, CatalogFileChanged
from app.catalog_reads import CatalogReads
from app.catalog_telemetry import CatalogTelemetry
from app.model_catalog import ModelCatalog
from app.observability import logger
from test_catalog_reads import until
from test_project_model_assignments import ModelApiFixture


class CatalogTelemetryUnitTests(unittest.TestCase):
    def test_untrusted_identity_route_and_outcome_are_not_echoed(self):
        with patch.object(logger, 'info') as sink:
            telemetry = CatalogTelemetry('secret-token', '/secret/model.pt?token=secret')
            telemetry.read_finished('secret-error')
            row = json.loads(sink.call_args.args[0])
        self.assertEqual(None, row['requestId'])
        self.assertEqual('unmatched', row['route'])
        self.assertEqual('error', row['outcome'])
        self.assertNotIn('secret', json.dumps(row))

    def test_sink_failure_does_not_escape_or_leak_exception(self):
        with patch.object(logger, 'info', side_effect=OSError('secret-sink-error')) as sink:
            telemetry = CatalogTelemetry(str(uuid4()), '/aiyoloapi/models')
            telemetry.read_finished('ok')
            telemetry.worker_finished('error', .001, None)
            self.assertEqual(2, sink.call_count)

    def test_counters_include_failed_attempts_reuses_and_fallback_rehash(self):
        with tempfile.TemporaryDirectory(prefix='m32-t29-stats-') as directory:
            path = Path(directory) / 'model.pt'
            path.write_bytes(b'local stats fixture')
            hashes = CatalogFileHashes(ModelCatalog.sha256)
            self.assertEqual(hashes.digest(path), hashes.digest(path))
            hashes.verify()
            hashes.clear()
            self.assertEqual((1, 1, 1), (hashes.hash_attempts, hashes.hash_completed, hashes.hash_reuses))
            self.assertGreaterEqual(hashes.hash_seconds, 0)
            with patch('app.catalog_hashes._change_time', return_value=None):
                fallback = CatalogFileHashes(ModelCatalog.sha256)
                fallback.digest(path)
                fallback.digest(path)
                fallback.verify()
            self.assertEqual((3, 3, 0), (fallback.hash_attempts, fallback.hash_completed, fallback.hash_reuses))
            def fail(_):
                raise OSError('secret-path-error')
            failed = CatalogFileHashes(fail)
            with self.assertRaises(CatalogFileChanged):
                failed.digest(path)
            self.assertEqual((1, 0, 0), (failed.hash_attempts, failed.hash_completed, failed.hash_reuses))


class CatalogTelemetryApiTests(ModelApiFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.reader = CatalogReads()
        self.addCleanup(self.reader.close)
        self.patches.enter_context(patch.object(main, 'catalog_reads', self.reader))
        self.records = []
        self.lock = threading.Lock()
        def capture(message):
            with self.lock:
                self.records.append(json.loads(message))
        self.patches.enter_context(patch.object(logger, 'info', side_effect=capture))

    def events(self, request_id=None, event=None):
        with self.lock:
            return [dict(row) for row in self.records
                    if (request_id is None or row.get('requestId') == request_id)
                    and (event is None or row.get('event') == event)]

    def test_success_correlates_server_request_id_and_allowlisted_counters_only(self):
        headers = dict(self.headers, **{'X-Request-ID': 'injected-request-secret',
                                       'Cookie': 'fixture=secret-cookie'})
        response = self.client.get('/aiyoloapi/models?unused=secret-query', headers=headers)
        self.assertEqual(200, response.status_code)
        request_id = response.headers['x-request-id']
        self.assertEqual(request_id, str(UUID(request_id)))
        rows = self.events(request_id)
        self.assertEqual(['catalog.worker.finished', 'catalog.read.finished', 'request.finished'],
                         [row['event'] for row in rows])
        worker, read, request = rows
        self.assertEqual({'event', 'requestId', 'route', 'outcome', 'durationMs',
                          'hashAttempts', 'hashCompleted', 'hashReuses', 'hashDurationMs'}, set(worker))
        self.assertEqual({'event', 'requestId', 'route', 'outcome', 'durationMs'}, set(read))
        self.assertEqual((6, 6, 3), (worker['hashAttempts'], worker['hashCompleted'], worker['hashReuses']))
        self.assertEqual(('ok', 'ok', 200, True),
                         (worker['outcome'], read['outcome'], request['status'], request['completed']))
        self.assertGreaterEqual(worker['durationMs'] + .01, worker['hashDurationMs'])
        self.assertGreaterEqual(read['durationMs'] + .01, worker['durationMs'])
        output = json.dumps(rows)
        for secret in ('secret-cookie', 'secret-query', 'injected-request-secret',
                       self.headers['Authorization'], self.temp.name, self.entries[0]['sha256']):
            self.assertNotIn(secret, output)

    def test_parallel_platform_and_project_stats_do_not_cross_requests(self):
        self.assertEqual(200, self._assign().status_code)
        async def scenario():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://fixture') as client:
                return await asyncio.gather(
                    client.get('/aiyoloapi/models', headers=self.headers),
                    client.get(self.project_path + '/models', headers=self.user))
        platform, project = asyncio.run(scenario())
        ids = [response.headers['x-request-id'] for response in (platform, project)]
        self.assertNotEqual(*ids)
        for response, request_id, expected, route in (
            (platform, ids[0], 6, '/aiyoloapi/models'),
            (project, ids[1], 2, '/aiyoloapi/projects/{project_id}/models')):
            self.assertEqual(200, response.status_code)
            workers = self.events(request_id, 'catalog.worker.finished')
            self.assertEqual(1, len(workers))
            self.assertEqual(expected, workers[0]['hashCompleted'])
            self.assertEqual(route, workers[0]['route'])
            self.assertEqual(1, len(self.events(request_id, 'catalog.read.finished')))

    def test_available_route_uses_template_and_has_one_pair_of_events(self):
        response = self.client.get(self.project_path + '/models/available', headers=self.owner)
        self.assertEqual(200, response.status_code)
        rows = self.events(response.headers['x-request-id'])
        worker = next(row for row in rows if row['event'] == 'catalog.worker.finished')
        self.assertEqual('/aiyoloapi/projects/{project_id}/models/available', worker['route'])
        self.assertEqual((6, 6, 3), (worker['hashAttempts'], worker['hashCompleted'], worker['hashReuses']))
        self.assertEqual(3, len(rows))

    def test_hash_completed_means_computed_not_integrity_passed(self):
        path = main.model_catalog.project_root / self.entries[0]['path']
        path.write_bytes(b'x' * path.stat().st_size)
        response = self.client.get('/aiyoloapi/models', headers=self.headers)
        self.assertEqual(200, response.status_code)
        self.assertFalse(response.json()['models'][0]['hashValid'])
        worker = self.events(response.headers['x-request-id'], 'catalog.worker.finished')[0]
        self.assertEqual('ok', worker['outcome'])
        self.assertEqual(6, worker['hashCompleted'])

    def test_added_log_sink_failure_does_not_change_response_or_hold_slots(self):
        def reject_added_events(message):
            row = json.loads(message)
            if row['event'].startswith('catalog.'):
                raise OSError('secret-log-sink-failure')
            with self.lock:
                self.records.append(row)
        with patch.object(logger, 'info', side_effect=reject_added_events):
            for _ in range(3):
                response = self.client.get('/aiyoloapi/models', headers=self.headers)
                self.assertEqual(200, response.status_code)
                self.assertTrue(response.json()['models'][0]['hashValid'])
        self.assertNotIn('secret-log-sink-failure', json.dumps(self.events()))

    def test_timeout_and_busy_end_http_before_late_worker_completion(self):
        self.reader.close()
        reader = CatalogReads(workers=1, timeout=.03)
        self.addCleanup(reader.close)
        release, started = threading.Event(), threading.Event()
        original = main.model_catalog.list_models
        def held():
            started.set()
            release.wait(3)
            return original()
        async def scenario():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://fixture') as client:
                with patch.object(main, 'catalog_reads', reader), patch.object(main.model_catalog, 'list_models', held):
                    try:
                        timed = await client.get('/aiyoloapi/models', headers=self.headers)
                        request_id = timed.headers['x-request-id']
                        self.assertTrue(started.is_set())
                        self.assertEqual(503, timed.status_code)
                        self.assertEqual('timeout', self.events(request_id, 'catalog.read.finished')[0]['outcome'])
                        self.assertEqual([], self.events(request_id, 'catalog.worker.finished'))
                        self.assertTrue(self.events(request_id, 'request.finished')[0]['completed'])
                        busy = await client.get('/aiyoloapi/models', headers=self.headers)
                        busy_id = busy.headers['x-request-id']
                        self.assertEqual(503, busy.status_code)
                        self.assertEqual('busy', self.events(busy_id, 'catalog.read.finished')[0]['outcome'])
                        self.assertEqual([], self.events(busy_id, 'catalog.worker.finished'))
                    finally:
                        release.set()
                        await asyncio.to_thread(reader._executor.shutdown, wait=True)
                    worker = self.events(request_id, 'catalog.worker.finished')
                    self.assertEqual(1, len(worker))
                    self.assertEqual(('ok', 6), (worker[0]['outcome'], worker[0]['hashCompleted']))
                    self.assertEqual(['catalog.read.finished', 'request.finished', 'catalog.worker.finished'],
                                     [row['event'] for row in self.events(request_id)])
        asyncio.run(scenario())

    def test_cancelled_waiter_and_late_worker_remain_separate(self):
        release, started = threading.Event(), threading.Event()
        original = main.model_catalog.list_models
        def held():
            started.set()
            release.wait(3)
            return original()
        async def scenario():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://fixture') as client:
                with patch.object(main.model_catalog, 'list_models', held):
                    task = asyncio.create_task(client.get('/aiyoloapi/models', headers=self.headers))
                    try:
                        await until(started.is_set)
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                        read = self.events(event='catalog.read.finished')
                        self.assertEqual(1, len(read))
                        self.assertEqual('cancelled', read[0]['outcome'])
                        request_id = read[0]['requestId']
                        self.assertEqual([], self.events(request_id, 'catalog.worker.finished'))
                        self.assertFalse(self.events(request_id, 'request.finished')[0]['completed'])
                    finally:
                        release.set()
                        await asyncio.to_thread(self.reader._executor.shutdown, wait=True)
                    self.assertEqual('ok', self.events(request_id, 'catalog.worker.finished')[0]['outcome'])
                    self.assertEqual('cancelled', self.events(request_id, 'catalog.read.finished')[0]['outcome'])
        asyncio.run(scenario())

    def test_file_change_logs_changed_without_path_or_error_text(self):
        original = main.model_catalog.list_models
        def changed():
            result = original()
            (main.model_catalog.project_root / self.entries[0]['path']).unlink()
            return result
        with patch.object(main.model_catalog, 'list_models', changed):
            response = self.client.get('/aiyoloapi/models', headers=self.headers)
        self.assertEqual(409, response.status_code)
        rows = self.events(response.headers['x-request-id'])
        self.assertEqual(['changed', 'changed'], [row['outcome'] for row in rows if 'outcome' in row])
        self.assertNotIn(self.temp.name, json.dumps(rows))

    def test_post_worker_revocation_is_not_logged_as_read_success(self):
        original = main.model_catalog.list_models
        def revoked():
            result = original()
            auth._memory_sessions.clear()
            return result
        with patch.object(main.model_catalog, 'list_models', revoked):
            response = self.client.get('/aiyoloapi/models', headers=self.headers)
        self.assertEqual(401, response.status_code)
        rows = self.events(response.headers['x-request-id'])
        self.assertEqual(['ok', 'denied'], [row['outcome'] for row in rows if 'outcome' in row])

    def test_failed_hash_has_attempt_but_no_completed_digest_or_exception_leak(self):
        with patch.object(main.model_catalog, 'sha256', side_effect=OSError('secret-file-token-password')):
            response = self.client.get('/aiyoloapi/models', headers=self.headers)
        self.assertEqual(409, response.status_code)
        rows = self.events(response.headers['x-request-id'])
        worker = next(row for row in rows if row['event'] == 'catalog.worker.finished')
        self.assertEqual((1, 0, 0), (worker['hashAttempts'], worker['hashCompleted'], worker['hashReuses']))
        self.assertNotIn('secret-file-token-password', json.dumps(rows))

    def test_unexpected_error_is_sanitized_and_does_not_fake_success(self):
        with patch.object(main.model_catalog, 'list_models', side_effect=ValueError('secret-internal-exception')):
            with self.assertRaises(ValueError):
                self.client.get('/aiyoloapi/models', headers=self.headers)
        worker = self.events(event='catalog.worker.finished')
        read = self.events(event='catalog.read.finished')
        self.assertEqual(1, len(worker))
        self.assertEqual(1, len(read))
        self.assertEqual(('error', 'error'), (worker[0]['outcome'], read[0]['outcome']))
        self.assertNotIn('secret-internal-exception', json.dumps(self.events()))

    def test_denied_before_catalog_admission_has_only_existing_http_log(self):
        response = self.client.get('/aiyoloapi/models', headers={'Authorization': 'Bearer invalid-secret'})
        self.assertEqual(401, response.status_code)
        rows = self.events(response.headers['x-request-id'])
        self.assertEqual(['request.finished'], [row['event'] for row in rows])
        self.assertNotIn('invalid-secret', json.dumps(rows))
