"""Controlled provider transport and shutdown tests; no external FCM calls."""
import asyncio
from datetime import timedelta
import threading
import unittest
from unittest.mock import patch

from app.model_updates.models import Device, PushOutbox
from app.model_updates.protocol import now, utc
from app.model_updates.push import FcmSender, PushDispatcher, PushResult
from app.model_updates.service import ModelUpdateService
import test_model_updates as common


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        common.UpdateStoreTests.setUp(self)
        self.store.bind('account-one', 'https://test.example', 'installation-one',
                        common.binding_request() | dict(pushProvider='fcm', token='test-token-one', tokenGeneration=1))
        common.UpdateStoreTests.put(self)
        self.dispatcher = PushDispatcher(self.store, type('Sender', (), {'enabled': True})())

    def test_expired_lease_is_reclaimed_and_old_result_cannot_ack_new_lease(self):
        first = self.dispatcher.claim(self.device)
        self.assertIsNone(self.dispatcher.claim(self.device))
        with self.db.session() as session:
            session.get(PushOutbox, self.device).lease_until = now() - timedelta(seconds=1)
        second = self.dispatcher.claim(self.device)
        self.assertNotEqual(first['leaseId'], second['leaseId'])
        self.dispatcher.finish(first, PushResult('accepted'))
        with self.db.session() as session:
            self.assertEqual(0, session.get(PushOutbox, self.device).sent_sequence)
        self.dispatcher.finish(second, PushResult('accepted'))
        with self.db.session() as session:
            self.assertEqual(1, session.get(PushOutbox, self.device).sent_sequence)

    def test_old_token_failure_cannot_retire_rotated_token(self):
        lease = self.dispatcher.claim(self.device)
        self.store.bind('account-one', 'https://test.example', 'installation-one',
                        common.binding_request() | dict(pushProvider='fcm', token='test-token-two', tokenGeneration=2))
        self.dispatcher.finish(lease, PushResult('invalid_token'))
        with self.db.session() as session:
            self.assertEqual('test-token-two', session.get(Device, self.device).push_token)
            self.assertEqual(0, session.get(PushOutbox, self.device).sent_sequence)

    def test_backoff_caps_at_hour_but_obeys_stricter_provider_retry(self):
        for supplier, expected in [(30, 3600), (7200, 7200)]:
            with self.db.session() as session:
                row = session.get(PushOutbox, self.device)
                row.next_attempt, row.attempts = now() - timedelta(seconds=1), 99
            lease = self.dispatcher.claim(self.device)
            before = now()
            with patch('app.model_updates.push.random.uniform', return_value=1.2):
                self.dispatcher.finish(lease, PushResult('retry', supplier))
            with self.db.session() as session:
                seconds = (utc(session.get(PushOutbox, self.device).next_attempt) - before).total_seconds()
                self.assertGreaterEqual(seconds, expected)
                self.assertLess(seconds, expected + 2)

    def test_fcm_limiter_does_not_spend_control_plane_budget(self):
        self.store.rate_limit('fcm:egress', rate=100, burst=100, shared_global=False)
        from app.model_updates.models import RateBucket
        with self.db.session() as session:
            self.assertIsNone(session.get(RateBucket, '0:global'))

    def test_none_bindings_cannot_starve_real_fcm_candidate(self):
        from datetime import timedelta
        from uuid import uuid4
        with self.db.session() as session:
            base = session.get(Device, self.device)
            for index in range(3):
                device_id = str(uuid4())
                session.add(Device(device_id=device_id, installation_id=base.installation_id, epoch=index + 10,
                    account_id=base.account_id, origin=base.origin, capabilities=base.capabilities, push_provider='none',
                    notification_permission='denied'))
                session.flush()
                session.add(PushOutbox(device_id=device_id, dirty_sequence=1,
                    next_attempt=now() - timedelta(days=1)))
        calls = []
        self.dispatcher.sender.send = lambda token: calls.append(token) or PushResult('accepted')
        self.assertEqual({'accepted': 1}, self.dispatcher.dispatch(maximum=1))
        self.assertEqual(['test-token-one'], calls)
        restarted = ModelUpdateService(self.db, None, None)
        self.assertEqual(1, restarted.metrics()['measurements']['provider_accepted']['count'])


class ProviderTests(unittest.TestCase):
    def sender(self, status, body, headers=None):
        sender = FcmSender('internal-project', 'fixture-not-read',
                           transport=lambda *args: (status, body, headers or {}))
        sender._access_token = lambda: 'fixture-only'
        return sender

    def test_unregistered_only_retires_explicit_fcm_token_error(self):
        result = self.sender(404, {'error': {'details': [dict(
            **{'@type': 'type.googleapis.com/google.firebase.fcm.v1.FcmError'}, errorCode='UNREGISTERED')]}}).send('fixture')
        self.assertEqual('invalid_token', result.state)
        self.assertEqual('configuration_error', self.sender(404, {}).send('fixture').state)

    def test_retry_after_and_malformed_provider_body_are_bounded_failures(self):
        self.assertEqual(7200, self.sender(429, {}, {'retry-after': '7200'}).send('fixture').retry_after)
        self.assertEqual('retry', self.sender(503, []).send('fixture').state)
        self.assertEqual('configuration_error', self.sender(403, {}).send('fixture').state)

    def test_unauthorized_response_invalidates_cached_oauth_token(self):
        sender = self.sender(401, {})
        sender._token, sender._until = 'expired', 9999999999
        sender.send('fixture')
        self.assertIsNone(sender._token)
        self.assertEqual(0, sender._until)

    def test_malformed_nested_error_does_not_escape_dispatcher(self):
        for error in (None, [], 'invalid', {'details': None}, {'details': 42}):
            with self.subTest(error=error):
                self.assertEqual('retry', self.sender(503, {'error': error}).send('fixture').state)
        self.assertEqual(30, self.sender(429, {}, {'Retry-After': 'invalid-date'}).send('fixture').retry_after)


class ServiceShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_drains_inflight_thread_before_return(self):
        service = ModelUpdateService(type('DB', (), {'enabled': True})(), None, None)
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        service.projection.scan = lambda: dict(failedDevices=0)
        def dispatch():
            started.set()
            if not release.wait(5):
                raise RuntimeError('test timeout')
            finished.set()
            return {}
        service.dispatcher.dispatch = dispatch
        service.store.cleanup = lambda: None
        await service.start()
        service.wake()
        self.assertTrue(await asyncio.to_thread(started.wait, 5))
        closing = asyncio.create_task(service.close())
        try:
            await asyncio.sleep(0)
            self.assertFalse(closing.done())
        finally:
            release.set()
            await asyncio.wait_for(closing, 5)
        self.assertTrue(finished.is_set())
        self.assertIsNone(service._task)

    async def test_slow_provider_does_not_hold_compensation_loop(self):
        service = ModelUpdateService(type('DB', (), {'enabled': True})(), None, None)
        service.store.observe = lambda *args: None
        service.store.cleanup = lambda: None
        scans = []
        service.projection.scan = lambda: scans.append(1) or dict(failedDevices=0, elapsedSeconds=0)
        started, release = threading.Event(), threading.Event()
        def dispatch():
            started.set()
            release.wait(5)
            return {}
        service.dispatcher.dispatch = dispatch
        await service.start()
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 5))
            service.wake()
            for _ in range(100):
                if len(scans) >= 2:
                    break
                await asyncio.sleep(.01)
            self.assertGreaterEqual(len(scans), 2)
        finally:
            release.set()
            await service.close()
