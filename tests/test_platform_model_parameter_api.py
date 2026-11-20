"""Platform publication permission and cross-project parameter propagation."""
import unittest
from pathlib import Path
from unittest.mock import patch

import app.main as main
from app.model_parameters import ModelParameterStore, ModelParameterError
from test_project_model_assignments import ModelApiFixture
from stream_api_support import StreamApiFixture


class PlatformParameterApiTests(ModelApiFixture, unittest.TestCase):
    def test_platform_catalog_explains_missing_parameters_and_refreshes_after_publication(self):
        store = ModelParameterStore(Path(self.temp.name) / "catalog-unpublished.json")
        model = main.model_catalog.get("helmet", "1.0.0")
        with patch.object(main, "model_parameter_store", store):
            def catalog_model():
                response = self.client.get("/aiyoloapi/models", headers=self.headers)
                self.assertEqual(200, response.status_code, response.text)
                return next(m for m in response.json()["models"] if m["modelId"] == "helmet" and m["version"] == "1.0.0")
            initial = catalog_model()
            self.assertEqual("PUBLISHED", initial["status"])
            self.assertEqual({"server", "android"}, set(initial["parameterPublication"]))
            self.assertTrue(all(s["state"] == "unpublished" for s in initial["parameterPublication"].values()))
            self.assertFalse(any(m["modelId"] == "helmet" for m in self.client.get(
                self.project_path + "/models/available", headers=self.owner).json()["models"]))
            store.publish(model, "server", "admin", 0, None)
            current = catalog_model()
            self.assertEqual(0, current["parameterPublication"]["server"]["publishedRevision"])
            self.assertEqual("published", current["parameterPublication"]["server"]["state"])
            self.assertEqual("unpublished", current["parameterPublication"]["android"]["state"])
            self.assertTrue(any(m["modelId"] == "helmet" for m in self.client.get(
                self.project_path + "/models/available", headers=self.owner).json()["models"]))
            project = self.client.get(self.project_path + "/models", headers=self.owner)
            self.assertEqual(200, project.status_code)
            self.assertEqual([], project.json()["models"])
            self.assertNotIn("detection", str(current["parameterPublication"]))

    def test_catalog_parameter_status_failure_preserves_files_and_reports_unknown(self):
        from sqlalchemy.exc import OperationalError
        for error in (ModelParameterError("profile_store_unavailable", "private fixture path"),
                      OperationalError("fixture query", {}, Exception("private database details"))):
            with self.subTest(error=type(error).__name__):
                with patch.object(main.model_parameter_store, "publication_status", side_effect=error):
                    response = self.client.get("/aiyoloapi/models", headers=self.headers)
                self.assertEqual(200, response.status_code, response.text)
                self.assertTrue(response.json()["models"])
                for model in response.json()["models"]:
                    self.assertTrue(all(s["state"] == "unavailable" for s in model["parameterPublication"].values()))
                self.assertNotIn("private", response.text)

    def test_legacy_assignment_without_publication_requires_platform_publish(self):
        for target, platform in (("pc", "server"), ("mobile", "android")):
            with self.subTest(platform=platform):
                self.assertEqual(200, self._assign({**self.body, "target": target}).status_code)
                store = ModelParameterStore(Path(self.temp.name) / f"unpublished-{platform}.json")
                with patch.object(main, "model_parameter_store", store), patch.object(main.project_model_assignments, "parameters", store):
                    url = f"{self.project_path}/models/helmet/parameters?platform={platform}&version=1.0.0"
                    for headers in (self.owner, self.user):
                        response = self.client.get(url, headers=headers)
                        self.assertEqual(409, response.status_code, response.text)
                        self.assertEqual("platform_parameters_unpublished", response.json()["detail"]["code"])
                        self.assertIn("平台", response.json()["detail"]["message"])
                    inventory = self.client.get(self.assignments, headers=self.owner).json()["assignments"]
                    self.assertFalse(next(a for a in inventory if a["target"] == target)["parameterPublished"])
                    model = main.model_catalog.get("helmet", "1.0.0")
                    draft = store.get(model, platform)
                    draft["detection"]["confidenceThreshold"] = .21
                    store.save(model, platform, draft, "fixture-admin", 0)
                    self.assertEqual(409, self.client.get(url, headers=self.owner).status_code)
                    # A publication for another exact version must not satisfy this request.
                    store.publish(main.model_catalog.get("helmet", "2.0.0"), platform, "fixture-admin", 0, None)
                    self.assertEqual(409, self.client.get(url, headers=self.owner).status_code)
                    store.publish(model, platform, "fixture-admin", 1, None)
                    response = self.client.get(url, headers=self.user)
                    self.assertEqual(200, response.status_code, response.text)
                    self.assertEqual(("platform", 1, .21), (response.json()["source"], response.json()["revision"], response.json()["detection"]["confidenceThreshold"]))

    def test_parameter_read_preserves_assignment_target_and_project_boundaries(self):
        self.assertEqual(200, self._assign().status_code)
        for path, headers in (
            (f"{self.project_path}/models/helmet/parameters?platform=android&version=1.0.0", self.owner),
            (f"{self.project_path}/models/helmet/parameters?platform=server&version=2.0.0", self.owner),
            (f"/aiyoloapi/projects/{self.other_id}/models/helmet/parameters?platform=server&version=1.0.0", self.owner),
        ):
            self.assertEqual(404, self.client.get(path, headers=headers).status_code)
        self.assertEqual(200, self._assign({**self.body, "enabled": False, "expectedRevision": 1}).status_code)
        self.assertEqual(404, self.client.get(f"{self.project_path}/models/helmet/parameters?platform=server&version=1.0.0", headers=self.owner).status_code)

    def test_invalid_published_parameters_are_not_reported_as_unpublished(self):
        self.assertEqual(200, self._assign().status_code)
        with patch.object(main.model_parameter_store, "published", side_effect=ModelParameterError("invalid_profile", "invalid fixture")):
            response = self.client.get(f"{self.project_path}/models/helmet/parameters?platform=server&version=1.0.0", headers=self.owner)
        self.assertEqual(503, response.status_code, response.text)
        self.assertEqual("invalid_profile", response.json()["detail"]["code"])

    def test_publication_is_platform_only_and_updates_both_projects(self):
        first = self._assign().json()
        other = self.client.put(f"/aiyoloapi/projects/{self.other_id}/model-assignments",
            headers=self.headers, json=self.body)
        self.assertEqual(200, other.status_code, other.text)
        url = "/aiyoloapi/platform/models/helmet/parameters?platform=server&version=1.0.0"
        publication = url.replace("parameters?", "parameters/publish?")
        draft = self.client.get(url, headers=self.headers).json()
        body = {k: draft[k] for k in ("schemaVersion", "detection", "alertRules")} | {"expectedRevision": 0}
        body["detection"]["confidenceThreshold"] = .21
        self.assertEqual(403, self.client.put(url, headers=self.owner, json=body).status_code)
        self.assertEqual(200, self.client.put(url, headers=self.headers, json=body).status_code)
        publish_body = {"expectedRevision": 1, "expectedPublishedRevision": 0}
        self.assertEqual(403, self.client.post(publication, headers=self.owner, json=publish_body).status_code)
        for pid in (self.project_id, self.other_id):
            profile = main.project_model_assignments.snapshot(pid, "helmet", "1.0.0", "server")
            self.assertEqual(0, profile["revision"])
        result = self.client.post(publication, headers=self.headers, json=publish_body)
        self.assertEqual(200, result.status_code, result.text)
        self.assertEqual("platform", result.json()["source"])
        self.assertEqual(409, self.client.post(publication, headers=self.headers,
            json={"expectedRevision": 1, "expectedPublishedRevision": None}).status_code)
        for pid in (self.project_id, self.other_id):
            profile = main.project_model_assignments.snapshot(pid, "helmet", "1.0.0", "server")
            self.assertEqual((1, .21), (profile["revision"], profile["detection"]["confidenceThreshold"]))
        self.assertEqual(1, main.project_model_assignments.get(self.project_id, first["projectModelId"])["revision"])
        self.assertEqual(404, self.client.get(f"/aiyoloapi/projects/{self.other_id}/models/helmet/parameters?platform=server",
            headers=self.owner).status_code)


class PlatformParameterStreamTests(StreamApiFixture, unittest.TestCase):
    def test_running_stream_keeps_parameters_restart_follows_platform_and_revocation_stops(self):
        self.create_stream('platform-parameters')
        stream = main.streams[(self.project_id, 'platform-parameters')]
        model = main.model_catalog.get('helmet', '1.0.0')
        store = main.model_parameter_store
        first = main._runtime_profile(self.project_id, 'platform-parameters', 'helmet')
        self.assertEqual(0, first['revision'])
        draft = store.get(model, 'server')
        draft['detection']['confidenceThreshold'] = .21
        store.save(model, 'server', draft, 'admin', 0)
        store.publish(model, 'server', 'admin', 1, 0)
        self.assertEqual(first, main._runtime_profile(self.project_id, 'platform-parameters', 'helmet'))
        url = self.streams_path + '/platform-parameters/yolo'
        self.assertEqual(200, self.client.post(url, json={'enabled': False}).status_code)
        self.assertEqual(200, self.client.post(url, json={'enabled': True}).status_code)
        self.assertEqual(1, main._runtime_profile(self.project_id, 'platform-parameters', 'helmet')['revision'])
        self.assertEqual(.21, stream.detector.confidence)
        self.client.post(self.project_path + '/scenes/transport/approval', headers=self.headers,
            json={'approved': False, 'expectedRevision': 2, 'reason': 'revoke'})
        self.assertIsNone(main._runtime_profile(self.project_id, 'platform-parameters', 'helmet'))
        self.assertEqual(204, self.client.delete(self.streams_path + '/platform-parameters').status_code)
