"""M33-T15: production-routed, two-project authorization golden matrix.

All identities are real sessions/issued device credentials. Storage and media
backends are isolated in-process; no live MinIO, MediaMTX or business DB writes.
"""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from uuid import uuid4

from fastapi import FastAPI
from starlette.websockets import WebSocketDisconnect
import uvicorn

import app.main as main
from app.alert_evidence import AlertEvidenceStore, EvidenceStorageError
from app.alerts.delivery import AlertDeliveryService
from app.alerts.disposition import AlertDispositionStore
from app.alerts.rules import RuleRegistry
from app.alerts.verification import AlertVerificationStore
from app.config import settings
from app.model_catalog import ModelCatalog
from app.model_parameters import ModelParameterStore
from app.media_authorization import MediaAuthorizationRequest, authorize_media_read
from app.project_business import _memory_model_assignments
from app.project_auth import memory_platform_entry_audits
from app.project_model_assignments import ProjectModelAssignments
from app.project_scenes import ProjectScenes
from app.service_principals import ALERTS_INGEST, STREAMS_INGEST, reset_memory_service_principals_for_tests
from app.stream_config import StreamConfigStore
from project_api_support import ProjectApiSupport
from test_alert_evidence import FakeMinio


class TrackedMinio(FakeMinio):
    def __init__(self):
        super().__init__()
        self.read_keys = []

    def get_object(self, bucket, object_key):
        self.read_keys.append(object_key)
        return super().get_object(bucket, object_key)


class CrossProjectGoldenMatrix(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="m33-t15-")
        self.addCleanup(self.temp.cleanup)
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        reset_memory_service_principals_for_tests()
        self.addCleanup(reset_memory_service_principals_for_tests)

        models = Path(self.temp.name) / "models"
        models.mkdir()
        entries = []
        for name in ("model-alpha", "model-beta"):
            artifact = models / (name + ".pt")
            artifact.write_bytes(name.encode())
            sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
            entries.append({"modelId": name, "name": name, "version": "1.0.0", "scenario": name,
                            "purpose": "golden test", "runtime": "server-pt", "format": "pt",
                            "path": "models/" + artifact.name, "sizeBytes": artifact.stat().st_size,
                            "sha256": sha256, "labels": ["head"], "status": "PUBLISHED",
                            "releaseEligible": True,
                            "artifacts": [{"artifactId": "server", "format": "pt", "platform": "server",
                                           "path": "models/" + artifact.name,
                                           "sizeBytes": artifact.stat().st_size, "sha256": sha256}]})
        registry = models / "registry.json"
        registry.write_text(json.dumps({"activeServerModel": None, "models": entries}), encoding="utf-8")
        catalog = ModelCatalog(registry)
        profiles = ModelParameterStore(models / "profiles.json")
        configs = StreamConfigStore(None)
        assignments = ProjectModelAssignments(None, catalog, profiles, configs)
        self.minio = TrackedMinio()
        evidence = AlertEvidenceStore(endpoint="minio.internal:9000", access_key="test",
                                      secret_key="test", client=self.minio)
        for name, value in (
            ("model_catalog", catalog), ("model_parameter_store", profiles),
            ("stream_config_store", configs), ("streams", main.ProjectStreamRegistry()),
            ("project_model_assignments", assignments),
            ("project_scenes", ProjectScenes(None, catalog, assignments)),
            ("alert_disposition_store", AlertDispositionStore(None)),
            ("alert_verification_store", AlertVerificationStore()),
            ("alert_delivery", AlertDeliveryService()), ("rule_registry", RuleRegistry()),
            ("alert_evidence_store", evidence),
        ):
            self.patches.enter_context(patch.object(main, name, value))
        self.patches.enter_context(patch.dict(_memory_model_assignments, {}, clear=True))
        for name, value in (
            ("legacy_project_id", None), ("legacy_project_until", None),
        ):
            self.patches.enter_context(patch.object(settings, name, value))

        self.start_project_api("matrix-alpha")
        self.addCleanup(self._close_streams)
        self.a = self.project_id
        self.paths = {"a": self.project_path}
        self.admin = self.headers
        self.accounts = {name: self._account(name) for name in
                         ("owner-a", "owner-b", "user-a", "user-b", "outsider", "disabled")}
        self.b = self._project("matrix-beta", "owner-b")
        self.paths["b"] = f"/aiyoloapi/projects/{self.b}"
        for key, project, role in (
            ("owner-a", self.a, "PROJECT_OWNER"), ("user-a", self.a, "PROJECT_USER"),
            ("user-b", self.b, "PROJECT_USER"), ("disabled", self.b, "PROJECT_USER"),
        ):
            response = self.client.post(f"/aiyoloapi/projects/{project}/members", headers=self.admin,
                                        json={"accountId": self.accounts[key]["accountId"], "projectRole": role})
            self.assertEqual(201, response.status_code, response.text)
        self.tokens = {name: self._login(name) for name in self.accounts}
        disabled = self.client.patch(
            f"/aiyoloapi/platform/accounts/{self.accounts['disabled']['accountId']}",
            headers=self.admin, json={"expectedRevision": 1, "enabled": False})
        self.assertEqual(200, disabled.status_code, disabled.text)
        self.missing = str(uuid4())

    def _close_streams(self):
        for stream in list(main.streams.values()):
            asyncio.run(stream.close())
        main.streams.clear()

    def _account(self, name):
        response = self.client.post("/aiyoloapi/platform/accounts", headers=self.admin,
                                    json={"username": "matrix-" + name,
                                          "password": "matrix-test-password", "platformRole": "NORMAL_USER"})
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def _login(self, name):
        response = self.client.post("/aiyoloapi/auth/login", json={
            "username": "matrix-" + name, "password": "matrix-test-password"})
        self.assertEqual(200, response.status_code, response.text)
        return {"Authorization": "Bearer " + response.json()["accessToken"]}

    def _project(self, code, owner):
        response = self.client.post("/aiyoloapi/projects", headers=self.admin,
            json={"projectCode": code, "displayName": code,
                  "ownerAccountId": self.accounts[owner]["accountId"]})
        self.assertEqual(201, response.status_code, response.text)
        return response.json()["projectId"]

    def _hidden(self, person, suffix="", *, method="get", json_body=None):
        """A real foreign project must be indistinguishable from an unknown ID."""
        headers = self.tokens[person]
        call = getattr(self.client, method)
        kwargs = {"headers": headers}
        if json_body is not None:
            kwargs["json"] = json_body
        foreign = call(self.paths["b"] + suffix, **kwargs)
        absent = call(f"/aiyoloapi/projects/{self.missing}" + suffix, **kwargs)
        self.assertEqual(404, foreign.status_code, (person, suffix, foreign.text))
        self.assertEqual((absent.status_code, absent.json()), (foreign.status_code, foreign.json()))

    def _seed_streams(self):
        self.model_ids = {}
        for project, owner in ((self.a, "owner-a"), (self.b, "owner-b")):
            model = "model-alpha" if project == self.a else "model-beta"
            assigned = self._assign(project, owner, model)
            member_id = "member-" + model
            scene = self.client.post(f"/aiyoloapi/projects/{project}/scenes",
                headers=self.tokens[owner], json={
                    "sceneId": "camera-safety", "name": "Camera safety",
                    "inputTypes": ["video"], "enabled": True, "expectedRevision": 0,
                    "models": [{"memberId": member_id, "projectModelId": assigned["projectModelId"],
                                "position": 0, "inputTypes": ["video"], "execution": "single"}],
                    "plans": [{"planId": "default", "name": "Default", "inputTypes": ["video"],
                               "memberIds": [member_id], "execution": "single", "enabled": True}],
                })
            self.assertEqual(201, scene.status_code, scene.text)
            approved = self.client.post(
                f"/aiyoloapi/projects/{project}/scenes/camera-safety/approval",
                headers=self.tokens[owner],
                json={"approved": True, "expectedRevision": 1, "reason": "isolated test"},
            )
            self.assertEqual(200, approved.status_code, approved.text)
            response = self.client.post(f"/aiyoloapi/projects/{project}/streams",
                headers=self.tokens[owner], json={"stream_id": "shared-camera", "enabled": False,
                    "sceneId": "camera-safety", "planId": "default", "sceneRevision": 2})
            self.assertEqual(201, response.status_code, response.text)
            self.model_ids[project] = assigned["projectModelId"]

    def _assign(self, project, owner, model):
        response = self.client.put(f"/aiyoloapi/projects/{project}/model-assignments",
            headers=self.tokens[owner], json={"modelId": model, "modelVersion": "1.0.0",
                "target": "pc", "parameterRevision": 0,
                "enabled": True, "expectedRevision": 0})
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def _alert(self, person, project, event_id, image):
        payload = {"eventId": event_id, "ruleId": "rule", "sourceId": "shared-camera",
                   "subjectKey": "frame:1", "label": "head", "state": "CONFIRMED",
                   "startedAtUs": 1, "confirmedAtUs": 1, "lastSeenAtUs": 1,
                   "evidence": {"snapshotDataUrl": "data:image/png;base64," +
                                base64.b64encode(image).decode()}}
        response = self.client.post(f"/aiyoloapi/projects/{project}/alerts/mobile-ingest",
                                    headers=self.tokens[person], json=payload)
        self.assertEqual(202, response.status_code, response.text)
        return response.json()

    def _device(self, owner, project, capabilities=(ALERTS_INGEST,)):
        response = self.client.post(f"/aiyoloapi/projects/{project}/service-principals",
            headers=self.tokens[owner], json={"displayName": "golden device", "principalType": "DEVICE",
                "capabilities": list(capabilities),
                "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    @staticmethod
    def _device_headers(device):
        return {"Authorization": "Bearer " + device["credential"],
                "X-Service-Timestamp": str(int(time.time())), "X-Service-Nonce": uuid4().hex}

    def test_identity_rest_lists_writes_guesses_and_roles(self):
        cases = (("owner-a", self.a, "PROJECT_OWNER"), ("owner-b", self.b, "PROJECT_OWNER"),
                 ("user-a", self.a, "PROJECT_USER"), ("user-b", self.b, "PROJECT_USER"))
        for person, project, role in cases:
            with self.subTest(person=person):
                projects = self.client.get("/aiyoloapi/auth/projects", headers=self.tokens[person])
                self.assertEqual([project], [item["projectId"] for item in projects.json()["projects"]])
                self.assertEqual(role, projects.json()["projects"][0]["projectRole"])
                self.assertEqual(200, self.client.get(f"/aiyoloapi/projects/{project}",
                                                      headers=self.tokens[person]).status_code)
        self.assertEqual([], self.client.get("/aiyoloapi/auth/projects",
                                             headers=self.tokens["outsider"]).json()["projects"])
        self.assertEqual(401, self.client.get("/aiyoloapi/auth/me",
                                             headers=self.tokens["disabled"]).status_code)
        self.assertEqual(401, self.client.get(self.paths["b"] + "/alerts",
                                             headers=self.tokens["disabled"]).status_code)
        self.assertEqual(401, self.client.get(self.paths["a"] + "/alerts").status_code)
        self.assertEqual(400, self.client.get("/aiyoloapi/streams",
                                             headers=self.tokens["owner-a"]).status_code)
        self.assertEqual(400, self.client.get("/aiyoloapi/models",
                                             headers=self.tokens["user-a"]).status_code)
        for person in ("owner-a", "user-a", "outsider"):
            for suffix in ("", "/streams", "/alerts", "/rules", "/models", "/audit",
                           "/dashboard/stats", "/alerts/export"):
                with self.subTest(person=person, suffix=suffix):
                    self._hidden(person, suffix)
        self._hidden("owner-a", "/streams/shared-camera", method="delete")
        self._hidden("owner-a", "/rules/shared-rule", method="delete")
        self._hidden("user-a", "/alerts/shared-event/acknowledge", method="post",
                     json_body={"actedAtUs": 2})
        self.assertEqual(403, self.client.post(self.paths["a"] + "/streams",
            headers=self.tokens["user-a"], json={"stream_id": "forbidden", "enabled": False}).status_code)
        self.assertEqual(403, self.client.get("/aiyoloapi/platform/accounts",
                                              headers=self.tokens["owner-a"]).status_code)
        self.assertEqual(200, self.client.get(self.paths["b"] + "/streams",
                                              headers=self.admin).status_code)
        self.assertEqual(400, self.client.get("/aiyoloapi/streams", headers=self.admin).status_code)

    def test_streams_media_websockets_and_model_downloads(self):
        self._seed_streams()
        for person, project, model in (("user-a", self.a, "model-alpha"),
                                       ("user-b", self.b, "model-beta")):
            base = f"/aiyoloapi/projects/{project}"
            streams = self.client.get(base + "/streams", headers=self.tokens[person])
            self.assertEqual([project], [row["project_id"] for row in streams.json()])
            playback = self.client.get(base + "/streams/shared-camera/playback", headers=self.tokens[person])
            self.assertEqual(410, playback.status_code, playback.text)
            self.assertNotIn("url", playback.text)
            models = self.client.get(base + "/models", headers=self.tokens[person])
            self.assertEqual([model], [row["modelId"] for row in models.json()["models"]])
            artifact = base + f"/models/{model}/versions/1.0.0/artifacts/server/download"
            self.assertEqual(model.encode(), self.client.get(artifact, headers=self.tokens[person]).content)
        self.assertEqual(404, self.client.get(
            self.paths["a"] + "/models/model-beta/versions/1.0.0",
            headers=self.tokens["user-a"],
        ).status_code)
        for suffix in ("/models/model-beta", "/models/model-beta/versions/1.0.0/artifacts/server/download",
                       "/model-assignments/" + self.model_ids[self.b]):
            self._hidden("user-a", suffix)
        self.assertEqual(403, self.client.put(self.paths["a"] + "/model-assignments",
            headers=self.tokens["user-a"], json={"modelId": "model-beta", "modelVersion": "1.0.0",
                "target": "pc", "parameterRevision": 0, "enabled": True, "expectedRevision": 0}).status_code)
        self.assertEqual(404, self.client.get(self.paths["a"] + "/models/model-beta",
                                              headers=self.tokens["user-a"]).status_code)
        self.assertEqual(404, self.client.get(self.paths["a"] +
            "/models/model-beta/versions/1.0.0/artifacts/server/download",
            headers=self.tokens["user-a"]).status_code)
        for suffix in ("/streams/shared-camera/detections", "/streams/shared-camera/ws",
                       "/streams/shared-camera/ingest", "/alerts/ws", "/alerts/notifications"):
            with self.subTest(suffix=suffix):
                with self.assertRaises(WebSocketDisconnect) as denied:
                    with self.client.websocket_connect(self.paths["b"] + suffix,
                                                       headers=self.tokens["user-a"]):
                        pass
                self.assertEqual(1008 if suffix.endswith(("/detections", "/ws")) and "/streams/" in suffix else 4404, denied.exception.code)
        with self.assertRaises(WebSocketDisconnect) as retired:
            with self.client.websocket_connect(self.paths["a"] + "/streams/shared-camera/detections", headers=self.tokens["user-a"]):
                pass
        self.assertEqual(1008, retired.exception.code)
        asyncio.run(main.streams[(self.a, "shared-camera")].close())
        own_mjpeg = self.client.get(self.paths["a"] + "/streams/shared-camera/mjpeg",
                                    headers=self.tokens["user-a"])
        self.assertEqual(410, own_mjpeg.status_code)

    def test_media_server_rejects_all_reads_publishes_and_api_even_for_members(self):
        """Simulate MediaMTX's HTTP callback, not merely the playback URL API."""
        self._seed_streams()
        callback = "/aiyoloapi/internal/media/authorize"

        def check(person, project, *, protocol="webrtc", action="read", path=None, credential=None):
            token = credential if credential is not None else self.tokens[person]["Authorization"].split(" ", 1)[1]
            return self.client.post(callback, json={
                "user": "", "token": token, "password": "", "action": action,
                "path": path if path is not None else f"projects/{project}/streams/shared-camera",
                "protocol": protocol,
            }).status_code

        for protocol in ("webrtc", "hls", "rtsp"):
            for person, own, foreign in (("user-a", self.a, self.b), ("user-b", self.b, self.a)):
                with self.subTest(person=person, protocol=protocol):
                    self.assertEqual(403, check(person, own, protocol=protocol))
                    self.assertEqual(403, check(person, foreign, protocol=protocol))
                    self.assertEqual(403, check(person, self.missing, protocol=protocol))
            self.assertEqual(403, check("outsider", self.a, protocol=protocol))
            self.assertEqual(403, check("disabled", self.b, protocol=protocol))
            self.assertEqual(403, check("user-a", self.a, protocol=protocol, credential=""))
        self.assertEqual(403, check("user-a", self.a, action="publish"))
        self.assertEqual(403, check("user-a", self.a, action="api"))
        before_admin_entries = len([row for row in memory_platform_entry_audits()
                                    if row["transport"] == "MEDIA" and row["projectId"] == self.b])
        self.assertEqual(403, check("user-b", self.b))
        admin_token = self.admin["Authorization"].split(" ", 1)[1]
        for _ in range(2):
            self.assertEqual(403, check("user-b", self.b, credential=admin_token))
        after_admin_entries = len([row for row in memory_platform_entry_audits()
                                   if row["transport"] == "MEDIA" and row["projectId"] == self.b])
        self.assertEqual(before_admin_entries, after_admin_entries)
        internal = {"user": "aiyolo-service", "password": 'retired-service-token',
                    "token": "", "protocol": "rtsp", "action": "publish",
                    "path": f"projects/{self.a}/streams/shared-camera"}
        self.assertEqual(403, self.client.post(callback, json=internal).status_code)
        self.assertEqual(403, self.client.post(callback, json={
            **internal, "password": "invalid-internal-credential",
        }).status_code)
        self.assertEqual(403, self.client.post(callback, json={
            **internal, "user": "matrix-user-a",
        }).status_code)
        self.assertEqual(403, self.client.post(callback, json={
            **internal, "path": f"projects/{self.b}/streams/missing",
        }).status_code)
        self.assertEqual(403, self.client.post(callback, json={
            **internal, "action": "api", "protocol": "api", "path": "",
        }).status_code)
        self.assertEqual(403, check("user-a", self.a, path=f"projects/{self.b}/streams/other"))
        self.assertEqual(403, check("user-a", self.a, path=f"projects/{self.a}/streams/../shared-camera"))
        removed = self.client.delete(self.paths["a"] + "/members/" + self.accounts["user-a"]["accountId"],
                                     headers=self.admin, params={"expectedRevision": 1})
        self.assertEqual(204, removed.status_code, removed.text)
        self.assertEqual(403, check("user-a", self.a))

    def test_real_old_mediamtx_rejects_all_whep_hls_and_internal_api(self):
        """Exercise the actual MediaMTX 1.20 HTTP-auth handshake on loopback."""
        tools_root = Path(__file__).resolve().parents[2] / "tools" / "rtsp"
        mtx = tools_root / "mediamtx" / "1.20.1" / "mediamtx.exe"
        ffmpeg = tools_root / "ffmpeg" / "9.0.1" / "ffmpeg-9.0.1-essentials_build" / "bin" / "ffmpeg.exe"
        if not mtx.is_file():
            self.skipTest("local MediaMTX 1.20.1 executable is required")
        self._seed_streams()
        authorized_paths = []
        callback = FastAPI()

        @callback.post("/aiyoloapi/internal/media/authorize")
        async def check_media(payload: MediaAuthorizationRequest):
            authorized_paths.append((payload.action, payload.protocol, payload.path))
            authorize_media_read(payload, main.stream_config_store)
            return {}

        def free_socket():
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            return sock

        callback_socket = free_socket()
        callback_socket.listen(128)
        callback_port = callback_socket.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(callback, log_level="error", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [callback_socket]}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(setattr, server, "should_exit", True)
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertTrue(server.started, "media authorization callback failed to start")
        with ExitStack() as stack:
            ports = [free_socket() for _ in range(4)]
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.bind(("127.0.0.1", 0))
            chosen = [sock.getsockname()[1] for sock in ports] + [udp_socket.getsockname()[1]]
            for sock in ports:
                sock.close()
            udp_socket.close()
            rtsp, api, hls, whep, udp = chosen
            template = (Path(__file__).resolve().parents[1] /
                        "tests/fixtures/retired-mediamtx.yml").read_text(encoding="utf-8")
            config = Path(self.temp.name) / "mediamtx.yml"
            config.write_text(template.replace(
                "http://video-service:8080", f"http://127.0.0.1:{callback_port}"
            ).replace("rtsp: true", "rtsp: true\nrtspTransports: [tcp]"), encoding="utf-8")
            environment = {**os.environ,
                "MTX_RTSPADDRESS": f"127.0.0.1:{rtsp}",
                "MTX_APIADDRESS": f"127.0.0.1:{api}",
                "MTX_HLSADDRESS": f"127.0.0.1:{hls}",
                "MTX_WEBRTCADDRESS": f"127.0.0.1:{whep}",
                "MTX_WEBRTCLOCALUDPADDRESS": f"127.0.0.1:{udp}",
            }
            mtx_log = stack.enter_context((Path(self.temp.name) / "mediamtx.log").open("wb"))
            media = subprocess.Popen([str(mtx), str(config)], cwd=self.temp.name,
                                     env=environment, stdout=mtx_log, stderr=subprocess.STDOUT)
            stack.callback(self._stop_process, media)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if media.poll() is not None:
                    self.fail(f"MediaMTX exited: {media.returncode}; " +
                              (Path(self.temp.name) / "mediamtx.log").read_text(errors="replace"))
                try:
                    socket.create_connection(("127.0.0.1", rtsp), timeout=.3).close()
                    break
                except OSError:
                    time.sleep(.1)
            else:
                self.fail("MediaMTX did not start within 15 seconds")
            path = f"projects/{self.b}/streams/shared-camera"
            def request(protocol, credential=None):
                if protocol == "hls":
                    url = f"http://127.0.0.1:{hls}/{path}/index.m3u8"
                    data = None
                    method = "GET"
                else:
                    url = f"http://127.0.0.1:{whep}/{path}/whep"
                    data = b"invalid SDP"
                    method = "POST"
                headers = {"Authorization": "Bearer " + credential} if credential else {}
                if data:
                    headers["Content-Type"] = "application/sdp"
                try:
                    with urllib.request.urlopen(urllib.request.Request(
                            url, data=data, headers=headers, method=method), timeout=8) as response:
                        return response.status, response.read()
                except urllib.error.HTTPError as exc:
                    return exc.code, exc.read()
                except TimeoutError:
                    return 598, b"request timed out"

            owner_b = self.tokens["user-b"]["Authorization"].split(" ", 1)[1]
            owner_a = self.tokens["user-a"]["Authorization"].split(" ", 1)[1]
            for protocol in ("hls", "whep"):
                for credential in (None, owner_a, owner_b):
                    with self.subTest(protocol=protocol, credential=bool(credential)):
                        self.assertIn(request(protocol, credential)[0], (401, 403))
            api_url = f"http://127.0.0.1:{api}/v3/paths/list"
            basic = base64.b64encode(f"aiyolo-service:{'retired-service-token'}".encode()).decode("ascii")
            for headers in ({}, {"Authorization": "Basic " + basic}):
                with self.assertRaises(urllib.error.HTTPError) as rejected:
                    urllib.request.urlopen(urllib.request.Request(api_url, headers=headers), timeout=3)
                self.assertIn(rejected.exception.code, (401, 403))
            self.assertIn(("read", "hls", path), authorized_paths)
            self.assertIn(("read", "webrtc", path), authorized_paths)
            self.assertTrue(any(action == "api" for action, _, _ in authorized_paths))

    @staticmethod
    def _stop_process(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def test_alerts_objects_exports_disposition_and_audit(self):
        self._alert("user-a", self.a, "shared-event", b"alpha-image")
        self._alert("user-b", self.b, "shared-event", b"beta-image")
        for person, project, image in (("user-a", self.a, b"alpha-image"),
                                       ("user-b", self.b, b"beta-image")):
            path = f"/aiyoloapi/projects/{project}/alerts"
            listed = self.client.get(path, headers=self.tokens[person])
            self.assertEqual([project], [row["projectId"] for row in listed.json()["events"]])
            detail = self.client.get(path + "/shared-event", headers=self.tokens[person])
            self.assertEqual(project, detail.json()["projectId"])
            evidence = self.client.get(path + "/shared-event/evidence", headers=self.tokens[person])
            self.assertEqual(image, evidence.content)
        keys = [row[1] for row in self.minio.objects]
        self.assertEqual(2, len(keys))
        self.assertNotEqual(keys[0], keys[1])
        self.assertNotIn(self.a, json.dumps(keys))
        self.assertNotIn(self.b, json.dumps(keys))
        previous_reads = list(self.minio.read_keys)
        foreign_ref = main.alert_disposition_store.get("shared-event", self.b)["evidence"]
        with self.assertRaises(EvidenceStorageError):
            main.alert_evidence_store.read(foreign_ref, self.a)
        self.assertEqual(previous_reads, self.minio.read_keys)
        for suffix in ("/alerts/shared-event", "/alerts/shared-event/evidence",
                       "/alerts/shared-event/verification", "/alerts/export",
                       "/alerts/false-positives/export"):
            self._hidden("user-a", suffix)
        self.assertEqual(403, self.client.get(self.paths["a"] + "/alerts/export",
                                              headers=self.tokens["user-a"]).status_code)
        disposed = self.client.post(self.paths["a"] + "/alerts/shared-event/acknowledge",
            headers={**self.tokens["user-a"], "X-Actor": "spoofed"}, json={"actedAtUs": 2})
        self.assertEqual(200, disposed.status_code, disposed.text)
        self.assertEqual(self.accounts["user-a"]["accountId"], disposed.json()["disposition"]["actor"])
        self.assertEqual("OPEN", self.client.get(self.paths["b"] + "/alerts/shared-event",
            headers=self.tokens["user-b"]).json()["disposition"]["status"])
        for owner, project in (("owner-a", self.a), ("owner-b", self.b)):
            exported = self.client.get(f"/aiyoloapi/projects/{project}/alerts/export",
                                       headers=self.tokens[owner])
            self.assertEqual(200, exported.status_code, exported.text)
            self.assertEqual(project, exported.json()["projectId"])
            self.assertEqual(1, exported.json()["count"])
            self.assertNotIn(self.b if project == self.a else self.a, exported.text)
            audit = self.client.get(f"/aiyoloapi/projects/{project}/audit",
                                    headers=self.tokens[owner])
            self.assertEqual(200, audit.status_code, audit.text)
            self.assertTrue(all(row["projectId"] == project for row in audit.json()["events"]))

    def test_devices_role_changes_project_switch_and_concurrent_requests(self):
        device_a = self._device("owner-a", self.a, (ALERTS_INGEST, STREAMS_INGEST))
        device_b = self._device("owner-b", self.b)
        self.assertNotEqual(device_a["projectId"], device_b["projectId"])
        event_id = "service:" + device_a["principalId"] + ":golden"
        payload = {"eventId": event_id, "sourceId": "camera:back", "ruleId": "rule",
                   "subjectKey": "frame:1", "label": "head", "state": "CONFIRMED",
                   "startedAtUs": 1, "lastSeenAtUs": 1, "evidence": {}}
        own = self.client.post(self.paths["a"] + "/alerts/mobile-ingest",
                               headers=self._device_headers(device_a), json=payload)
        self.assertEqual(202, own.status_code, own.text)
        self.assertEqual(self.a, own.json()["projectId"])
        for project in (self.b, self.missing):
            response = self.client.post(f"/aiyoloapi/projects/{project}/alerts/mobile-ingest",
                                        headers=self._device_headers(device_a), json=payload)
            self.assertEqual(404, response.status_code, response.text)
        conflict = self.client.post(self.paths["a"] + "/alerts/mobile-ingest",
            headers=self._device_headers(device_a), json={**payload, "projectId": self.b})
        self.assertEqual(409, conflict.status_code, conflict.text)
        self.assertEqual(401, self.client.get(self.paths["a"] + "/alerts",
                                             headers=self._device_headers(device_a)).status_code)
        self.assertEqual(401, self.client.get(self.paths["a"] + "/alerts",
                                             headers=self._device_headers(device_b)).status_code)
        self._seed_streams()
        with self.assertRaises(WebSocketDisconnect) as denied:
            with self.client.websocket_connect(self.paths["b"] + "/streams/shared-camera/ingest",
                                               headers=self._device_headers(device_a)):
                pass
        self.assertEqual(4404, denied.exception.code)

        def fetch(person, project):
            response = self.client.get(f"/aiyoloapi/projects/{project}/streams",
                                       headers=self.tokens[person])
            return response.status_code, response.json()

        queries = (("user-a", self.a), ("user-a", self.b),
                   ("user-b", self.b), ("user-b", self.a)) * 8
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda item: fetch(*item), queries))
        for (person, project), (status, data) in zip(queries, results):
            if (person, project) in (("user-a", self.a), ("user-b", self.b)):
                self.assertEqual(200, status)
                self.assertEqual([project], [row["project_id"] for row in data])
            else:
                self.assertEqual(404, status)
                self.assertEqual("project_not_found", data["detail"]["code"])
        demoted = self.client.patch(self.paths["a"] +
            "/members/" + self.accounts["owner-a"]["accountId"], headers=self.admin,
            json={"expectedRevision": 1, "projectRole": "PROJECT_USER"})
        self.assertEqual(200, demoted.status_code, demoted.text)
        self.assertEqual(403, self.client.post(self.paths["a"] + "/streams",
            headers=self.tokens["owner-a"], json={"stream_id": "after-demotion"}).status_code)
        self.assertEqual(200, self.client.get(self.paths["a"] + "/streams",
                                              headers=self.tokens["owner-a"]).status_code)
        removed = self.client.delete(self.paths["a"] + "/members/" + self.accounts["user-a"]["accountId"],
            headers=self.admin, params={"expectedRevision": 1})
        self.assertEqual(204, removed.status_code, removed.text)
        self.assertEqual(404, self.client.get(self.paths["a"] + "/streams",
                                              headers=self.tokens["user-a"]).status_code)
        self.assertEqual(200, self.client.get("/aiyoloapi/auth/me",
                                              headers=self.tokens["user-a"]).status_code)
        self.assertEqual([], self.client.get("/aiyoloapi/auth/projects",
            headers=self.tokens["user-a"]).json()["projects"])

    def test_same_account_can_switch_only_between_explicit_memberships(self):
        # A user may join both projects, but every request still carries an
        # explicit project context and cannot silently fall back to the first.
        added = self.client.post(self.paths["b"] + "/members", headers=self.admin,
            json={"accountId": self.accounts["owner-a"]["accountId"], "projectRole": "PROJECT_USER"})
        self.assertEqual(201, added.status_code, added.text)
        projects = self.client.get("/aiyoloapi/auth/projects", headers=self.tokens["owner-a"])
        self.assertEqual({self.a, self.b}, {item["projectId"] for item in projects.json()["projects"]})
        self._seed_streams()
        for project in (self.a, self.b):
            switched = self.client.get("/aiyoloapi/streams",
                headers={**self.tokens["owner-a"], "X-Project-Id": project})
            self.assertEqual(200, switched.status_code, switched.text)
            self.assertEqual([project], [item["project_id"] for item in switched.json()])
        self.assertEqual(400, self.client.get("/aiyoloapi/streams",
            headers=self.tokens["owner-a"]).status_code)
        self.assertEqual(404, self.client.get("/aiyoloapi/streams",
            headers={**self.tokens["owner-a"], "X-Project-Id": self.missing}).status_code)


if __name__ == "__main__":
    unittest.main()
