import base64
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.alert_evidence import AlertEvidenceStore, EvidenceStorageError
from app.database import (
    AlertEventRecord,
    DEFAULT_PROJECT_ID,
    Base,
    DatabaseManager,
    FalsePositiveFeedbackRecord,
    PlatformAuditEventRecord,
    ProjectRecord,
)
from app.alerts.evidence_retention import cleanup_alert_evidence, retain_alert_evidence
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
        self.fail_remove = False

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

    def remove_object(self, bucket, object_key):
        if self.fail_remove:
            raise OSError("simulated MinIO delete failure")
        self.objects.pop((bucket, object_key), None)


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
    def test_retention_dry_run_mark_grace_recheck_and_delete(self):
        database = DatabaseManager("sqlite:///:memory:")
        Base.metadata.create_all(database.engine)
        now = datetime(2026, 10, 20, tzinfo=timezone.utc)
        project_id = DEFAULT_PROJECT_ID
        key = "alerts/projects/p/events/e/thumbnail/1/d.jpg"
        client = FakeMinio()
        client.objects[("aiyolo-alerts", key)] = b"image"
        store = make_store(client)
        old = {"eventId": "event-1", "projectId": project_id, "disposition": {"status": "OPEN"},
               "evidence": {"thumbnail": {"1": {
                   "uploadedAt": (now - timedelta(days=91)).isoformat(),
                   "retentionState": "ACTIVE",
                   "objectStorage": {"provider": "minio", "bucket": "aiyolo-alerts", "objectKey": key},
               }}}}
        with database.session() as session:
            session.add(ProjectRecord(project_id=project_id, project_code="retention-test",
                                      display_name="Retention Test", lifecycle_state="ACTIVE"))
            session.add(AlertEventRecord(project_id=project_id, event_id="event-1", payload=old))

        preview = cleanup_alert_evidence(database, store, now=now)
        self.assertEqual(preview["marked"], 1)
        self.assertEqual(client.objects[("aiyolo-alerts", key)], b"image")
        marked = cleanup_alert_evidence(database, store, apply=True, now=now)
        self.assertEqual(marked["marked"], 1)
        with database.session() as session:
            row = session.get(AlertEventRecord, (project_id, "event-1"))
            delete_after = datetime.fromisoformat(row.payload["evidence"]["thumbnail"]["1"]["deleteAfter"])
        completed = cleanup_alert_evidence(database, store, apply=True,
                                           now=delete_after + timedelta(seconds=1))
        self.assertEqual(completed["deleted"], 1)
        self.assertNotIn(("aiyolo-alerts", key), client.objects)
        with database.session() as session:
            ref = session.get(AlertEventRecord, (project_id, "event-1")).payload["evidence"]["thumbnail"]["1"]
        self.assertEqual(ref["retentionState"], "DELETED")
        self.assertNotIn("objectStorage", ref)
        database.close()

    def test_retention_delete_failure_remains_pending_for_retry(self):
        database = DatabaseManager("sqlite:///:memory:")
        Base.metadata.create_all(database.engine)
        now = datetime(2026, 10, 20, tzinfo=timezone.utc)
        key = "alerts/projects/p/events/e/original/1/d.jpg"
        client = FakeMinio()
        client.objects[("aiyolo-alerts", key)] = b"image"
        client.fail_remove = True
        store = make_store(client)
        payload = {"eventId": "retry-event", "projectId": DEFAULT_PROJECT_ID,
                   "disposition": {"status": "OPEN"}, "evidence": {"original": {"1": {
                       "uploadedAt": (now - timedelta(days=95)).isoformat(),
                       "retentionState": "DELETE_PENDING",
                       "deleteAfter": (now - timedelta(hours=1)).isoformat(),
                       "objectStorage": {"provider": "minio", "bucket": "aiyolo-alerts", "objectKey": key},
                   }}}}
        with database.session() as session:
            session.add(ProjectRecord(project_id=DEFAULT_PROJECT_ID, project_code="retry-test",
                                      display_name="Retry Test", lifecycle_state="ACTIVE"))
            session.add(AlertEventRecord(project_id=DEFAULT_PROJECT_ID, event_id="retry-event", payload=payload))
        failed = cleanup_alert_evidence(database, store, apply=True, now=now)
        self.assertEqual(failed["failed"], 1)
        with database.session() as session:
            ref = session.get(AlertEventRecord, (DEFAULT_PROJECT_ID, "retry-event")).payload["evidence"]["original"]["1"]
        self.assertEqual(ref["retentionState"], "DELETE_PENDING")
        client.fail_remove = False
        retried = cleanup_alert_evidence(database, store, apply=True, now=now + timedelta(minutes=1))
        self.assertEqual(retried["deleted"], 1)
        database.close()

    def test_sample_retention_marker_is_bounded_and_audited(self):
        database = DatabaseManager("sqlite:///:memory:")
        Base.metadata.create_all(database.engine)
        now = datetime(2026, 10, 20, tzinfo=timezone.utc)
        uploaded = now - timedelta(days=20)
        payload = {"eventId": "sample-event", "projectId": DEFAULT_PROJECT_ID,
                   "evidence": {"thumbnail": {"1": {"uploadedAt": uploaded.isoformat(),
                                                      "retentionState": "ACTIVE"}}}}
        with database.session() as session:
            session.add(ProjectRecord(project_id=DEFAULT_PROJECT_ID, project_code="sample-test",
                                      display_name="Sample Test", lifecycle_state="ACTIVE"))
            session.add(AlertEventRecord(project_id=DEFAULT_PROJECT_ID, event_id="sample-event", payload=payload))
        until = uploaded + timedelta(days=365)
        retain_alert_evidence(database, project_id=DEFAULT_PROJECT_ID, event_id="sample-event",
                              evidence_type="thumbnail", content_version=1, until=until,
                              actor="operator@example", now=now)
        with database.session() as session:
            row = session.get(AlertEventRecord, (DEFAULT_PROJECT_ID, "sample-event"))
            audits = session.query(PlatformAuditEventRecord).filter_by(action="alert.evidence.retain").all()
        self.assertEqual(row.payload["evidence"]["thumbnail"]["1"]["retentionMarkedBy"], "operator@example")
        self.assertEqual(len(audits), 1)
        database.close()

    def test_retention_skips_legacy_unknown_age_and_reports_bounded_cursor(self):
        database = DatabaseManager("sqlite:///:memory:")
        Base.metadata.create_all(database.engine)
        project_ids = (DEFAULT_PROJECT_ID, "00000000-0000-0000-0000-000000000002")
        with database.session() as session:
            for index, project_id in enumerate(project_ids):
                session.add(ProjectRecord(project_id=project_id, project_code=f"cursor-{index}",
                                          display_name="Cursor", lifecycle_state="ACTIVE"))
                session.add(AlertEventRecord(project_id=project_id, event_id="event", payload={
                    "eventId": "event", "evidence": {"thumbnail": {"1": {
                        "objectStorage": {"provider": "minio", "bucket": "aiyolo-alerts",
                                          "objectKey": f"legacy/{index}.jpg"},
                    }}}}))
        result = cleanup_alert_evidence(database, make_store(), batch_size=1)
        self.assertEqual(result["scanned"], 1)
        self.assertEqual(result["skippedUnknownAge"], 1)
        self.assertEqual(result["nextAfter"], [project_ids[0], "event"])
        next_page = cleanup_alert_evidence(database, make_store(), batch_size=1,
                                           after=tuple(result["nextAfter"]))
        self.assertEqual(next_page["scanned"], 1)
        self.assertIsNone(next_page["nextAfter"])
        database.close()

    def test_retention_never_deletes_shared_object_reference(self):
        database = DatabaseManager("sqlite:///:memory:")
        Base.metadata.create_all(database.engine)
        now = datetime(2026, 10, 20, tzinfo=timezone.utc)
        key = "alerts/shared.jpg"
        shared = {"provider": "minio", "bucket": "aiyolo-alerts", "objectKey": key}
        client = FakeMinio()
        client.objects[("aiyolo-alerts", key)] = b"shared"
        store = make_store(client)
        with database.session() as session:
            session.add(ProjectRecord(project_id=DEFAULT_PROJECT_ID, project_code="shared-test",
                                      display_name="Shared Test", lifecycle_state="ACTIVE"))
            for event_id, state in (("shared-a", "DELETE_PENDING"), ("shared-b", "ACTIVE")):
                session.add(AlertEventRecord(project_id=DEFAULT_PROJECT_ID, event_id=event_id, payload={
                    "eventId": event_id, "evidence": {"thumbnail": {"1": {
                        "uploadedAt": (now - timedelta(days=100)).isoformat(),
                        "retentionState": state,
                        "deleteAfter": (now - timedelta(hours=1)).isoformat(),
                        "objectStorage": shared,
                    }}}}))
        result = cleanup_alert_evidence(database, store, apply=True, now=now)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["retained"], 1)
        self.assertIn(("aiyolo-alerts", key), client.objects)
        database.close()

    def test_tiered_upload_uses_content_qualified_keys_and_signature_validation(self):
        client = FakeMinio()
        store = make_store(client)
        content = b"\xff\xd8\xffjpeg-payload"
        import hashlib
        digest = hashlib.sha256(content).hexdigest()
        reference = store.store_tiered_bytes(
            "project-a", "event:1", "thumbnail", 2, content, "image/jpeg", digest)
        self.assertIn(f"/thumbnail/2/{digest}.jpg", reference["objectKey"])
        self.assertEqual(content, store.read_tiered(
            {"objectStorage": reference, "sha256": digest, "contentType": "image/jpeg"},
            "project-a", "event:1", "thumbnail", 2).content)
        with self.assertRaises(ValueError):
            store.store_tiered_bytes(
                "project-a", "event:1", "thumbnail", 2, content, "image/png", digest)

    def test_tiered_read_rejects_modified_key(self):
        store = make_store(FakeMinio())
        content = b"\xff\xd8\xffjpeg-payload"
        import hashlib
        digest = hashlib.sha256(content).hexdigest()
        reference = store.store_tiered_bytes(
            "project-a", "event:1", "thumbnail", 2, content, "image/jpeg", digest)
        forged = {"objectStorage": {**reference, "objectKey": reference["objectKey"] + "/extra.jpg"},
                  "sha256": digest, "contentType": "image/jpeg"}
        with self.assertRaises(EvidenceStorageError):
            store.read_tiered(forged, "project-a", "event:1", "thumbnail", 2)

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

    def test_object_keys_are_project_partitioned_and_cross_project_reads_fail(self):
        client = FakeMinio()
        store = make_store(client)
        first = store.store_data_url("shared-event", PNG_DATA_URL, "project-a")
        second = store.store_data_url("shared-event", PNG_DATA_URL, "project-b")

        self.assertNotEqual(
            first["objectStorage"]["objectKey"],
            second["objectStorage"]["objectKey"],
        )
        self.assertIn("/projects/project-a/alerts/", first["snapshotUri"])
        self.assertEqual(b"png-bytes", store.read(first, "project-a").content)
        with self.assertRaises(EvidenceStorageError):
            store.read(first, "project-b")

    def test_read_rejects_forged_or_traversal_shaped_object_keys(self):
        client = FakeMinio()
        store = make_store(client)
        reference = store.store_data_url("event-1", PNG_DATA_URL, "project-a")
        forged = {
            **reference,
            "objectStorage": {
                **reference["objectStorage"],
                "objectKey": reference["objectStorage"]["objectKey"].rsplit("/", 1)[0]
                + "/../project-b/evidence.png",
            },
        }

        with self.assertRaises(EvidenceStorageError):
            store.read(forged, "project-a")

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

    def store_data_url(self, event_id, data_url, project_id):
        self.events.append((project_id, event_id, data_url))
        return {
            "snapshotUri": f"/aiyoloapi/projects/{project_id}/alerts/{event_id}/evidence",
            "objectStorage": {
                "provider": "minio",
                "bucket": "aiyolo-alerts",
                "objectKey": f"alerts/{project_id}/{event_id}.png",
                "contentType": "image/png",
                "sizeBytes": 9,
                "sha256": "digest",
            },
        }


class AlertEvidenceMigrationTests(unittest.TestCase):
    def test_same_event_id_in_two_projects_migrates_all_batches_without_feedback_leak(self):
        with tempfile.TemporaryDirectory() as temp:
            database = DatabaseManager(f"sqlite:///{Path(temp) / 'projects.db'}")
            try:
                Base.metadata.create_all(database.engine)
                images = {
                    project: "data:image/png;base64," + base64.b64encode(project.encode()).decode()
                    for project in ("project-a", "project-b")
                }
                with database.session() as session:
                    for project, data_url in images.items():
                        session.add(AlertEventRecord(
                            project_id=project, event_id="same-event", disposition_status="FALSE_POSITIVE",
                            payload={"projectId": "forged", "eventId": "same-event",
                                     "evidence": {"snapshotDataUrl": data_url}},
                        ))
                        session.add(FalsePositiveFeedbackRecord(
                            project_id=project, entry_id="same-feedback", event_id="same-event",
                            action_id=1, payload={"image": data_url, "screenshot": data_url},
                        ))
                store = make_store()
                dry = migrate(database, None, batch_size=1, dry_run=True)
                self.assertEqual(dry, {"scanned": 2, "candidates": 2, "migrated": 0, "feedbackUpdated": 0})
                first = migrate(database, store, batch_size=1, limit=1)
                self.assertEqual(first["migrated"], 1)
                with database.session() as session:
                    untouched = session.get(FalsePositiveFeedbackRecord, ("project-b", "same-feedback"))
                    self.assertEqual(untouched.payload["image"], images["project-b"])
                second = migrate(database, store, batch_size=1)
                self.assertEqual(second["migrated"], 1)
                self.assertEqual(second["feedbackUpdated"], 1)
                self.assertEqual(migrate(database, store, batch_size=1)["migrated"], 0)
                with database.session() as session:
                    references = {}
                    for project in images:
                        event = session.get(AlertEventRecord, (project, "same-event"))
                        feedback = session.get(FalsePositiveFeedbackRecord, (project, "same-feedback"))
                        self.assertEqual(event.payload["projectId"], project)
                        self.assertEqual(feedback.payload["projectId"], project)
                        evidence = event.payload["evidence"]
                        self.assertEqual(feedback.payload["image"], evidence["snapshotUri"])
                        self.assertEqual(store.read(evidence, project).content, project.encode())
                        references[project] = evidence
                    self.assertNotEqual(references["project-a"], references["project-b"])
                    with self.assertRaises(EvidenceStorageError):
                        store.read(references["project-a"], "project-b")
            finally:
                database.close()

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
                event = session.get(AlertEventRecord, (DEFAULT_PROJECT_ID, "event-1"))
                feedback = session.get(FalsePositiveFeedbackRecord, (DEFAULT_PROJECT_ID, "fp-1"))
                self.assertNotIn("snapshotDataUrl", event.payload["evidence"])
                self.assertEqual(event.payload["evidence"]["objectStorage"]["provider"], "minio")
                self.assertNotIn("data:image", str(event.payload))
                self.assertNotIn("data:image", str(feedback.payload))
            database.close()


if __name__ == "__main__":
    unittest.main()
