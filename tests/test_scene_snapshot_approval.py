"""Regression: a newly created scene must not approve an old broken assignment."""
from copy import deepcopy
import os
import unittest

from fastapi import HTTPException
from sqlalchemy import select

import app.main as main
from app.database import ProjectModelAssignmentRecord, ProjectAuditEventRecord
from app.project_business import _memory_model_assignments
from app.project_management import memory_audits_for_tests
from app.project_scenes import ProjectScenes
import test_project_scenes as fixtures


class SceneSnapshotApprovalApiTests(fixtures.SceneApiTests):
    def corrupt(self, project_model_id, transform):
        row = next(row for row in _memory_model_assignments.values()
                   if row["projectModelId"] == project_model_id and row["projectId"] == self.project_id)
        row["parameterSnapshot"] = transform(deepcopy(row["parameterSnapshot"]))

    def approve_snapshot(self, revision=1):
        return self.client.post(self.scenes + "/safety/approval", headers=self.owner,
            json={"approved": True, "expectedRevision": revision, "reason": "isolated snapshot regression"})

    def test_new_scene_reusing_old_assignment_denied_atomically_then_normal_resave_recovers(self):
        bad_id = self.project_models[("helmet", "2.0.0", "mobile")]
        self.corrupt(bad_id, lambda p: {k: v for k, v in p.items()
                                       if k not in {"schemaVersion", "source", "updatedAt"}})
        body = {**self.scene, "models": [self.member("helmet", target="mobile"),
                self.member("helmet", 1, version="2.0.0", target="mobile")], "plans": []}
        self.assertEqual(201, self.create(body).status_code)
        before = self.scene_store.get(self.project_id, "safety")
        audits = deepcopy(memory_audits_for_tests())
        denied = self.approve_snapshot()
        self.assertEqual(409, denied.status_code, denied.text)
        detail = denied.json()["detail"]
        self.assertEqual("project_model_snapshot_invalid", detail["code"])
        self.assertEqual(bad_id, detail["projectModelId"])
        self.assertEqual("mobile", detail["target"])
        self.assertEqual({"schemaVersion", "source", "updatedAt", "inheritedRevision"}, set(detail["invalidFields"]))
        self.assertIn("重新批准", detail["message"])
        self.assertNotIn("detection", detail)
        self.assertEqual(before, self.scene_store.get(self.project_id, "safety"))
        self.assertEqual(audits, memory_audits_for_tests())
        self.assertEqual([], self.client.get(self.scenes, headers=self.user).json()["scenes"])
        saved = self._assign({**self.body, "modelVersion": "2.0.0", "target": "mobile", "expectedRevision": 1})
        self.assertEqual(200, saved.status_code, saved.text)
        approved = self.approve_snapshot()
        self.assertEqual(200, approved.status_code, approved.text)
        self.assertEqual(2, approved.json()["revision"])
        self.assertEqual([], approved.json()["plans"])
        members = self.client.get(self.scenes, headers=self.user).json()["scenes"][0]["models"]
        self.assertTrue(all(m["parameterSnapshot"]["schemaVersion"] == 2 for m in members))
        self.assertTrue(all(m["parameterSnapshot"]["source"] == "inherited" for m in members))
        self.assertFalse(main.streams)

    def test_malformed_metadata_does_not_replace_existing_approval(self):
        self.assertEqual(201, self.create().status_code)
        self.assertEqual(200, self.approve_snapshot().status_code)
        before = self.scene_store.get(self.project_id, "safety")
        assignment_id = before["models"][0]["projectModelId"]
        original = main.project_model_assignments.resolve(self.project_id, assignment_id)["parameterSnapshot"]
        cases = [
            ("schemaVersion", "2"), ("schemaVersion", True), ("schemaVersion", 2.0),
            ("source", "unknown"), ("source", []), ("source", None),
            ("updatedAt", " "), ("updatedAt", 123),
            ("inheritedRevision", None), ("inheritedRevision", True), ("inheritedRevision", -1),
            ("inheritedRevision", "0"),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.corrupt(assignment_id, lambda _p: {**deepcopy(original), field: value})
                denied = self.approve_snapshot(2)
                self.assertEqual(409, denied.status_code, denied.text)
                self.assertIn(field, denied.json()["detail"]["invalidFields"])
                self.assertEqual(before, self.scene_store.get(self.project_id, "safety"))

    def test_complete_default_custom_inherited_snapshots_and_null_timestamp_are_valid(self):
        self.assertEqual(201, self.create().status_code)
        self.assertEqual(200, self.approve_snapshot().status_code)
        scene = self.scene_store.get(self.project_id, "safety")
        original = scene["models"][0]
        for source, inherited, updated_at in (("default", None, None),
                ("custom", None, "2026-11-02T10:00:00Z"), ("inherited", 0, None)):
            with self.subTest(source=source):
                member = deepcopy(original)
                member["parameterSnapshot"].update(source=source, inheritedRevision=inherited, updatedAt=updated_at)
                ProjectScenes.validate_approval_parameters(scene, member)
        member = deepcopy(original)
        member["parameterSnapshot"].update(source="custom", inheritedRevision=0)
        with self.assertRaises(HTTPException) as error:
            ProjectScenes.validate_approval_parameters(scene, member)
        self.assertEqual(["inheritedRevision"], error.exception.detail["invalidFields"])


class SnapshotStorageChecks:
    def test_missing_metadata_in_database_rejects_entire_approval_and_recovers_after_resave(self):
        assignment_id = "pm-p1-person"
        with self.db.session() as session:
            row = session.get(ProjectModelAssignmentRecord, assignment_id)
            original = deepcopy(row.parameter_snapshot)
            row.parameter_snapshot = {k: v for k, v in original.items()
                                      if k not in {"schemaVersion", "source", "updatedAt"}}
        self.store.save("p1", "safety", self.changes, 0, creating=True)
        before = self.store.get("p1", "safety")
        with self.db.session() as session:
            audits = list(session.scalars(select(ProjectAuditEventRecord.audit_id)))
        with self.assertRaises(HTTPException) as error:
            self.store.save("p1", "safety", {"approved": True}, 1, approval_reason="isolated check")
        self.assertEqual(409, error.exception.status_code)
        self.assertEqual(assignment_id, error.exception.detail["projectModelId"])
        self.assertEqual(before, self.store.get("p1", "safety"))
        self.db.close()
        self.assertEqual(before, self.store.get("p1", "safety"))
        with self.db.session() as session:
            self.assertEqual(audits, list(session.scalars(select(ProjectAuditEventRecord.audit_id))))
            self.assertNotIn("schemaVersion", session.get(ProjectModelAssignmentRecord, assignment_id).parameter_snapshot)
        # Recover through the real assignment writer, not by patching the approved scene.
        self.assignments.save("p1", "person", "1.0.0", "pc", 0, True, 1)
        approved = self.store.save("p1", "safety", {"approved": True}, 1, approval_reason="explicit recovery")
        self.assertEqual(2, approved["revision"])
        self.assertTrue(approved["approved"])
        self.assertTrue(all(m["parameterSnapshot"]["schemaVersion"] == 2 for m in approved["models"]))
        frozen = deepcopy(approved)
        self.db.close()
        self.assertEqual(frozen, self.store.get("p1", "safety"))


class SceneSnapshotApprovalSqliteTests(SnapshotStorageChecks, fixtures.SceneSqliteTests):
    pass


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "isolated PostgreSQL is opt-in")
class SceneSnapshotApprovalPostgresTests(SnapshotStorageChecks, fixtures.SceneSqliteTests):
    use_postgresql = True
