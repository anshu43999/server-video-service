import unittest
from uuid import uuid4
from urllib.parse import quote

from app.alerts.disposition import alert_disposition_store
from project_api_support import ProjectApiSupport
from test_mobile_alert_control import PRODUCER


class MobileControlApiTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        self.old_database = alert_disposition_store.database_manager
        alert_disposition_store.configure_database(None)
        alert_disposition_store.reset()
        self.start_project_api("m38-control-api")
        self.path = self.project_path + "/alerts"
        self.event_id = "local:control:1"
        self.event_path = self.path + "/" + quote(self.event_id, safe="")
        response = self.client.post(self.path + "/mobile-ingest", headers={**self.headers,
            "X-Mobile-Alert-Contract": "1.0", "X-Mobile-Producer-ID": PRODUCER}, json={
            "eventId": self.event_id, "origin": "MOBILE_IMAGE", "sourceId": "image:control",
            "ruleId": "helmet", "subjectKey": "frame:1", "startedAtUs": 1,
            "lastSeenAtUs": 1, "state": "CONFIRMED", "severity": "MAJOR", "label": "head", "evidence": {}})
        self.assertEqual(202, response.status_code, response.text)
        self.assertNotIn("mobileProducer", response.json()["event"])

    def tearDown(self):
        alert_disposition_store.reset()
        alert_disposition_store.configure_database(self.old_database)
        self.stop_project_api()

    def sync(self, producer=PRODUCER, headers=None):
        return self.client.post(self.path + "/mobile-sync", headers=headers or self.headers,
            json={"events": [{"eventId": self.event_id, "producerId": producer}]})

    def test_backend_first_false_positive_request_and_missing_file_receipt(self):
        response = self.client.post(self.event_path + "/false-positive", headers=self.headers,
                                    json={"expectedRevision": 0})
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("PENDING", response.json()["originalRequest"]["status"])
        state = self.sync().json()["events"][0]
        self.assertEqual(1, state["dispositionRevision"])
        self.assertEqual("FALSE_POSITIVE", state["disposition"]["status"])
        self.assertEqual([], self.sync(str(uuid4())).json()["events"])
        path = self.event_path + "/original-requests/" + state["requests"][0]["requestId"] + "/receipt"
        body = {"producerId": PRODUCER, "status": "UNAVAILABLE", "reason": "local_file_missing"}
        first = self.client.post(path, headers=self.headers, json=body)
        self.assertEqual(200, first.status_code, first.text)
        self.assertEqual(first.json(), self.client.post(path, headers=self.headers, json=body).json())
        denied = self.client.post(path, headers=self.headers, json={**body, "producerId": str(uuid4())})
        self.assertEqual(404, denied.status_code)
        self.assertEqual("local_file_missing", self.client.get(self.event_path, headers=self.headers).json()["originalRequest"]["unavailableReason"])

    def test_confirm_no_original_explicit_request_and_stale_l2(self):
        confirmed = self.client.post(self.event_path + "/acknowledge", headers=self.headers, json={"expectedRevision": 0})
        self.assertEqual(200, confirmed.status_code, confirmed.text)
        self.assertNotIn("originalRequest", confirmed.json())
        op = str(uuid4())
        headers = {**self.headers, "Idempotency-Key": op}
        first = self.client.post(self.event_path + "/original-requests", headers=headers,
                                 json={"operationId": op, "expectedRevision": 1})
        self.assertEqual(200, first.status_code, first.text)
        self.assertEqual("PENDING", first.json()["originalRequest"]["status"])
        replay = self.client.post(self.event_path + "/original-requests", headers=headers,
                                  json={"operationId": op, "expectedRevision": 1})
        self.assertEqual(first.json(), replay.json())
        conflict = self.client.put(self.event_path + "/disposition", headers=headers,
            json={"operationId": op, "expectedRevision": 0, "status": "FALSE_POSITIVE", "actedAtUs": 2})
        self.assertEqual(409, conflict.status_code, conflict.text)
        self.assertEqual("disposition_revision_conflict", conflict.json()["detail"]["code"])

    def test_authentication_validation_and_cross_project_denied(self):
        self.client.cookies.clear()
        self.assertEqual(401, self.client.post(self.path + "/mobile-sync", json={"events": []}).status_code)
        self.assertEqual(422, self.client.post(self.path + "/mobile-sync", headers=self.headers,
            json={"events": [{"eventId": self.event_id, "producerId": "invalid"}]}).status_code)
        self.assertEqual(404, self.client.post("/aiyoloapi/projects/" + str(uuid4()) + "/alerts/mobile-sync",
                                             headers=self.headers, json={"events": []}).status_code)
        missing_cas = self.client.post(self.event_path + "/acknowledge", headers=self.headers, json={})
        self.assertEqual(409, missing_cas.status_code)
