import json
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app.alerts.disposition import AlertDispositionStore
from app.alerts.verification import AlertVerificationStore
from app.alerts.verification_attempts import VerificationRequestConflict
from app.alerts.verification_provider import VerificationProviderError, VerificationProviderResult
from app.database import AlertVerificationRecord, DatabaseManager, ProjectRecord
from postgresql_support import isolated_postgresql_url


IMAGE = "data:image/jpeg;base64,aW1hZ2U="


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "set RUN_POSTGRES_TESTS=1")
class VerificationAttemptsPostgreSqlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.isolated = isolated_postgresql_url("m37_verification_attempts")
        cls.database_url = cls.isolated.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.isolated.__exit__(None, None, None)

    def setUp(self):
        self.database = DatabaseManager(self.database_url)
        self.project_id = str(uuid4())
        with self.database.session() as session:
            session.add(ProjectRecord(project_id=self.project_id, project_code=self.project_id,
                                      display_name="isolated verification fixture"))
        self.alerts = AlertDispositionStore(self.database)
        self.event = self.alerts.register({"eventId": "review",
            "evidence": {"snapshotUri": IMAGE}}, project_id=self.project_id)

    def tearDown(self):
        self.database.close()

    def configure(self, provider, limit=4):
        store = AlertVerificationStore(database_manager=self.database, provider=provider)
        store.configure(enabled=True, image_egress_authorized=True, daily_limit=limit,
                        model_id="fixture-model", provider_configured=True, project_id=self.project_id)
        return store

    def request(self, store, **changes):
        kwargs = dict(actor="fixture-account", image_ref="owned", image_data=IMAGE, project_id=self.project_id)
        kwargs.update(changes)
        return store.request(self.event, **kwargs)

    def test_pre_call_reservation_and_retry_history_survive_database_reopen(self):
        test = self
        class Provider:
            calls = 0
            def review(self, **kwargs):
                self.calls += 1
                observer = AlertVerificationStore(database_manager=test.database)
                pending = observer.get("review", test.project_id)
                test.assertEqual("PENDING", pending["status"])
                test.assertEqual("RESERVED", pending["quotaState"])
                test.assertEqual(self.calls, observer.config(test.project_id)["callsToday"])
                if self.calls == 1:
                    raise VerificationProviderError("RATE_LIMITED")
                return VerificationProviderResult("CONFIRMED", "fixture")
        provider = Provider()
        store = self.configure(provider)
        operation = str(uuid4())
        first = self.request(store, operation_id=operation)
        self.assertEqual("FAILED", first["status"])
        self.database.close()
        self.database = DatabaseManager(self.database_url)
        reopened = AlertVerificationStore(database_manager=self.database, provider=provider)
        self.assertEqual(first, reopened.get("review", self.project_id))
        self.assertEqual(first, self.request(reopened, operation_id=operation))
        second = self.request(reopened, operation_id=str(uuid4()), retry_of_attempt_id=first["attemptId"])
        self.assertEqual("CONFIRMED", second["status"])
        self.assertEqual(2, second["attemptCount"])
        self.assertEqual(first, self.request(reopened, operation_id=operation))
        with self.database.session() as session:
            payload = session.get(AlertVerificationRecord, (self.project_id, "review")).payload
        self.assertEqual(2, len(payload["attempts"]))
        self.assertEqual(["FAILED", "CONFIRMED"], [a["status"] for a in payload["attempts"]])
        self.assertNotIn("base64", json.dumps(payload))
        self.assertEqual(2, reopened.config(self.project_id)["callsToday"])
        results, _ = reopened.statistics(self.project_id, 0)
        self.assertEqual(1, len(results))

    def test_abrupt_process_loss_keeps_reserved_attempt_and_blocks_replay(self):
        class ProcessLoss(BaseException):
            pass
        class Provider:
            calls = 0
            def review(self, **kwargs):
                self.calls += 1
                raise ProcessLoss()
        provider = Provider()
        store = self.configure(provider)
        operation = str(uuid4())
        with self.assertRaises(ProcessLoss):
            self.request(store, operation_id=operation)
        self.database.close()
        self.database = DatabaseManager(self.database_url)
        reopened = AlertVerificationStore(database_manager=self.database, provider=provider)
        pending = reopened.get("review", self.project_id)
        self.assertEqual("PENDING", pending["status"])
        self.assertEqual(pending, self.request(reopened, operation_id=operation))
        with self.database.session() as session:
            row = session.get(AlertVerificationRecord, (self.project_id, "review"))
            row.payload = {**row.payload, "leaseExpiresAtUs": 0}
        unknown = reopened.get("review", self.project_id)
        self.assertEqual("UNKNOWN", unknown["status"])
        self.assertEqual("OUTCOME_UNKNOWN", unknown["attempts"][-1]["failureKind"])
        self.assertEqual(unknown, self.request(reopened, operation_id=operation))
        with self.assertRaises(VerificationRequestConflict):
            self.request(reopened, operation_id=str(uuid4()), retry_of_attempt_id=unknown["attemptId"])
        self.assertEqual(1, reopened.config(self.project_id)["callsToday"])
        self.assertEqual(1, provider.calls)
        with self.database.session() as session:
            self.assertEqual("UNKNOWN", session.get(AlertVerificationRecord, (self.project_id, "review")).status)

    def test_separate_instances_concurrent_requests_and_quota_boundary(self):
        started, release = threading.Event(), threading.Event()
        class Provider:
            calls = 0
            def review(self, **kwargs):
                self.calls += 1
                started.set()
                if not release.wait(10):
                    raise RuntimeError("fixture timed out")
                return VerificationProviderResult("CONFIRMED", "fixture")
        provider = Provider()
        first = self.configure(provider, limit=1)
        other_db = DatabaseManager(self.database_url)
        second = AlertVerificationStore(database_manager=other_db, provider=provider)
        operation = str(uuid4())
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                future = pool.submit(self.request, first, operation_id=operation)
                try:
                    self.assertTrue(started.wait(5))
                    duplicate = self.request(second, operation_id=operation)
                    self.assertEqual("PENDING", duplicate["status"])
                    with self.assertRaises(VerificationRequestConflict):
                        self.request(second, operation_id=str(uuid4()), retry_of_attempt_id=duplicate["attemptId"])
                    next_event = self.alerts.register({"eventId": "quota-boundary"}, project_id=self.project_id)
                    denied = second.request(next_event, actor="owner", image_ref="owned", image_data=IMAGE,
                                            project_id=self.project_id, operation_id=str(uuid4()))
                    self.assertEqual("QUOTA_EXHAUSTED", denied["failureKind"])
                    self.assertIsNone(denied["attemptId"])
                finally:
                    release.set()
                self.assertEqual("CONFIRMED", future.result(timeout=5)["status"])
            self.assertEqual(1, provider.calls)
            self.assertEqual(1, second.config(self.project_id)["callsToday"])
        finally:
            other_db.close()
