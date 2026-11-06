import hashlib
import asyncio
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from app.alerts.disposition import AlertDispositionStore
from app.alerts.runtime import ServerAlertRuntime
from app.database import DEFAULT_PROJECT_ID
from app.detection import Detection, InferenceResult, NormalizedBox
from app.model_catalog import ModelCatalog
from app.model_parameters import ModelParameterStore
from app.project_business import _memory_model_assignments
from app.project_model_assignments import ProjectModelAssignments
from app.stream_config import StreamConfigStore
from project_api_support import ProjectApiSupport
import app.main as main


def release(models, model_id, version, *, scenario="ppe", status="PUBLISHED"):
    path = models / f"{model_id}-{version}.pt"
    path.write_bytes(f"{model_id}-{version}".encode())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    android_path = models / f"{model_id}-{version}.tflite"
    android_path.write_bytes(f"android-{model_id}-{version}".encode())
    android_digest = hashlib.sha256(android_path.read_bytes()).hexdigest()
    return {"modelId": model_id, "name": model_id, "version": version, "scenario": scenario,
            "runtime": "server-pt", "format": "pt", "path": "models/" + path.name,
            "sizeBytes": path.stat().st_size, "sha256": digest, "labels": ["head"],
            "releaseEligible": status == "PUBLISHED", "status": status,
            "artifacts": [{"artifactId": "server", "format": "pt", "platform": "server",
                           "path": "models/" + path.name, "sizeBytes": path.stat().st_size, "sha256": digest},
                          {"artifactId": "android", "format": "tflite", "platform": "android",
                           "path": "models/" + android_path.name, "sizeBytes": android_path.stat().st_size,
                           "sha256": android_digest}]}


class ModelApiFixture(ProjectApiSupport):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = ExitStack()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.patches.close)
        models = Path(self.temp.name) / "models"
        models.mkdir()
        self.entries = [release(models, "helmet", "1.0.0"), release(models, "helmet", "2.0.0"),
                        release(models, "secret", "1.0.0", scenario="intrusion")]
        for entry in self.entries[:2]:
            entry.update(androidReady=True, androidConverted=True, signatureStatus="signed")
        registry = models / "registry.json"
        registry.write_text(json.dumps({"activeServerModel": "helmet@2.0.0", "models": self.entries}), encoding="utf-8")
        catalog = ModelCatalog(registry)
        profiles = ModelParameterStore(models / "profiles.json")
        configs = StreamConfigStore(None)
        assignments = ProjectModelAssignments(
            None, catalog, profiles, configs,
        )
        self.patches.enter_context(patch.object(main, "model_catalog", catalog))
        self.patches.enter_context(patch.object(main, "model_parameter_store", profiles))
        self.patches.enter_context(patch.object(main, "stream_config_store", configs))
        self.patches.enter_context(patch.object(main, "project_model_assignments", assignments))
        from app.project_scenes import ProjectScenes
        self.patches.enter_context(patch.object(main, "project_scenes", ProjectScenes(None, catalog, assignments)))
        self.patches.enter_context(patch.object(main, "streams", main.ProjectStreamRegistry()))
        self.patches.enter_context(patch.dict(_memory_model_assignments, {}, clear=True))
        self.start_project_api("model-assignment")
        self.addCleanup(self.stop_project_api)
        self.assignments = self.project_path + "/model-assignments"
        self.body = {"modelId": "helmet", "modelVersion": "1.0.0", "target": "pc",
                     "parameterRevision": 0, "enabled": True, "expectedRevision": 0}
        self.owner = self._account("model-owner", "PROJECT_OWNER")
        self.user = self._account("model-user", "PROJECT_USER")
        other = self.client.post("/aiyoloapi/projects", headers=self.headers, json={
            "projectCode": "model-other", "displayName": "Other", "ownerAccountId": self.account_id})
        self.assertEqual(201, other.status_code)
        self.other_id = other.json()["projectId"]

    def _account(self, username, role):
        created = self.client.post("/aiyoloapi/platform/accounts", headers=self.headers, json={
            "username": username, "password": "temporary-test-password", "platformRole": "NORMAL_USER"})
        self.assertEqual(201, created.status_code, created.text)
        member = self.client.post(self.project_path + "/members", headers=self.headers, json={
            "accountId": created.json()["accountId"], "projectRole": role})
        self.assertIn(member.status_code, (200, 201), member.text)
        token = self.client.post("/aiyoloapi/auth/login", json={
            "username": username, "password": "temporary-test-password"})
        self.assertEqual(200, token.status_code)
        return {"Authorization": "Bearer " + token.json()["accessToken"]}

    def _assign(self, body=None, headers=None):
        return self.client.put(self.assignments, headers=headers or self.owner, json=body or self.body)


