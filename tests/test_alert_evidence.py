import base64
import tempfile
import unittest
from pathlib import Path

from app.alert_evidence import AlertEvidenceStore, EvidenceStorageError
from app.database import (
    AlertEventRecord,
    Base,
    DatabaseManager,
    FalsePositiveFeedbackRecord,
)
from tools.migrate_alert_evidence_to_minio import migrate


PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(b"png-bytes").decode("ascii")


class FakeResponse:
    def __init__(self, content):
        self.content = content
        self.closed = False
        self.released = False

    def read(self):
        return self.content

    def close(self):
        self.closed = True

    def release_conn(self):
        self.released = True


class FakeMinio:
    def __init__(self, *, exists=True):
        self.exists = exists
        self.created = []
        self.uploads = []
        self.objects = {}

    def bucket_exists(self, bucket):
        return self.exists

    def make_bucket(self, bucket):
        self.created.append(bucket)
        self.exists = True

    def put_object(self, bucket, object_key, stream, length, **kwargs):
        content = stream.read()
        self.uploads.append((bucket, object_key, content, length, kwargs))
        self.objects[(bucket, object_key)] = content

    def get_object(self, bucket, object_key):
        return FakeResponse(self.objects[(bucket, object_key)])


def make_store(client=None, **overrides):
    return AlertEvidenceStore(
        endpoint="minio.internal:9000",
        access_key="access",
        secret_key="secret",
        bucket="aiyolo-alerts",
        secure=False,
        client=client or FakeMinio(),
        **overrides,
    )


class AlertEvidenceStoreTests(unittest.TestCase):
    def test_store_and_read_use_private_object_reference(self):
        client = FakeMinio()
        store = make_store(client)
        reference = store.store_data_url("mobile:event:1", PNG_DATA_URL)

        evidence = reference["objectStorage"]
        self.assertEqual(evidence["provider"], "minio")
        self.assertEqual(evidence["bucket"], "aiyolo-alerts")
        self.assertNotIn("data:image", str(reference))
        self.assertEqual(client.uploads[0][2], b"png-bytes")
        body = store.read(reference)
        self.assertEqual(body.content, b"png-bytes")
        self.assertEqual(body.content_type, "image/png")

    def test_validate_can_create_bucket_only_when_enabled(self):
        client = FakeMinio(exists=False)
        store = make_store(client, auto_create_bucket=True)
        store.validate()
        self.assertEqual(client.created, ["aiyolo-alerts"])

        with self.assertRaises(EvidenceStorageError):
            make_store(FakeMinio(exists=False)).validate()

    def test_invalid_or_oversized_data_url_is_rejected(self):
        with self.assertRaises(ValueError):
            AlertEvidenceStore.decode_data_url("data:text/plain;base64,AAAA")
        oversized = "data:image/png;base64," + base64.b64encode(b"x" * 9).decode("ascii")
        with self.assertRaises(ValueError):
            AlertEvidenceStore.decode_data_url(oversized, max_bytes=8)


class FakeEvidenceStore:
    enabled = True

    def __init__(self):
        self.events = []

    def store_data_url(self, event_id, data_url):
        self.events.append((event_id, data_url))
        return {
            "snapshotUri": f"/aiyoloapi/alerts/{event_id}/evidence",
            "objectStorage": {
                "provider": "minio",
                "bucket": "aiyolo-alerts",
                "objectKey": f"alerts/{event_id}.png",
                "contentType": "image/png",
                "sizeBytes": 9,
                "sha256": "digest",
            },
        }


class AlertEvidenceMigrationTests(unittest.TestCase):
    def test_migration_removes_inline_image_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            database = DatabaseManager(f"sqlite:///{Path(temp) / 'migration.db'}")
            Base.metadata.create_all(database.engine)
            with database.session() as session:
                session.add(AlertEventRecord(
                    event_id="event-1",
                    disposition_status="FALSE_POSITIVE",
                    payload={
                        "eventId": "event-1",
                        "evidence": {"snapshotDataUrl": PNG_DATA_URL},
                    },
                ))
                session.add(FalsePositiveFeedbackRecord(
                    entry_id="fp-1",
                    event_id="event-1",
                    action_id=1,
                    payload={"image": PNG_DATA_URL, "screenshot": PNG_DATA_URL},
                ))

            store = FakeEvidenceStore()
            first = migrate(database, store, batch_size=1)
            second = migrate(database, store, batch_size=1)
            self.assertEqual(first["migrated"], 1)
            self.assertEqual(first["feedbackUpdated"], 1)
            self.assertEqual(second["migrated"], 0)

            with database.session() as session:
                event = session.get(AlertEventRecord, "event-1")
                feedback = session.get(FalsePositiveFeedbackRecord, "fp-1")
                self.assertNotIn("snapshotDataUrl", event.payload["evidence"])
                self.assertEqual(event.payload["evidence"]["objectStorage"]["provider"], "minio")
                self.assertNotIn("data:image", str(event.payload))
                self.assertNotIn("data:image", str(feedback.payload))
            database.close()


if __name__ == "__main__":
    unittest.main()
