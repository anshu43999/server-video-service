"""Platform publications authorize execution; legacy project snapshots are history."""
from copy import deepcopy
import os
import unittest
from unittest.mock import patch

from app.database import ProjectModelAssignmentRecord
from app.model_parameters import ModelParameterError
from app.project_business import _memory_model_assignments
import app.main as main
import test_project_scenes as fixtures


class SceneSnapshotApprovalApiTests(fixtures.SceneApiTests):
    def test_legacy_assignment_snapshot_cannot_override_platform(self):
        row = next(row for row in _memory_model_assignments.values()
                   if row["projectModelId"] == self.project_models[("helmet", "1.0.0", "pc")])
        legacy = {"schemaVersion": 1, "revision": 999, "source": "custom",
                  "detection": {"confidenceThreshold": .99}}
        row["parameterSnapshot"] = deepcopy(legacy)
        self.assertEqual(201, self.create().status_code)
        approved = self.client.post(self.scenes + "/safety/approval", headers=self.owner,
            json={"approved": True, "expectedRevision": 1, "reason": "review"})
        self.assertEqual(200, approved.status_code, approved.text)
        profile = approved.json()["models"][0]["parameterSnapshot"]
        self.assertEqual(("platform", 0), (profile["source"], profile["revision"]))
        self.assertNotEqual(.99, profile["detection"]["confidenceThreshold"])
        self.assertEqual(legacy, row["parameterSnapshot"])

    def test_missing_publication_cannot_fall_back_to_legacy_snapshot(self):
        self.assertEqual(201, self.create().status_code)
        before = self.scene_store.get(self.project_id, "safety")
        with patch.object(main.model_parameter_store, "published",
                side_effect=ModelParameterError("platform_parameters_unpublished", "unpublished")):
            response = self.client.post(self.scenes + "/safety/approval", headers=self.owner,
                json={"approved": True, "expectedRevision": 1, "reason": "review"})
            self.assertEqual(409, response.status_code, response.text)
        self.assertEqual(before, self.scene_store.get(self.project_id, "safety"))


class SnapshotStorageChecks:
    def test_database_legacy_snapshot_is_preserved_but_not_executed(self):
        with self.db.session() as session:
            row = session.get(ProjectModelAssignmentRecord, "pm-p1-person")
            row.parameter_snapshot = {"revision": 999, "source": "custom", "detection": {}}
        self.store.save("p1", "safety", self.changes, 0, creating=True)
        approved = self.store.save("p1", "safety", {"approved": True}, 1, approval_reason="review")
        self.assertTrue(all(m["parameterSnapshot"]["source"] == "platform" for m in approved["models"]))
        self.db.close()
        self.assertEqual(approved, self.store.get("p1", "safety"))
        with self.db.session() as session:
            self.assertEqual(999, session.get(ProjectModelAssignmentRecord, "pm-p1-person").parameter_snapshot["revision"])


class SceneSnapshotApprovalSqliteTests(SnapshotStorageChecks, fixtures.SceneSqliteTests):
    pass


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "isolated PostgreSQL is opt-in")
class SceneSnapshotApprovalPostgresTests(SnapshotStorageChecks, fixtures.SceneSqliteTests):
    use_postgresql = True
