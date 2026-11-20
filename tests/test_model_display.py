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
    def test_uninstalled_assignment_retains_exact_name_and_rejects_reactivation(self):
        catalog = main.model_catalog
        registry = catalog._load()
        registry["models"][0]["name"] = "安全帽检测 一代"
        registry["models"][1]["name"] = "安全帽检测 二代"
        catalog._save(registry)
        assigned = self._assign().json()
        disabled = self._assign({**self.body, "enabled": False, "expectedRevision": 1})
        self.assertEqual(200, disabled.status_code, disabled.text)
        release_path = "/aiyoloapi/models/helmet/versions/1.0.0"
        impact = self.client.get(release_path + "/removal-impact", headers=self.headers)
        self.assertEqual(200, impact.status_code, impact.text)
        self.assertTrue(impact.json()["safeToRemove"])
        removed = self.client.delete(release_path, headers={**self.headers,
            "If-Match": f'"{impact.json()["expectedRevision"]}"', "Idempotency-Key": "display-uninstall"})
        self.assertEqual(200, removed.status_code, removed.text)
        tombstone = catalog._load()["modelHistory"][-1]
        self.assertEqual("安全帽检测 一代", tombstone["name"])
        self.assertEqual({"name", "status"}, set(catalog.display_metadata("helmet", "1.0.0")))
        self.assertEqual("安全帽检测 一代", catalog_model_name(catalog, "helmet", "1.0.0"))
        # Ordinary users must still not see disabled inventory entries.
        self.assertEqual([], self.client.get(self.assignments, headers=self.user).json()["assignments"])
        row = self.client.get(self.assignments, headers=self.owner).json()["assignments"][0]
        self.assertEqual("安全帽检测 一代", row["modelName"])
        self.assertEqual("UNINSTALLED", row["modelStatus"])
        self.assertEqual(2, row["revision"])
        self.assertFalse(row["enabled"])
        self.assertFalse(row["parameterPublished"])
        rejected = self._assign({**self.body, "expectedRevision": 2})
        self.assertEqual(409, rejected.status_code, rejected.text)
        self.assertEqual("model_uninstalled", rejected.json()["detail"]["code"])
        self.assertIn("不能重新启用", rejected.text)
        self.assertIn("1.0.0", rejected.text)
        with self.assertRaises(KeyError):
            catalog.get("helmet", "1.0.0")
        self.assertEqual("PUBLISHED", catalog.get("helmet", "2.0.0")["status"])
        self.assertEqual(200, self.client.delete(f'{self.assignments}/{assigned["projectModelId"]}',
            headers=self.owner, params={"expectedRevision": 2}).status_code)

    def test_old_tombstones_do_not_borrow_other_version_names_or_restore_assets(self):
        catalog = main.model_catalog
        self._assign()
        self._assign({**self.body, "enabled": False, "expectedRevision": 1})
        catalog.uninstall("helmet", "1.0.0")
        registry = catalog._load()
        registry["modelHistory"][-1].pop("name")
        catalog._save(registry)
        before = deepcopy(catalog._load())
        row = main.project_model_assignments.list(self.project_id)[0]
        self.assertEqual("未命名模型", row["modelName"])
        self.assertEqual("UNINSTALLED", row["modelStatus"])
        self.assertEqual(before, catalog._load())
        registry["modelHistory"] = []
        catalog._save(registry)
        row = main.project_model_assignments.list(self.project_id)[0]
        self.assertEqual("MISSING", row["modelStatus"])
        self.assertEqual("未命名模型", row["modelName"])

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
