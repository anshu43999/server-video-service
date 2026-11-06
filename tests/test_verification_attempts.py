import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from unittest.mock import Mock

from app.alerts.verification import AlertVerificationStore
from app.alerts.verification_attempts import VerificationRequestConflict
from app.alerts.verification_provider import VerificationProviderError, VerificationProviderResult


IMAGE = "data:image/jpeg;base64,aW1hZ2U="


class SequenceProvider:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def review(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return VerificationProviderResult(outcome, "fixture verdict")


class VerificationAttemptTests(unittest.TestCase):
    def test_implicit_database_reset_is_rejected_without_opening_a_session(self):
        database = Mock()
        store = AlertVerificationStore(database_manager=database)
        with self.assertRaisesRegex(ValueError, "explicit allow_database_delete"):
            store.reset()
        database.session.assert_not_called()

    def setup_store(self, provider, **changes):
        store = AlertVerificationStore(provider=provider)
        config = dict(enabled=True, image_egress_authorized=True, daily_limit=4,
                      model_id="fixture-model", provider_configured=True, project_id="project-a")
        config.update(changes)
        store.configure(**config)
        return store

    def request(self, store, **changes):
        kwargs = dict(actor="owner", image_ref="owned-reference", image_data=IMAGE,
                      project_id="project-a")
        kwargs.update(changes)
        return store.request({"eventId": "fixture", "projectId": "project-a"}, **kwargs)

    def test_transient_failure_explicit_retry_and_old_operation_replay(self):
        provider = SequenceProvider(VerificationProviderError("RATE_LIMITED"), "CONFIRMED")
        store = self.setup_store(provider)
        operation = str(uuid4())
        first = self.request(store, operation_id=operation)
        self.assertTrue(first["retryable"])
        self.assertEqual(1, first["attemptCount"])
        self.assertEqual("CONSUMED", first["quotaState"])
        self.assertEqual(first, self.request(store, operation_id=operation))
        retry = str(uuid4())
        second = self.request(store, operation_id=retry, retry_of_attempt_id=first["attemptId"])
        self.assertEqual("CONFIRMED", second["status"])
        self.assertEqual(2, second["attemptCount"])
        self.assertNotEqual(first["attemptId"], second["attemptId"])
        self.assertEqual(first, self.request(store, operation_id=operation))
        self.assertEqual(second, self.request(store, operation_id=retry, retry_of_attempt_id=first["attemptId"]))
        self.assertEqual(2, store.config("project-a")["callsToday"])
        self.assertEqual(2, len(provider.calls))
        self.assertEqual(first["attemptId"], provider.calls[0]["attempt_id"])
        self.assertEqual(second["attemptId"], provider.calls[1]["attempt_id"])
        self.assertNotIn("operations", second)
        self.assertNotIn("requestDigest", second)

    def test_deterministic_gates_do_not_call_or_consume_quota(self):
        for change, failure in (({"enabled": False}, "DISABLED"),
                                ({"image_egress_authorized": False}, "NOT_AUTHORIZED"),
                                ({"daily_limit": 0}, "QUOTA_EXHAUSTED"),
                                ({"provider_configured": False}, "NOT_CONFIGURED"),
                                ({"model_id": ""}, "NOT_CONFIGURED")):
            with self.subTest(failure=failure):
                provider = SequenceProvider("CONFIRMED")
                store = self.setup_store(provider, **change)
                first = self.request(store, operation_id=str(uuid4()))
                self.assertEqual(failure, first["failureKind"])
                self.assertIsNone(first["attemptId"])
                self.assertFalse(first["retryable"])
                self.assertEqual(0, store.config("project-a")["callsToday"])
                with self.assertRaises(VerificationRequestConflict):
                    self.request(store, operation_id=str(uuid4()), retry_of_attempt_id=str(uuid4()))
                self.assertEqual([], provider.calls)
        for image_ref, image_data in ((None, IMAGE), ("reference", None)):
            store = self.setup_store(SequenceProvider("CONFIRMED"))
            result = self.request(store, image_ref=image_ref, image_data=image_data)
            self.assertEqual("MISSING_IMAGE", result["failureKind"])
            self.assertEqual(0, store.config("project-a")["callsToday"])

    def test_unknown_provider_outcome_keeps_reservation_and_cannot_retry(self):
        for kind in ("TIMEOUT_UNKNOWN", "NETWORK", "MALFORMED_RESPONSE"):
            with self.subTest(kind=kind):
                provider = SequenceProvider(VerificationProviderError(kind))
                store = self.setup_store(provider)
                operation = str(uuid4())
                result = self.request(store, operation_id=operation)
                self.assertEqual("UNKNOWN", result["status"])
                self.assertEqual("RESERVED", result["quotaState"])
                self.assertEqual("UNVERIFIED", result["providerBilling"])
                self.assertFalse(result["retryable"])
                self.assertEqual(result, self.request(store, operation_id=operation))
                with self.assertRaises(VerificationRequestConflict):
                    self.request(store, operation_id=str(uuid4()), retry_of_attempt_id=result["attemptId"])
                self.assertEqual(1, len(provider.calls))

    def test_concurrent_request_observes_pending_without_reentering_provider(self):
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
        store = self.setup_store(provider)
        operation = str(uuid4())
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(self.request, store, operation_id=operation)
            try:
                self.assertTrue(started.wait(5))
                result = self.request(store, operation_id=operation)
                self.assertEqual("PENDING", result["status"])
                self.assertEqual(1, store.config("project-a")["callsToday"])
            finally:
                release.set()
            self.assertEqual("CONFIRMED", future.result(timeout=5)["status"])
        self.assertEqual(1, provider.calls)

    def test_request_identity_conflict_and_attempt_limit(self):
        provider = SequenceProvider(*(VerificationProviderError("RATE_LIMITED") for _ in range(3)))
        store = self.setup_store(provider)
        operation = str(uuid4())
        result = self.request(store, operation_id=operation)
        with self.assertRaisesRegex(VerificationRequestConflict, "idempotency_conflict"):
            self.request(store, operation_id=operation, image_ref="different-reference")
        for _ in range(2):
            result = self.request(store, operation_id=str(uuid4()), retry_of_attempt_id=result["attemptId"])
        self.assertFalse(result["retryable"])
        with self.assertRaisesRegex(VerificationRequestConflict, "retry_not_allowed"):
            self.request(store, operation_id=str(uuid4()), retry_of_attempt_id=result["attemptId"])
        self.assertEqual(3, len(provider.calls))

    def test_image_bytes_and_inline_refs_never_enter_result(self):
        provider = SequenceProvider("CONFIRMED")
        store = self.setup_store(provider)
        result = self.request(store, image_ref=IMAGE)
        self.assertNotIn("base64", json.dumps(result))
        self.assertNotIn("base64", json.dumps(list(store._results.values())))
