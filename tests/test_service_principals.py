import asyncio
from datetime import datetime, timedelta, timezone
import json
import time
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from starlette.websockets import WebSocketDisconnect

from app import auth
import app.main as main
from app.alerts.disposition import alert_disposition_store
from app.project_auth import set_memory_project, set_memory_membership
from app.service_principals import (ALERTS_INGEST, STREAMS_INGEST, _principals,
    reset_memory_service_principals_for_tests)
from project_api_support import ProjectApiSupport


class ServicePrincipalApiTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        self.start_project_api("machine-project")
        reset_memory_service_principals_for_tests()
        self.addCleanup(reset_memory_service_principals_for_tests)
        self.addCleanup(alert_disposition_store.configure_database, alert_disposition_store.database_manager)
        alert_disposition_store.configure_database(None)
        alert_disposition_store.reset()
        self.addCleanup(alert_disposition_store.reset)
        self.base = self.project_path + "/service-principals"
        self.ingest = self.project_path + "/alerts/mobile-ingest"
        self.other_id = str(uuid4())
        set_memory_project(self.other_id, "other-project")
        self.addCleanup(setattr, main.alert_evidence_store, "enabled", main.alert_evidence_store.enabled)
        main.alert_evidence_store.enabled = False

    def create(self, capabilities=None):
        response = self.client.post(self.base, headers=self.headers, json={
            "displayName": "inspection device", "principalType": "DEVICE",
            "capabilities": capabilities or [ALERTS_INGEST],
            "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        })
        self.assertEqual(201, response.status_code, response.text)
        self.assertEqual("no-store", response.headers["cache-control"])
        return response.json()

    def machine_headers(self, value, **extra):
        return {"Authorization": f"Bearer {value['credential']}",
                "X-Service-Timestamp": str(int(time.time())), "X-Service-Nonce": uuid4().hex, **extra}

    def payload(self, value, **extra):
        return {"eventId": f"service:{value['principalId']}:event-1",
                "sourceId": "camera:back", "ruleId": "ppe", "subjectKey": "frame:1",
                "label": "head", "state": "CONFIRMED", "startedAtUs": 1,
                "lastSeenAtUs": 2, "evidence": {}, **extra}

    def post_event(self, value, **extra):
        return self.client.post(self.ingest, headers=self.machine_headers(value), json=self.payload(value, **extra))

    def test_issue_digest_only_list_audit_and_identity_separation(self):
        value = self.create()
        row = _principals[value["principalId"]]
        self.assertNotEqual(value["credential"], row.credential_digest)
        listed = self.client.get(self.base, headers=self.headers)
        self.assertNotIn("credential", listed.text)
        self.assertNotIn(row.credential_digest, listed.text)
        self.assertIsNone(listed.json()["principals"][0]["lastUsedAt"])
        accepted = self.post_event(value)
        self.assertEqual(202, accepted.status_code, accepted.text)
        self.assertNotIn("event", accepted.json())
        detail = self.client.get(self.base + "/" + value["principalId"], headers=self.headers).json()
        self.assertIsNotNone(detail["lastUsedAt"])
        for path in ["/aiyoloapi/auth/me", "/aiyoloapi/platform/accounts", self.base, self.project_path + "/alerts"]:
            self.assertEqual(401, self.client.get(path, headers=self.machine_headers(value)).status_code)
        audits = self.client.get(self.base + "/" + value["principalId"] + "/audit", headers=self.headers)
        self.assertNotIn(value["credential"], audits.text)
        self.assertNotIn(row.credential_digest, audits.text)
        uses = [a for a in audits.json()["events"] if a["action"] == "service_principal.use"]
        self.assertTrue(uses)
        self.assertIsNone(uses[0]["actorAccountId"])
        self.assertEqual(value["principalId"], uses[0]["actorServicePrincipalId"])

    def test_human_user_cannot_manage_or_write_other_project_owner_can_issue(self):
        user = auth._create_account("ordinary-user", "temporary-password", "operator")
        set_memory_membership(self.project_id, user.account_id, "PROJECT_USER")
        headers = {"Authorization": "Bearer " + auth._issue_session(user)}
        value = self.create()
        self.assertEqual(403, self.client.post(self.base, headers=headers, json={}).status_code)
        self.assertEqual(403, self.client.post(self.base + "/" + value["principalId"] + "/revoke", headers=headers, json={"expectedRevision": 1}).status_code)
        payload = self.payload(value, eventId="human-event")
        self.assertEqual(202, self.client.post(self.ingest, headers=headers, json=payload).status_code)
        self.assertEqual(404, self.client.post(f"/aiyoloapi/projects/{self.other_id}/alerts/mobile-ingest", headers=headers, json=payload).status_code)
        set_memory_membership(self.project_id, user.account_id, "PROJECT_OWNER", revision=2)
        old_headers = self.headers
        try:
            self.headers = headers
            self.create()
        finally:
            self.headers = old_headers

    def test_cross_project_route_body_capability_disposition_and_evidence_denied(self):
        value = self.create()
        headers = self.machine_headers(value)
        cross = self.client.post(f"/aiyoloapi/projects/{self.other_id}/alerts/mobile-ingest", headers=headers, json=self.payload(value))
        self.assertEqual(404, cross.status_code)
        self.assertEqual(409, self.post_event(value, projectId=self.other_id).status_code)
        self.assertEqual(403, self.post_event(value, disposition={"status": "ACKNOWLEDGED", "actedAtUs": 5}).status_code)
        self.assertEqual(422, self.post_event(value, evidence={"objectStorage": {"objectKey": "other-project-secret"}}).status_code)
        self.assertEqual(422, self.post_event(value, eventId="human-event").status_code)
        other = self.create([STREAMS_INGEST])
        self.assertEqual(403, self.post_event(other).status_code)
        self.assertEqual([], alert_disposition_store.list(project_id=self.project_id))
        self.assertEqual([], alert_disposition_store.list(project_id=self.other_id))

    def test_nonce_replay_stale_missing_headers_and_idempotent_event_retry(self):
        value = self.create()
        headers = self.machine_headers(value)
        first = self.client.post(self.ingest, headers=headers, json=self.payload(value))
        self.assertEqual(202, first.status_code)
        second = self.client.post(self.ingest, headers=headers, json=self.payload(value))
        self.assertEqual(409, second.status_code)
        self.assertEqual("service_request_replayed", second.json()["detail"]["code"])
        retry = self.post_event(value)
        self.assertEqual(202, retry.status_code)
        self.assertFalse(retry.json()["created"])
        self.assertEqual(409, self.post_event(value, label="tampered").status_code)
        self.assertEqual(401, self.client.post(self.ingest, headers={"Authorization": headers["Authorization"]}, json=self.payload(value)).status_code)
        for stamp in [int(time.time())-600, int(time.time())+600]:
            self.assertEqual(401, self.client.post(self.ingest, headers=self.machine_headers(value, **{"X-Service-Timestamp": str(stamp)}), json=self.payload(value)).status_code)
        self.assertEqual(1, len(alert_disposition_store.list(project_id=self.project_id)))

    def test_rotation_revocation_expiry_and_revision_conflicts(self):
        value = self.create()
        path = self.base + "/" + value["principalId"]
        rotated = self.client.post(path + "/rotate", headers=self.headers, json={"expectedRevision": 1, "expiresAt": value["expiresAt"]})
        self.assertEqual(200, rotated.status_code, rotated.text)
        new = rotated.json()
        self.assertEqual(401, self.post_event(value).status_code)
        self.assertEqual(202, self.post_event(new).status_code)
        self.assertEqual(409, self.client.post(path + "/revoke", headers=self.headers, json={"expectedRevision": 1}).status_code)
        updated = self.client.patch(path, headers=self.headers, json={"expectedRevision": 2, "capabilities": [STREAMS_INGEST]})
        self.assertEqual(200, updated.status_code)
        self.assertEqual(403, self.post_event(new).status_code)
        revoked = self.client.post(path + "/revoke", headers=self.headers, json={"expectedRevision": 3})
        self.assertEqual(200, revoked.status_code)
        self.assertEqual(401, self.post_event(new).status_code)
        self.assertEqual(409, self.client.post(path + "/rotate", headers=self.headers, json={"expectedRevision": 4, "expiresAt": value["expiresAt"]}).status_code)
        expired = self.create()
        _principals[expired["principalId"]].expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
        self.assertEqual(401, self.post_event(expired).status_code)

    def test_validation_prevents_project_rebinding_privilege_grants_and_nulls(self):
        value = self.create()
        path = self.base + "/" + value["principalId"]
        for fields in [{"projectId": self.other_id}, {"capabilities": ["project.models.assign"]},
                       {"capabilities": []}, {"capabilities": None}, {"displayName": " "},
                       {"expiresAt": "2099-01-01T00:00:00Z"}, {"expiresAt": "2026-10-12T00:00:00"}]:
            result = self.client.patch(path, headers=self.headers, json={"expectedRevision": 1, **fields})
            self.assertEqual(422, result.status_code, result.text)
        self.assertEqual(404, self.client.get(f"/aiyoloapi/projects/{self.other_id}/service-principals/{value['principalId']}", headers=self.headers).status_code)

    def test_suspended_archived_block_use_but_allow_emergency_revocation(self):
        value = self.create()
        for state in ["SUSPENDED", "ARCHIVED"]:
            set_memory_project(self.project_id, "machine-project", lifecycle_state=state)
            self.assertEqual(403, self.post_event(value).status_code)
        revoked = self.client.post(self.base + "/" + value["principalId"] + "/revoke", headers=self.headers, json={"expectedRevision": 1})
        self.assertEqual(200, revoked.status_code)
        set_memory_project(self.project_id, "machine-project", lifecycle_state="ACTIVE")
        self.assertEqual(401, self.post_event(value).status_code)

    def test_ingest_revocation_during_evidence_io_prevents_event_write(self):
        value = self.create()
        main.alert_evidence_store.enabled = True
        def revoke(*args):
            _principals[value["principalId"]].revoked_at = datetime.now(timezone.utc)
            return {"snapshotUri": "unused"}
        with patch.object(main.alert_evidence_store, "store_data_url", side_effect=revoke):
            self.assertEqual(401, self.post_event(value, evidence={"snapshotDataUrl": "data:image/png;base64,AAAA"}).status_code)
        self.assertEqual([], alert_disposition_store.list(project_id=self.project_id))

    def test_machine_evidence_and_human_disposition_retry_is_not_exposed(self):
        value = self.create()
        main.alert_evidence_store.enabled = True
        evidence = {"snapshotDataUrl": "data:image/png;base64,AAAA"}
        with patch.object(main.alert_evidence_store, "store_data_url", return_value={"objectStorage": {"objectKey": "content-key"}}) as store:
            accepted = self.post_event(value, evidence=evidence)
        self.assertEqual(202, accepted.status_code)
        event_id = self.payload(value)["eventId"]
        self.assertTrue(store.call_args.args[0].startswith(event_id + ":"))
        event = alert_disposition_store.get(event_id, self.project_id)
        self.assertIn("/alerts/service%3A", event["evidence"]["snapshotUri"])
        alert_disposition_store.dispose(event_id, "ACKNOWLEDGED", self.account_id, project_id=self.project_id)
        retry = self.post_event(value, evidence=evidence)
        self.assertEqual(202, retry.status_code)
        self.assertNotIn("disposition", retry.text)
        self.assertEqual("ACKNOWLEDGED", alert_disposition_store.get(event_id, self.project_id)["disposition"]["status"])

    def test_websocket_cross_project_and_capability_denied(self):
        value = self.create()
        stream = type("Stream", (), {"ingest_jpeg": AsyncMock()})()
        with patch.dict(main.streams, {(self.project_id, "cam"): stream, (self.other_id, "cam"): stream}):
            for pid, code in [(self.project_id, 4403), (self.other_id, 4404)]:
                with self.assertRaises(WebSocketDisconnect) as error:
                    with self.client.websocket_connect(f"/aiyoloapi/projects/{pid}/streams/cam/ingest", headers=self.machine_headers(value)):
                        pass
                self.assertEqual(code, error.exception.code)
        stream.ingest_jpeg.assert_not_called()

    def test_websocket_revoked_idle_connection_closes_and_frames_stop(self):
        value = self.create([STREAMS_INGEST])
        stream = type("Stream", (), {"ingest_jpeg": AsyncMock()})()
        with patch.dict(main.streams, {(self.project_id, "cam"): stream}):
            with self.client.websocket_connect(self.project_path + "/streams/cam/ingest", headers=self.machine_headers(value)) as socket:
                socket.send_bytes(b"first")
                socket.send_text("ping")
                self.assertTrue(socket.receive_json()["ok"])
                response = self.client.post(self.base + "/" + value["principalId"] + "/revoke", headers=self.headers, json={"expectedRevision": 1})
                self.assertEqual(200, response.status_code)
                self.assertEqual(4401, socket.receive()["code"])
        stream.ingest_jpeg.assert_awaited_once_with(b"first")

    def test_websocket_rotation_capability_and_project_changes_close_connections(self):
        for change, expected_code in [("rotate", 4401), ("capabilities", 4403), ("project", 4403), ("expiry", 4401)]:
            set_memory_project(self.project_id, "machine-project")
            value = self.create([STREAMS_INGEST])
            stream = type("Stream", (), {"ingest_jpeg": AsyncMock()})()
            with patch.dict(main.streams, {(self.project_id, "cam"): stream}):
                with self.client.websocket_connect(self.project_path + "/streams/cam/ingest", headers=self.machine_headers(value)) as socket:
                    path = self.base + "/" + value["principalId"]
                    if change == "rotate":
                        self.assertEqual(200, self.client.post(path + "/rotate", headers=self.headers, json={"expectedRevision": 1, "expiresAt": value["expiresAt"]}).status_code)
                    elif change == "capabilities":
                        self.assertEqual(200, self.client.patch(path, headers=self.headers, json={"expectedRevision": 1, "capabilities": [ALERTS_INGEST]}).status_code)
                    elif change == "project":
                        set_memory_project(self.project_id, "machine-project", lifecycle_state="SUSPENDED")
                    else:
                        _principals[value["principalId"]].expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
                    self.assertEqual(expected_code, socket.receive()["code"])

    def test_human_websocket_membership_removal_reauthorizes(self):
        user = auth._create_account("stream-human", "temporary-password", "operator")
        set_memory_membership(self.project_id, user.account_id, "PROJECT_USER")
        headers = {"Authorization": "Bearer " + auth._issue_session(user)}
        stream = type("Stream", (), {"ingest_jpeg": AsyncMock()})()
        with patch.dict(main.streams, {(self.project_id, "cam"): stream}):
            with self.client.websocket_connect(self.project_path + "/streams/cam/ingest", headers=headers) as socket:
                set_memory_membership(self.project_id, user.account_id, "PROJECT_USER", enabled=False)
                self.assertEqual(4404, socket.receive()["code"])

    def test_websocket_handshake_replay_and_other_device_event_id_are_denied(self):
        value = self.create([STREAMS_INGEST])
        headers = self.machine_headers(value)
        stream = type("Stream", (), {"ingest_jpeg": AsyncMock()})()
        with patch.dict(main.streams, {(self.project_id, "cam"): stream}):
            with self.client.websocket_connect(self.project_path + "/streams/cam/ingest", headers=headers) as socket:
                socket.send_text("ping")
                self.assertTrue(socket.receive_json()["ok"])
            with self.assertRaises(WebSocketDisconnect):
                with self.client.websocket_connect(self.project_path + "/streams/cam/ingest", headers=headers):
                    pass
        first, second = self.create(), self.create()
        self.assertEqual(202, self.post_event(first).status_code)
        self.assertEqual(422, self.post_event(second, eventId=self.payload(first)["eventId"]).status_code)

    def test_websocket_internal_failure_does_not_expose_credentials(self):
        value = self.create([STREAMS_INGEST])
        stream = type("Stream", (), {
            "ingest_jpeg": AsyncMock(side_effect=RuntimeError("internal credential: " + value["credential"]))
        })()
        with patch.dict(main.streams, {(self.project_id, "cam"): stream}):
            with self.client.websocket_connect(self.project_path + "/streams/cam/ingest", headers=self.machine_headers(value)) as socket:
                socket.send_bytes(b"bad-frame")
                closed = socket.receive()
                self.assertEqual(4400, closed["code"])
                self.assertEqual("ingest failed", closed["reason"])
                self.assertNotIn(value["credential"], str(closed))
        self.assertEqual("ingest failed", stream.last_error)


if __name__ == "__main__":
    unittest.main()
