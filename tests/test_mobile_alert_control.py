import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app.alerts.disposition import AlertDispositionStore, public_alert_event
from app.database import Base, DatabaseManager, DEFAULT_PROJECT_ID
from postgresql_support import isolated_postgresql_url


PRODUCER = "11111111-1111-4111-8111-111111111111"


def fact(event_id="local:control:1", *, producer=True):
    return {"eventId": event_id, "origin": "MOBILE_IMAGE", "sourceId": "image:control",
            "ruleId": "helmet", "subjectKey": "frame:1", "startedAtUs": 1, "evidence": {},
            **({"mobileProducer": {"accountId": "capture-account", "producerId": PRODUCER}} if producer else {})}


class MobileControlStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = AlertDispositionStore()
        self.store.register_mobile_fact(fact(), DEFAULT_PROJECT_ID)

    def dispose(self, status="FALSE_POSITIVE", revision=0, **kwargs):
        return self.store.dispose("local:control:1", status, "backend", expected_revision=revision, **kwargs)

    def sync(self, account="capture-account", producer=PRODUCER, project=DEFAULT_PROJECT_ID):
        return self.store.mobile_sync(project, account, [{"eventId": "local:control:1", "producerId": producer}])

    def test_backend_confirm_needs_no_mobile_action_or_original(self):
        result = self.dispose("ACKNOWLEDGED")
        self.assertEqual(1, result["dispositionRevision"])
        self.assertNotIn("_originalRequests", result)
        self.assertEqual("ACKNOWLEDGED", self.sync()[0]["disposition"]["status"])

    def test_backend_false_positive_is_atomic_and_producer_is_private(self):
        result = self.dispose()
        public = public_alert_event(result)
        self.assertEqual("PENDING", public["originalRequest"]["status"])
        self.assertNotIn("mobileProducer", public)
        self.assertNotIn("_originalRequests", public)
        self.assertEqual(public["originalRequest"]["requestId"], self.sync()[0]["requests"][0]["requestId"])
        self.assertEqual([], self.sync(account="another-account"))
        self.assertEqual([], self.sync(producer=str(uuid4())))
        self.assertEqual([], self.sync(project="another-project"))

    def test_stale_or_missing_revision_cannot_add_action_or_original_request(self):
        self.dispose("ACKNOWLEDGED")
        for expected in (0, None):
            with self.assertRaisesRegex(ValueError, "disposition_revision_conflict"):
                self.dispose(revision=expected)
        result = self.store.get("local:control:1")
        self.assertEqual(1, len(result["disposition"]["history"]))
        self.assertNotIn("_originalRequests", result)

    def test_receipt_replay_missing_file_and_conflicting_terminal_result(self):
        request = self.dispose()["_originalRequests"]
        request_id = next(iter(request))
        receipt = {"producerId": PRODUCER, "status": "UNAVAILABLE", "reason": "local_file_missing"}
        first = self.store.original_receipt("local:control:1", DEFAULT_PROJECT_ID, "capture-account", request_id, receipt)
        self.assertEqual(first, self.store.original_receipt("local:control:1", DEFAULT_PROJECT_ID,
                                                          "capture-account", request_id, receipt))
        with self.assertRaisesRegex(ValueError, "receipt_conflict"):
            self.store.original_receipt("local:control:1", DEFAULT_PROJECT_ID, "capture-account", request_id,
                                        {**receipt, "reason": "no_local_capture"})
        self.assertEqual("FALSE_POSITIVE", self.store.get("local:control:1")["disposition"]["status"])

    def test_uploaded_receipt_requires_real_canonical_reference(self):
        request_id = next(iter(self.dispose()["_originalRequests"]))
        receipt = {"producerId": PRODUCER, "status": "UPLOADED", "contentVersion": 1, "sha256": "a" * 64}
        with self.assertRaisesRegex(ValueError, "original_not_uploaded"):
            self.store.original_receipt("local:control:1", DEFAULT_PROJECT_ID, "capture-account", request_id, receipt)
        self.store.register_evidence("local:control:1", DEFAULT_PROJECT_ID, "original", 1,
            {"sha256": "a" * 64, "objectStorage": {"provider": "minio"}})
        self.assertEqual("UPLOADED", self.store.original_receipt("local:control:1", DEFAULT_PROJECT_ID,
                                         "capture-account", request_id, receipt)["status"])

    def test_request_idempotency_cas_and_coalescing(self):
        op = str(uuid4())
        first = self.store.request_original("local:control:1", DEFAULT_PROJECT_ID, "backend", 0, op, "same")
        self.dispose("ACKNOWLEDGED")
        replay = self.store.request_original("local:control:1", DEFAULT_PROJECT_ID, "backend", 0, op, "same")
        self.assertEqual(first["_originalRequests"], replay["_originalRequests"])
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self.store.request_original("local:control:1", DEFAULT_PROJECT_ID, "backend", 0, op, "changed")
        self.store.request_original("local:control:1", DEFAULT_PROJECT_ID, "backend", 1, str(uuid4()), "new")
        self.assertEqual(1, len(self.store.get("local:control:1")["_originalRequests"]))

    def test_existing_original_satisfies_request_and_cannot_be_regressed(self):
        self.store.register_evidence("local:control:1", DEFAULT_PROJECT_ID, "original", 1,
                                    {"sha256": "a" * 64, "objectStorage": {"provider": "minio"}})
        request = public_alert_event(self.dispose())["originalRequest"]
        self.assertEqual("UPLOADED", request["status"])
        with self.assertRaisesRegex(ValueError, "receipt_conflict"):
            self.store.original_receipt("local:control:1", DEFAULT_PROJECT_ID, "capture-account", request["requestId"],
                {"producerId": PRODUCER, "status": "UNAVAILABLE", "reason": "no_local_capture"})

    def test_sync_is_bounded_after_repeated_terminal_requests(self):
        for _ in range(4):
            event = self.store.request_original("local:control:1", DEFAULT_PROJECT_ID, "backend", 0, str(uuid4()), "new")
            request_id = list(event["_originalRequests"])[-1]
            self.store.original_receipt("local:control:1", DEFAULT_PROJECT_ID, "capture-account", request_id,
                {"producerId": PRODUCER, "status": "UNAVAILABLE", "reason": "local_file_missing"})
        self.assertEqual(1, len(self.sync()[0]["requests"]))
        self.assertEqual(request_id, self.sync()[0]["requests"][0]["requestId"])

    def test_unknown_legacy_capture_is_not_claimed(self):
        self.store.register_mobile_fact(fact("local:legacy:1", producer=False), DEFAULT_PROJECT_ID)
        result = self.store.dispose("local:legacy:1", "FALSE_POSITIVE", "backend")
        self.assertEqual("producer_unregistered", public_alert_event(result)["originalRequest"]["unavailableReason"])
        with self.assertRaisesRegex(ValueError, "producer_identity_conflict"):
            self.store.register_mobile_fact(fact("local:legacy:1"), DEFAULT_PROJECT_ID)

    def test_l2_lost_response_replay_precedes_revision_check(self):
        op = str(uuid4())
        self.dispose(operation_id=op, request_digest="same")
        replay = self.dispose(operation_id=op, request_digest="same")
        self.assertEqual(1, len(replay["disposition"]["history"]))
        self.assertEqual(1, len(replay["_originalRequests"]))


class MobileControlSqliteTests(unittest.TestCase):
    def test_committed_operation_survives_sql_projection_and_reopen(self):
        database = DatabaseManager("sqlite+pysqlite:///:memory:")
        self.addCleanup(database.close)
        Base.metadata.create_all(database.engine)
        store = AlertDispositionStore(database)
        store.register(fact())
        operation = str(uuid4())
        store.dispose("local:control:1", "ACKNOWLEDGED", "capture-account", expected_revision=0,
                      operation_id=operation, request_digest="private-internal-digest", acted_at_us=100)
        reopened = AlertDispositionStore(database)
        snapshot = reopened.mobile_sync(DEFAULT_PROJECT_ID, "capture-account",
            [{"eventId": "local:control:1", "producerId": PRODUCER}])[0]
        self.assertEqual(operation, snapshot["disposition"]["history"][0]["operationId"])
        self.assertEqual(operation, snapshot["disposition"]["operationId"])
        self.assertNotIn("requestDigest", snapshot["disposition"]["history"][0])

    def test_durable_request_and_revision_survive_store_recreation(self):
        database = DatabaseManager("sqlite+pysqlite:///:memory:")
        self.addCleanup(database.close)
        Base.metadata.create_all(database.engine)
        first = AlertDispositionStore(database)
        first.register(fact())
        first.dispose("local:control:1", "ACKNOWLEDGED", "backend", expected_revision=0, acted_at_us=200)
        # Client timestamps are evidence, not ordering authority.
        first.dispose("local:control:1", "FALSE_POSITIVE", "backend", expected_revision=1, acted_at_us=100)
        reopened = AlertDispositionStore(database)
        result = reopened.get("local:control:1")
        self.assertEqual("FALSE_POSITIVE", result["disposition"]["status"])
        self.assertEqual(2, result["dispositionRevision"])
        self.assertEqual(1, len(result["_originalRequests"]))
        with self.assertRaisesRegex(ValueError, "disposition_revision_conflict"):
            reopened.dispose("local:control:1", "ACKNOWLEDGED", "mobile", expected_revision=0)


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "explicit remote PostgreSQL opt-in")
class MobileControlPostgresqlTests(unittest.TestCase):
    def test_atomic_cas_across_independent_stores_and_restart(self):
        with isolated_postgresql_url("m38_control") as url:
            database = DatabaseManager(url)
            self.addCleanup(database.close)
            AlertDispositionStore(database).register_mobile_fact(fact(), DEFAULT_PROJECT_ID)

            def act(_):
                other = DatabaseManager(url)
                try:
                    AlertDispositionStore(other).dispose("local:control:1", "FALSE_POSITIVE", "backend",
                                                        expected_revision=0, acted_at_us=100)
                    return "committed"
                except ValueError as error:
                    return str(error)
                finally:
                    other.close()
            with ThreadPoolExecutor(max_workers=4) as pool:
                outcomes = list(pool.map(act, range(4)))
            self.assertEqual(1, outcomes.count("committed"))
            self.assertEqual(3, outcomes.count("disposition_revision_conflict"))
            reopened = AlertDispositionStore(database).get("local:control:1")
            self.assertEqual(1, reopened["dispositionRevision"])
            self.assertEqual(1, len(reopened["_originalRequests"]))
