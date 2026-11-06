import importlib
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.model_parameters import ModelParameterStore
from app.model_catalog import ModelCatalog
from app.database import DatabaseManager
import app.auth as auth_module


main_module = importlib.import_module("app.main")
ROOT = Path(__file__).resolve().parents[1]
HELMET_MODEL_ID = "parameter-test-model"


class ModelParameterApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".test-convert")
        self.original_store = main_module.model_parameter_store
        self.isolation = ExitStack()
        self.addCleanup(self.isolation.close)
        models_dir = Path(self.temp.name) / "models"
        models_dir.mkdir()
        artifact = models_dir / "parameter-test.pt"
        artifact.write_bytes(b"parameter-test-model")
        registry = models_dir / "registry.json"
        registry.write_text(__import__('json').dumps({"activeServerModel": HELMET_MODEL_ID, "models": [{
            "modelId": HELMET_MODEL_ID, "name": "Parameter test", "version": "1.0.0",
            "scenario": "test", "purpose": "development", "runtime": "server-pt",
            "format": "pt", "path": "models/parameter-test.pt", "sizeBytes": artifact.stat().st_size,
            "sha256": __import__('hashlib').sha256(artifact.read_bytes()).hexdigest(),
            "labels": ["head", "helmet"], "releaseEligible": False,
            "artifacts": [{"artifactId": "server", "format": "pt", "platform": "server",
                "path": "models/parameter-test.pt", "sizeBytes": artifact.stat().st_size,
                "sha256": __import__('hashlib').sha256(artifact.read_bytes()).hexdigest()}],
        }]}), encoding="utf-8")
        self.isolation.enter_context(patch('app.main.model_catalog', ModelCatalog(registry)))
        self.isolation.enter_context(patch('app.auth.database', DatabaseManager(None)))
        self.isolation.enter_context(patch.dict(auth_module._memory_accounts, {}, clear=True))
        self.isolation.enter_context(patch.dict(auth_module._memory_sessions, {}, clear=True))
        self.original_admin = settings.admin_token
        self.original_mobile = settings.mobile_token
        main_module.model_parameter_store = ModelParameterStore(Path(self.temp.name) / "profiles.json")
        settings.admin_token = None
        settings.mobile_token = None
        self.client = TestClient(main_module.app)
        response = self.client.post('/aiyoloapi/auth/setup', json={
            'username': 'parameter-admin', 'password': 'temporary-test-password',
        })
        self.assertEqual(response.status_code, 200)

    def tearDown(self):
        self.client.close()
        main_module.model_parameter_store = self.original_store
        settings.admin_token = self.original_admin
        settings.mobile_token = self.original_mobile
        self.temp.cleanup()

    def test_get_returns_versioned_default_profile_for_catalog_clients(self):
        settings.mobile_token = "mobile-secret"
        anonymous = TestClient(main_module.app)
        denied = anonymous.get(f"/aiyoloapi/models/{HELMET_MODEL_ID}/parameters")
        self.assertEqual(denied.status_code, 401)
        anonymous.close()
        response = self.client.get(
            f"/aiyoloapi/models/{HELMET_MODEL_ID}/parameters",
            headers={"X-Video-Service-Token": "mobile-secret"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["modelVersion"], "1.0.0")
        self.assertEqual(body["platform"], "android")
        self.assertEqual(body["schemaVersion"], 2)
        self.assertEqual(next(rule for rule in body["alertRules"] if rule["rawLabel"] == "head")["eventCode"], "PPE_NO_HELMET")

    def test_v2_update_returns_image_and_camera_parameters(self):
        settings.admin_token = "admin-secret"
        profile = self.client.get(
            f"/aiyoloapi/models/{HELMET_MODEL_ID}/parameters",
            headers={"X-Admin-Token": "admin-secret"},
        ).json()
        payload = {
            "schemaVersion": 2,
            "expectedRevision": profile["revision"],
            "detection": profile["detection"],
            "alertRules": profile["alertRules"],
        }
        payload["alertRules"][0]["image"]["minimumConfidence"] = 0.45
        saved = self.client.put(
            f"/aiyoloapi/models/{HELMET_MODEL_ID}/parameters",
            json=payload,
            headers={"X-Admin-Token": "admin-secret"},
        )
        self.assertEqual(saved.status_code, 200)
        body = saved.json()
        head = next(rule for rule in body["alertRules"] if rule["rawLabel"] == "head")
        self.assertEqual(head["image"]["minimumConfidence"], 0.45)
        self.assertEqual(head["camera"]["minimumConsecutiveFrames"], 4)
        self.assertEqual(head["minimumConfidence"], head["camera"]["minimumConfidence"])

    def test_legacy_v1_update_is_accepted_and_persisted_as_v2(self):
        settings.admin_token = "admin-secret"
        profile = self.client.get(
            f"/aiyoloapi/models/{HELMET_MODEL_ID}/parameters",
            headers={"X-Admin-Token": "admin-secret"},
        ).json()
        legacy_rules = []
        for rule in profile["alertRules"]:
            legacy_rules.append({key: rule[key] for key in (
                "rawLabel", "displayName", "eventCode", "operator", "enabled",
                "minimumConfidence", "minimumConsecutiveFrames", "minimumDwellTimeMs", "cooldownMs", "severity",
            )})
        payload = {"expectedRevision": 0, "detection": profile["detection"], "alertRules": legacy_rules}
        saved = self.client.put(
            f"/aiyoloapi/models/{HELMET_MODEL_ID}/parameters",
            json=payload,
            headers={"X-Admin-Token": "admin-secret"},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["schemaVersion"], 2)
        self.assertIn("image", saved.json()["alertRules"][0])

    def test_v2_image_confidence_is_validated_against_detection_threshold(self):
        settings.admin_token = "admin-secret"
        profile = self.client.get(
            f"/aiyoloapi/models/{HELMET_MODEL_ID}/parameters",
            headers={"X-Admin-Token": "admin-secret"},
        ).json()
        profile["alertRules"][0]["image"]["minimumConfidence"] = 0.2
        rejected = self.client.put(
            f"/aiyoloapi/models/{HELMET_MODEL_ID}/parameters",
            json={"schemaVersion": 2, "expectedRevision": 0, "detection": profile["detection"], "alertRules": profile["alertRules"]},
            headers={"X-Admin-Token": "admin-secret"},
        )
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(rejected.json()["detail"]["code"], "alert_confidence_too_low")

    def test_update_requires_admin_and_rejects_stale_revision(self):
        settings.admin_token = "admin-secret"
        settings.mobile_token = "mobile-secret"
        profile = self.client.get(
            f"/aiyoloapi/models/{HELMET_MODEL_ID}/parameters?platform=server",
            headers={"X-Video-Service-Token": "mobile-secret"},
        ).json()
        payload = {
            "expectedRevision": profile["revision"],
            "detection": profile["detection"],
            "alertRules": profile["alertRules"],
        }
        anonymous = TestClient(main_module.app)
        self.assertEqual(anonymous.put(f"/aiyoloapi/models/{HELMET_MODEL_ID}/parameters?platform=server", json=payload).status_code, 401)
        anonymous.close()
        saved = self.client.put(
            f"/aiyoloapi/models/{HELMET_MODEL_ID}/parameters?platform=server",
            json=payload,
            headers={"X-Admin-Token": "admin-secret", "X-Operator-Id": "safety-admin"},
        )
        stale = self.client.put(
            f"/aiyoloapi/models/{HELMET_MODEL_ID}/parameters?platform=server",
            json=payload,
            headers={"X-Admin-Token": "admin-secret"},
        )
        self.assertEqual(saved.status_code, 200)
        account_id = self.client.get('/aiyoloapi/auth/me').json()['accountId']
        self.assertEqual(saved.json()["updatedBy"], account_id)
        self.assertNotEqual(saved.json()["updatedBy"], "safety-admin")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"]["code"], "revision_conflict")

    def test_update_validates_model_labels_and_reset_is_audited(self):
        profile = self.client.get(f"/aiyoloapi/models/{HELMET_MODEL_ID}/parameters").json()
        invalid = {
            "expectedRevision": 0,
            "detection": profile["detection"],
            "alertRules": profile["alertRules"][:-1],
        }
        rejected = self.client.put(f"/aiyoloapi/models/{HELMET_MODEL_ID}/parameters", json=invalid)
        saved = self.client.put(
            f"/aiyoloapi/models/{HELMET_MODEL_ID}/parameters",
            json={"expectedRevision": 0, "detection": profile["detection"], "alertRules": profile["alertRules"]},
        )
        reset = self.client.delete(f"/aiyoloapi/models/{HELMET_MODEL_ID}/parameters?expectedRevision=1")
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(rejected.json()["detail"]["code"], "alert_label_mismatch")
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(reset.json()["source"], "default")
        self.assertEqual([item["action"] for item in reset.json()["audit"]], ["UPDATED", "RESET"])

    def test_missing_model_and_invalid_platform_are_rejected(self):
        self.assertEqual(self.client.get("/aiyoloapi/models/missing/parameters").status_code, 404)
        self.assertEqual(self.client.get(f"/aiyoloapi/models/{HELMET_MODEL_ID}/parameters?platform=ios").status_code, 422)


if __name__ == "__main__":
    unittest.main()
