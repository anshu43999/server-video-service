import unittest
import uuid
import hashlib
from concurrent.futures import ThreadPoolExecutor
import threading
from urllib.parse import quote
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.alert_evidence import EvidenceBody, EvidenceStorageError
from app.auth import NORMAL_USER, update_memory_account_for_tests
from app.alerts.disposition import alert_disposition_store
from app.main import alert_evidence_store, app, settings
from app.project_auth import remove_memory_membership, set_memory_membership
from project_api_support import ProjectApiSupport


class MobileAlertIngestApiTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        self.old_database = alert_disposition_store.database_manager
        alert_disposition_store.configure_database(None)
        alert_disposition_store.reset()
        self.start_project_api("mobile-alert-project")
        self.alerts_path = f"{self.project_path}/alerts"

    def tearDown(self):
        alert_disposition_store.reset()
        alert_disposition_store.configure_database(self.old_database)
        self.stop_project_api()

    def payload(self, **overrides):
        value = {
            "eventId": "local:uploaded-helmet:PPE_NO_HELMET:123",
            "ruleId": "PPE_NO_HELMET",
            "sourceId": "image:现场拍照",
            "origin": "MOBILE_IMAGE",
            "subjectKey": "frame:123",
            "label": "head",
            "state": "CONFIRMED",
            "severity": "IMPORTANT",
            "notifySeverity": "IMPORTANT",
            "startedAtUs": 1000,
            "confirmedAtUs": 1000,
            "lastSeenAtUs": 1000,
            "effectiveThresholds": {"minimumConfidence": 0.8},
            "detectionResults": [{"label": "head", "confidence": 0.91}],
            "evidence": {"snapshotDataUrl": "data:image/png;base64,AAAA"},
        }
        value.update(overrides)
        return value

    def upload_tiered(self, *, content=b"\xff\xd8\xfftiered-jpeg", version=1, event_id=None, headers=None):
        event_id = event_id or self.payload()["eventId"]
        path = f"{self.alerts_path}/{quote(event_id, safe='')}/evidence"
        upload_headers = {**self.headers, "X-Mobile-Alert-Contract": "1.0",
                          "Idempotency-Key": str(uuid.uuid4()), **(headers or {})}
        return self.client.post(path, headers=upload_headers, data={
            "evidenceType": "thumbnail", "contentVersion": str(version),
            "sha256": hashlib.sha256(content).hexdigest(),
        }, files={"file": ("image.jpg", content, "image/jpeg")})

    def test_scene_provenance_round_trip_replay_conflict_and_export(self):
        provenance = {"kind": "SCENE", "scene": {"sceneId": "scene-02", "name": "场景02", "revision": 3},
                      "plan": {"planId": "plan-1", "name": "联合相机方案"}, "memberId": "helmet-member",
                      "model": {"modelId": "uploaded-06abc", "name": "安全帽", "version": "2.0.0"}}
        payload = self.payload(evidence={}, origin="MOBILE_CAMERA", sourceId="scene-camera:abc", provenance=provenance)
        headers = {**self.headers, "X-Mobile-Alert-Contract": "1.0"}
        first = self.client.post(f"{self.alerts_path}/mobile-ingest", headers=headers, json=payload)
        self.assertEqual(202, first.status_code, first.text)
        self.assertEqual(provenance, first.json()["event"]["provenance"])
        self.assertEqual(provenance["model"], first.json()["event"]["model"])
        event_path = f"{self.alerts_path}/{quote(payload['eventId'], safe='')}"
        self.assertEqual(provenance, self.client.get(event_path, headers=self.headers).json()["provenance"])
        self.assertEqual(provenance, self.client.get(self.alerts_path, headers=self.headers).json()["events"][0]["provenance"])
        replay = self.client.post(f"{self.alerts_path}/mobile-ingest", headers=headers, json=payload)
        self.assertFalse(replay.json()["created"])
        for changed in ({**provenance, "scene": {**provenance["scene"], "name": "重命名后"}},
                        {**provenance, "model": {**provenance["model"], "version": "3.0.0"}}, None):
            conflict = self.client.post(f"{self.alerts_path}/mobile-ingest", headers=headers,
                                        json={**payload, "provenance": changed})
            self.assertEqual(409, conflict.status_code, conflict.text)
        self.client.post(f"{event_path}/false-positive", headers=self.headers, json={"actedAtUs": 3000})
        exported = self.client.get(f"{self.alerts_path}/false-positives/export", headers=self.headers).json()
        self.assertEqual(provenance, exported["entries"][0]["provenance"])

    def test_provenance_validation_and_old_envelope_compatibility(self):
        model = {"modelId": "uploaded-06abc", "name": "安全帽", "version": "2.0.0"}
        for provenance in ({"kind": "SCENE", "model": model},
                           {"kind": "STANDALONE", "model": model, "memberId": "x"},
                           {"kind": "STANDALONE", "model": {**model, "name": " "}},
                           {"kind": "STANDALONE", "model": {**model, "name": "x" * 257}},
                           {"kind": "STANDALONE", "model": model, "projectId": "other-project"}):
            response = self.client.post(f"{self.alerts_path}/mobile-ingest", headers=self.headers,
                                        json=self.payload(evidence={}, provenance=provenance))
            self.assertEqual(422, response.status_code, response.text)
        response = self.client.post(f"{self.alerts_path}/mobile-ingest", headers=self.headers,
                                    json=self.payload(evidence={}, projectId="other-project",
                                        provenance={"kind": "STANDALONE", "model": model}))
        self.assertIn(response.status_code, (403, 409, 422))
        self.assertEqual([], alert_disposition_store.list(project_id=self.project_id))
        for extra in ({}, {"eventId": "standalone:1", "provenance": {"kind": "STANDALONE", "model": model}}):
            response = self.client.post(f"{self.alerts_path}/mobile-ingest", headers=self.headers,
                                        json=self.payload(evidence={}, **extra))
            self.assertEqual(202, response.status_code, response.text)

    def test_tiered_evidence_upload_replay_conflict_and_authenticated_read(self):
        self.client.post(f"{self.alerts_path}/mobile-ingest", headers=self.headers,
                         json=self.payload(evidence={}))
        self.addCleanup(setattr, alert_evidence_store, "enabled", alert_evidence_store.enabled)
        alert_evidence_store.enabled = True
        stored = {"provider": "minio", "bucket": "aiyolo-alerts",
                  "objectKey": "alerts/test/events/test/thumbnail/1/digest.jpg",
                  "contentType": "image/jpeg", "sizeBytes": 17,
                  "sha256": hashlib.sha256(b"\xff\xd8\xfftiered-jpeg").hexdigest()}
        with patch.object(alert_evidence_store, "store_tiered_bytes", return_value=stored) as write, \
             patch.object(alert_evidence_store, "read_tiered", return_value=EvidenceBody(b"image", "image/jpeg")) as read:
            first = self.upload_tiered()
            self.assertEqual(len(alert_disposition_store.list(project_id=self.project_id)), 1)
            persisted = alert_disposition_store.get(self.payload()["eventId"], self.project_id)
            self.assertEqual(persisted["eventId"], self.payload()["eventId"])
            self.assertIn("thumbnail", persisted["evidence"])
            reference = persisted["evidence"]["thumbnail"]["1"]
            self.assertEqual(reference["retentionState"], "ACTIVE")
            self.assertTrue(reference["uploadedAt"].endswith("+00:00"))
            replay = self.upload_tiered()
            self.assertEqual(first.status_code, 201, first.text)
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(first.json(), replay.json())
            replayed = alert_disposition_store.get(self.payload()["eventId"], self.project_id)
            self.assertEqual(replayed["evidence"]["thumbnail"]["1"]["uploadedAt"], reference["uploadedAt"])
            self.assertEqual(first.json()["evidence"]["contentVersion"], 1)
            image = self.client.get(first.json()["evidence"]["uri"], headers=self.headers)
            self.assertEqual(image.status_code, 200)
            self.assertEqual(image.content, b"image")
            conflict = self.upload_tiered(content=b"\xff\xd8\xffdifferent")
            self.assertEqual(conflict.status_code, 409)
            write.assert_called_once()
            read.assert_called_once()

    def test_capture_display_metadata_survives_fact_replay_and_tiered_upload_without_changing_image(self):
        overlay = {"version": 1, "capturedAtUs": 1000, "bakedIn": False,
                   "detections": [{"label": "head", "confidence": .91,
                                   "box": {"left": .1, "top": .2, "right": .6, "bottom": .8}}]}
        payload = self.payload(evidence={"capturedAtUs": 1000, "displayOverlay": overlay})
        headers = {**self.headers, "X-Mobile-Alert-Contract": "1.0", "Idempotency-Key": str(uuid.uuid4())}
        for _ in range(2):
            response = self.client.post(f"{self.alerts_path}/mobile-ingest", headers=headers, json=payload)
            self.assertEqual(202, response.status_code, response.text)
        self.addCleanup(setattr, alert_evidence_store, "enabled", alert_evidence_store.enabled)
        alert_evidence_store.enabled = True
        content = b"\xff\xd8\xffunchanged-jpeg"
        stored = {"provider": "minio", "bucket": "aiyolo-alerts", "objectKey": "alerts/test/overlay.jpg",
                  "contentType": "image/jpeg", "sizeBytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        with patch.object(alert_evidence_store, "store_tiered_bytes", return_value=stored) as write:
            response = self.upload_tiered(content=content)
            self.assertEqual(201, response.status_code, response.text)
            self.assertIn(content, write.call_args.args)
        public = self.client.get(f"{self.alerts_path}/{quote(payload['eventId'], safe='')}", headers=self.headers)
        self.assertEqual(200, public.status_code, public.text)
        self.assertEqual(overlay, public.json()["evidence"]["displayOverlay"])

    def test_tiered_evidence_rejects_missing_event_and_fake_signature(self):
        self.addCleanup(setattr, alert_evidence_store, "enabled", alert_evidence_store.enabled)
        alert_evidence_store.enabled = True
        missing = self.upload_tiered(event_id="local:not-ingested:1")
        self.assertEqual(missing.status_code, 404)
        self.client.post(f"{self.alerts_path}/mobile-ingest", headers=self.headers,
                         json=self.payload(evidence={}))
        fake = self.upload_tiered(content=b"not really an image")
        self.assertEqual(fake.status_code, 415)
        self.assertEqual(fake.json()["detail"]["code"], "unsupported_media_type")

    def test_tiered_storage_timeout_has_no_reference_and_same_key_can_retry(self):
        self.client.post(f"{self.alerts_path}/mobile-ingest", headers=self.headers, json=self.payload(evidence={}))
        self.addCleanup(setattr, alert_evidence_store, "enabled", alert_evidence_store.enabled)
        alert_evidence_store.enabled = True
        headers = {"Idempotency-Key": str(uuid.uuid4())}
        stored = {"provider": "minio", "bucket": "aiyolo-alerts", "objectKey": "test/retry.jpg"}
        with patch.object(alert_evidence_store, "store_tiered_bytes",
                          side_effect=[EvidenceStorageError("storage timeout"), stored]) as write:
            failed = self.upload_tiered(headers=headers)
            self.assertEqual(503, failed.status_code)
            self.assertEqual("storage_unavailable", failed.json()["detail"]["code"])
            self.assertTrue(failed.json()["detail"]["retryable"])
            self.assertEqual({}, alert_disposition_store.get(self.payload()["eventId"], self.project_id)["evidence"])
            retry = self.upload_tiered(headers=headers)
            replay = self.upload_tiered(headers=headers)
            self.assertEqual(201, retry.status_code)
            self.assertEqual(200, replay.status_code)
            self.assertEqual(retry.json(), replay.json())
            self.assertEqual(2, write.call_count)

    def test_v1_rejects_inline_paths_keys_and_legacy_disposition_before_writes(self):
        headers = {**self.headers, "X-Mobile-Alert-Contract": "1.0"}
        for evidence in ({"snapshotDataUrl": "data:image/png;base64,AAAA"},
                         {"nested": {"image": "data:image/png;base64,AAAA"}},
                         {"localPath": "C:/private/image.jpg"}, {"objectStorage": {"objectKey": "secret"}}):
            with self.subTest(evidence=evidence):
                response = self.client.post(f"{self.alerts_path}/mobile-ingest", headers=headers,
                                            json=self.payload(evidence=evidence))
                self.assertEqual(422, response.status_code, response.text)
        response = self.client.post(f"{self.alerts_path}/mobile-ingest", headers=headers,
            json=self.payload(evidence={}, disposition={"status": "ACKNOWLEDGED", "actedAtUs": 2000}))
        self.assertEqual(422, response.status_code)
        self.assertEqual([], alert_disposition_store.list(project_id=self.project_id))

    def test_v1_identity_conflicts_do_not_mutate_canonical_event(self):
        headers = {**self.headers, "X-Mobile-Alert-Contract": "1.0"}
        payload = self.payload(evidence={})
        first = self.client.post(f"{self.alerts_path}/mobile-ingest", headers=headers, json=payload)
        self.assertEqual(202, first.status_code, first.text)
        for key, value in (("sourceId", "image:other"), ("ruleId", "other-rule"),
                           ("subjectKey", "other-subject"), ("startedAtUs", 999)):
            with self.subTest(key=key):
                conflict = self.client.post(f"{self.alerts_path}/mobile-ingest", headers=headers,
                                            json={**payload, key: value})
                self.assertEqual(409, conflict.status_code, conflict.text)
                self.assertEqual("event_identity_conflict", conflict.json()["detail"]["code"])
        replay = self.client.post(f"{self.alerts_path}/mobile-ingest", headers=headers, json=payload)
        self.assertFalse(replay.json()["created"])
        self.assertEqual(first.json()["event"], replay.json()["event"])

    def test_evidence_uploaded_after_false_positive_repairs_feedback_reference(self):
        event_id = self.payload()["eventId"]
        self.client.post(f"{self.alerts_path}/mobile-ingest", headers=self.headers,
                         json=self.payload(evidence={}))
        marked = self.client.post(
            f"{self.alerts_path}/{quote(event_id, safe='')}/false-positive",
            headers=self.headers, json={"actedAtUs": 2000},
        )
        self.assertEqual(marked.status_code, 200, marked.text)
        before = alert_disposition_store.feedback(self.project_id)[0]
        self.assertEqual(before["evidenceUnavailableReason"], "evidence_not_uploaded")
        stored = {"provider": "minio", "bucket": "aiyolo-alerts", "objectKey": "test/unique.jpg"}
        self.addCleanup(setattr, alert_evidence_store, "enabled", alert_evidence_store.enabled)
        alert_evidence_store.enabled = True
        with patch.object(alert_evidence_store, "store_tiered_bytes", return_value=stored), \
             patch.object(alert_evidence_store, "read_tiered", return_value=EvidenceBody(b"image", "image/jpeg")):
            uploaded = self.upload_tiered()
            self.assertEqual(uploaded.status_code, 201, uploaded.text)
            self.assertNotIn("base64", uploaded.text)
            entry = alert_disposition_store.feedback(self.project_id)[0]
            self.assertIsNone(entry["evidenceUnavailableReason"])
            self.assertEqual(entry["image"], uploaded.json()["evidence"]["uri"])
            image = self.client.get(entry["image"], headers=self.headers)
            self.assertEqual(image.status_code, 200)
            self.assertEqual(image.content, b"image")
            exported = self.client.get(f"{self.alerts_path}/false-positives/export", headers=self.headers)
            self.assertEqual(exported.status_code, 200)
            self.assertEqual(exported.json()["entries"][0]["image"], entry["image"])

    def test_tiered_evidence_rejects_digest_mismatch_and_oversize(self):
        self.addCleanup(setattr, alert_evidence_store, "enabled", alert_evidence_store.enabled)
        alert_evidence_store.enabled = True
        self.client.post(f"{self.alerts_path}/mobile-ingest", headers=self.headers,
                         json=self.payload(evidence={}))
        content = b"\xff\xd8\xffvalid-but-wrong-digest"
        # The helper computes the digest, so explicitly override the form field for this vector.
        mismatch = self.client.post(
            f"{self.alerts_path}/{quote(self.payload()['eventId'], safe='')}/evidence",
            headers={**self.headers, "X-Mobile-Alert-Contract": "1.0", "Idempotency-Key": str(uuid.uuid4())},
            data={"evidenceType": "thumbnail", "contentVersion": "1", "sha256": "0" * 64},
            files={"file": ("image.jpg", content, "image/jpeg")},
        )
        self.assertEqual(mismatch.status_code, 422)
        oversized = self.upload_tiered(content=b"\xff\xd8\xff" + b"x" * (128 * 1024))
        self.assertEqual(oversized.status_code, 413)

    def test_tiered_evidence_upload_requires_project_authorization(self):
        self.client.post(f"{self.alerts_path}/mobile-ingest", headers=self.headers,
                         json=self.payload(evidence={}))
        content = b"\xff\xd8\xffimage"
        path = f"{self.alerts_path}/{quote(self.payload()['eventId'], safe='')}/evidence"
        self.client.cookies.clear()
        response = self.client.post(path, headers={
            "X-Mobile-Alert-Contract": "1.0", "Idempotency-Key": str(uuid.uuid4()),
        }, data={"evidenceType": "thumbnail", "contentVersion": "1",
                "sha256": hashlib.sha256(content).hexdigest()},
            files={"file": ("image.jpg", content, "image/jpeg")})
        self.assertEqual(response.status_code, 401)

    def test_tiered_evidence_upload_is_safe_under_concurrent_version_conflict(self):
        self.client.post(f"{self.alerts_path}/mobile-ingest", headers=self.headers,
                         json=self.payload(evidence={}))
        self.addCleanup(setattr, alert_evidence_store, "enabled", alert_evidence_store.enabled)
        alert_evidence_store.enabled = True
        barrier = threading.Barrier(2)
        removed = []

        def write(project_id, event_id, evidence_type, version, content, content_type, digest):
            barrier.wait(timeout=5)
            return {"provider": "minio", "bucket": "aiyolo-alerts",
                    "objectKey": f"test/{evidence_type}/{version}/{digest}.jpg",
                    "contentType": content_type, "sizeBytes": len(content), "sha256": digest}

        with patch.object(alert_evidence_store, "store_tiered_bytes", side_effect=write), \
             patch.object(alert_evidence_store, "remove_tiered", side_effect=lambda obj: removed.append(obj["objectKey"])):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self.upload_tiered, content=content)
                           for content in (b"\xff\xd8\xfffirst", b"\xff\xd8\xffsecond")]
                responses = [future.result(timeout=15) for future in futures]
        self.assertEqual(sorted(response.status_code for response in responses), [201, 409])
        self.assertEqual(len(alert_disposition_store.get(self.payload()["eventId"], self.project_id)
                             ["evidence"]["thumbnail"]), 1)
        self.assertEqual(len(removed), 1)

    def test_tiered_evidence_upload_obeys_revoked_membership(self):
        self.client.post(f"{self.alerts_path}/mobile-ingest", headers=self.headers,
                         json=self.payload(evidence={}))
        update_memory_account_for_tests(self.account_id, platform_role=NORMAL_USER)
        content = b"\xff\xd8\xffimage"
        path = f"{self.alerts_path}/{quote(self.payload()['eventId'], safe='')}/evidence"
        remove_memory_membership(self.project_id, self.account_id)
        denied = self.client.post(path, headers={**self.headers, "X-Mobile-Alert-Contract": "1.0",
                                                "Idempotency-Key": str(uuid.uuid4())},
                                  data={"evidenceType": "thumbnail", "contentVersion": "1",
                                        "sha256": hashlib.sha256(content).hexdigest()},
                                  files={"file": ("image.jpg", content, "image/jpeg")})
        self.assertIn(denied.status_code, {401, 404})
        set_memory_membership(self.project_id, self.account_id, "PROJECT_OWNER")

    def test_removed_legacy_approval_field_is_rejected_without_writing_event(self):
        response = self.client.post(
            f"{self.alerts_path}/mobile-ingest",
            headers=self.headers,
            json=self.payload(legacyApproval={"approvalId": "old-data"}),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(alert_disposition_store.list(project_id=self.project_id), [])

    def test_retired_approval_endpoints_are_not_registered(self):
        self.assertEqual(self.client.get("/aiyoloapi/mobile-legacy-approval/config").status_code, 404)
        self.assertEqual(self.client.get("/aiyoloapi/platform/mobile-legacy-approvals").status_code, 404)

    @patch.object(alert_evidence_store, "validate")
    @patch.object(alert_evidence_store, "store_data_url")
    def test_mobile_ingest_requires_mobile_token_and_accepts_colon_id(self, store_data_url, validate_store):
        # This API test supplies a synthetic object upload. Its anonymous client
        # also starts the lifespan, which must use the same isolated storage fixture.
        self.addCleanup(setattr, alert_evidence_store, "enabled", alert_evidence_store.enabled)
        alert_evidence_store.enabled = True
        store_data_url.return_value = {
            "snapshotUri": (
                f"{self.alerts_path}/local%3Auploaded-helmet%3APPE_NO_HELMET%3A123/evidence"
            ),
            "objectStorage": {
                "provider": "minio",
                "bucket": "aiyolo-alerts",
                "objectKey": "alerts/ab/event.png",
                "contentType": "image/png",
                "sizeBytes": 3,
                "sha256": "abc",
            },
        }
        with TestClient(app) as anonymous:
            denied = anonymous.post(
                f"{self.alerts_path}/mobile-ingest", json=self.payload()
            )
        validate_store.assert_called_once()
        self.assertEqual(denied.status_code, 401)
        response = self.client.post(
            f"{self.alerts_path}/mobile-ingest",
            headers=self.headers,
            json=self.payload(),
        )
        self.assertEqual(response.status_code, 202)
        event = response.json()["event"]
        self.assertEqual(event["eventId"], "local:uploaded-helmet:PPE_NO_HELMET:123")
        self.assertEqual(event["origin"], "MOBILE_IMAGE")
        self.assertTrue(event["evidence"]["snapshotUri"].endswith("/evidence"))
        self.assertEqual(event["evidence"]["objectStorage"]["provider"], "minio")
        self.assertNotIn("snapshotDataUrl", event["evidence"])
        self.assertNotIn("data:image", str(event))
        store_data_url.assert_called_once()
        with patch.object(
            alert_evidence_store, "read", return_value=EvidenceBody(b"png-bytes", "image/png")
        ) as read:
            image = self.client.get(
                event["evidence"]["snapshotUri"],
                headers=self.headers,
            )
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.content, b"png-bytes")
        self.assertEqual(image.headers["content-type"], "image/png")
        read.assert_called_once()

    @patch.object(
        alert_evidence_store,
        "store_data_url",
        side_effect=EvidenceStorageError("MinIO unavailable"),
    )
    def test_mobile_ingest_does_not_fall_back_to_database_when_minio_fails(self, _):
        self.addCleanup(setattr, alert_evidence_store, "enabled", alert_evidence_store.enabled)
        alert_evidence_store.enabled = True
        response = self.client.post(
            f"{self.alerts_path}/mobile-ingest",
            headers=self.headers,
            json=self.payload(),
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(alert_disposition_store.list(project_id=self.project_id), [])

    def test_legacy_mobile_payload_infers_origin_from_source(self):
        payload = self.payload(sourceId="camera:back")
        payload.pop("origin")
        response = self.client.post(
            f"{self.alerts_path}/mobile-ingest",
            headers=self.headers,
            json=payload,
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["event"]["origin"], "MOBILE_CAMERA")

    def test_local_inline_evidence_is_readable_from_admin_evidence_endpoint(self):
        self.addCleanup(setattr, alert_evidence_store, "enabled", alert_evidence_store.enabled)
        alert_evidence_store.enabled = False
        response = self.client.post(
            f"{self.alerts_path}/mobile-ingest",
            headers=self.headers,
            json=self.payload(),
        )
        self.assertEqual(response.status_code, 202)
        event = response.json()["event"]

        image = self.client.get(
            f"{self.alerts_path}/{event['eventId']}/evidence",
            headers=self.headers,
        )
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.content, b"\x00\x00\x00")
        self.assertEqual(image.headers["content-type"], "image/png")

    def test_ingest_is_idempotent_and_preserves_disposition_history(self):
        first = self.client.post(f"{self.alerts_path}/mobile-ingest", headers=self.headers, json=self.payload(
            disposition={"status": "ACKNOWLEDGED", "actor": "local-operator", "actedAtUs": 2000},
        ))
        self.assertEqual(first.status_code, 202)
        second = self.client.post(f"{self.alerts_path}/mobile-ingest", headers=self.headers, json=self.payload(
            detectionResults=[{"label": "head", "confidence": 0.95}],
            disposition={"status": "ACKNOWLEDGED", "actor": "local-operator", "actedAtUs": 2000},
        ))
        self.assertEqual(second.status_code, 202)
        event = second.json()["event"]
        self.assertEqual(event["disposition"]["status"], "ACKNOWLEDGED")
        self.assertEqual(event["disposition"]["actor"], self.account_id)
        self.assertEqual(len(event["disposition"]["history"]), 1)
        listed = self.client.get(self.alerts_path, headers=self.headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["events"]), 1)

    def test_mobile_token_cannot_use_admin_disposition_endpoint(self):
        response = self.client.post(
            f"{self.alerts_path}/mobile-ingest",
            headers=self.headers,
            json=self.payload(),
        )
        self.assertEqual(response.status_code, 202)
        denied = self.client.post(
            f"{self.alerts_path}/local:uploaded-helmet:PPE_NO_HELMET:123/acknowledge",
            headers=self.headers,
            json={},
        )
        self.assertEqual(denied.status_code, 200)

    def test_v1_fact_without_disposition_stays_open_and_delta_is_idempotent(self):
        payload = self.payload(evidence={})
        first = self.client.post(f"{self.alerts_path}/mobile-ingest", headers=self.headers, json=payload)
        replay = self.client.post(f"{self.alerts_path}/mobile-ingest", headers=self.headers, json=payload)
        self.assertEqual(202, first.status_code)
        self.assertEqual(202, replay.status_code)
        self.assertEqual("OPEN", replay.json()["event"]["disposition"]["status"])

        operation = str(uuid.uuid4())
        body = {"operationId": operation, "status": "ACKNOWLEDGED", "actedAtUs": 2000}
        headers = {**self.headers, "Idempotency-Key": operation}
        path = f"{self.alerts_path}/{payload['eventId']}/disposition"
        delta = self.client.put(path, headers=headers, json=body)
        duplicate = self.client.put(path, headers=headers, json=body)
        self.assertEqual(200, delta.status_code)
        self.assertEqual(200, duplicate.status_code)
        event = alert_disposition_store.get(payload["eventId"], self.project_id)
        self.assertEqual("ACKNOWLEDGED", event["disposition"]["status"])
        self.assertEqual(1, len(event["disposition"]["history"]))
        conflict = self.client.put(path, headers=headers, json={**body, "status": "FALSE_POSITIVE"})
        self.assertEqual(409, conflict.status_code)
        self.assertEqual("idempotency_conflict", conflict.json()["detail"]["code"])

    def test_v1_disposition_before_fact_is_retryable_without_orphan(self):
        operation = str(uuid.uuid4())
        response = self.client.put(f"{self.alerts_path}/local:missing:123/disposition",
            headers={**self.headers, "Idempotency-Key": operation},
            json={"operationId": operation, "status": "ACKNOWLEDGED", "actedAtUs": 2000})
        self.assertEqual(409, response.status_code)
        self.assertEqual("event_not_ingested", response.json()["detail"]["code"])
        self.assertTrue(response.json()["detail"]["retryable"])
        self.assertEqual([], alert_disposition_store.list(project_id=self.project_id))


if __name__ == "__main__":
    unittest.main()
