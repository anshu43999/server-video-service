from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import app.main as main
from app.model_display import catalog_model_name, model_display_name
from test_project_model_assignments import ModelApiFixture


class ModelDisplayTests(unittest.TestCase):
    def test_missing_names_are_not_ids_or_guessed_latest_versions(self):
        self.assertEqual("未命名模型", model_display_name({"name": "  ", "modelId": "uploaded-123"}))
        self.assertEqual("安全帽检测", model_display_name({"name": " 安全帽检测 "}))
        catalog = unittest.mock.Mock()
        self.assertEqual("未命名模型", catalog_model_name(catalog, "uploaded-123", None))
        catalog.get.assert_not_called()


class ModelDisplayApiTests(ModelApiFixture, unittest.TestCase):
    def test_exact_release_name_project_and_scene_projection_without_reapproval(self):
        catalog = main.model_catalog
        registry = json.loads(catalog.registry_path.read_text(encoding="utf-8"))
        registry["models"][0]["name"] = "安全帽检测 一代"
        registry["models"][1]["name"] = "安全帽检测 二代"
        catalog.registry_path.write_text(json.dumps(registry), encoding="utf-8")
        assigned = self._assign().json()
        assignment_id = assigned["projectModelId"]
        self.assertEqual("安全帽检测 一代", main.project_model_assignments.get(self.project_id, assignment_id)["modelName"])
        self.assertEqual("安全帽检测 一代", self.client.get(self.assignments, headers=self.user).json()["assignments"][0]["modelName"])
        path = self.project_path + "/scenes"
        created = self.client.post(path, headers=self.owner, json={"sceneId": "display", "name": "命名测试",
            "inputTypes": ["image"], "expectedRevision": 0, "models": [{"projectModelId": assignment_id,
            "position": 0, "execution": "single"}]})
        self.assertEqual(201, created.status_code, created.text)
        before = deepcopy(main.project_scenes.get(self.project_id, "display"))
        projected = self.client.get(path + "/display", headers=self.owner)
        self.assertEqual("安全帽检测 一代", projected.json()["models"][0]["modelName"])
        self.assertEqual("helmet", projected.json()["models"][0]["modelId"])
        self.assertEqual("1.0.0", projected.json()["models"][0]["version"])
        self.assertEqual(before, main.project_scenes.get(self.project_id, "display"))
        self.assertNotIn("modelName", before["models"][0])
        denied = self.client.get(f"/aiyoloapi/projects/{self.other_id}/scenes/display", headers=self.user)
        self.assertIn(denied.status_code, (403, 404))
        self.assertNotIn("安全帽检测", denied.text)

    def test_event_display_does_not_mutate_history_or_resolve_another_version(self):
        event = {"eventId": "display", "projectId": self.project_id,
                 "model": {"modelId": "helmet", "version": "1.0.0"}}
        original = deepcopy(event)
        with patch.object(main.model_catalog, "get", return_value={"name": " 上传名称 <&> "}) as get:
            output = main.public_alert_event(event)
            get.assert_called_once_with("helmet", "1.0.0")
        self.assertEqual("上传名称 <&>", output["model"]["name"])
        self.assertEqual(original, event)
