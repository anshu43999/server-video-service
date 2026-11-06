import copy
import tempfile
import unittest
import uuid
from pathlib import Path

from sqlalchemy import select

from app.alert_advice_knowledge import (
    ACTIVE,
    INACTIVE,
    AlertAdviceKnowledgeStore,
    KnowledgeConflict,
    KnowledgeMatchConflict,
    helmet_mock_seed,
    normalize_match_key,
)
from app.database import (
    AlertAdviceKnowledgeRevisionRecord,
    Base,
    DatabaseManager,
    ProjectRecord,
)


ROOT = Path(__file__).resolve().parents[1]


class AlertAdviceKnowledgeStoreTest(unittest.TestCase):
    def setUp(self):
        (ROOT / ".test-db").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".test-db")
        path = Path(self.temp.name) / "knowledge.db"
        self.database = DatabaseManager(f"sqlite+pysqlite:///{path.as_posix()}")
        Base.metadata.create_all(self.database.engine)
        self.project_a = str(uuid.uuid4())
        self.project_b = str(uuid.uuid4())
        with self.database.session() as session:
            session.add_all([
                ProjectRecord(project_id=self.project_a, project_code="advice-a", display_name="Advice A"),
                ProjectRecord(project_id=self.project_b, project_code="advice-b", display_name="Advice B"),
            ])
        self.store = AlertAdviceKnowledgeStore(self.database)

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    @staticmethod
    def seed_payload():
        return copy.deepcopy(helmet_mock_seed()["payload"])

    def test_normalization_matches_android_contract(self):
        self.assertEqual(("PPE_NO_HELMET", "HEAD"), normalize_match_key(" ppe_no_helmet ", "head"))

    def test_create_find_revision_and_reopen(self):
        item, created = self.store.ensure_mock_seed(self.project_a)
        self.assertTrue(created)
        self.assertEqual(1, item["revision"])
        self.assertEqual("PPE_NO_HELMET", item["matchKey"]["alertTypeId"])
        self.assertEqual("HEAD", item["matchKey"]["recognitionCategoryId"])
        self.assertEqual(item["entryId"], self.store.find_active_exact(self.project_a, "ppe_no_helmet", "head")["entryId"])
        _, created_again = self.store.ensure_mock_seed(self.project_a)
        self.assertFalse(created_again)

        reopened = AlertAdviceKnowledgeStore(DatabaseManager(self.database.url))
        try:
            self.assertEqual(item["entryId"], reopened.get(self.project_a, item["entryId"])["entryId"])
        finally:
            reopened.database.close()

    def test_cas_status_and_immutable_revision_snapshots(self):
        item, _ = self.store.ensure_mock_seed(self.project_a)
        original = copy.deepcopy(item)
        changed = self.store.set_status(self.project_a, item["entryId"], INACTIVE, "owner", 1)
        self.assertEqual(2, changed["revision"])
        self.assertEqual(INACTIVE, changed["status"])
        self.assertIsNone(self.store.find_active_exact(self.project_a, "PPE_NO_HELMET", "HEAD"))
        with self.assertRaises(KnowledgeConflict):
            self.store.set_status(self.project_a, item["entryId"], ACTIVE, "stale", 1)

        payload = self.seed_payload()
        payload["title"] = "更新后的标题"
        updated = self.store.replace(self.project_a, item["entryId"], payload, "owner", 2, status=ACTIVE)
        self.assertEqual(3, updated["revision"])
        revisions = self.store.revisions(self.project_a, item["entryId"])
        self.assertEqual([1, 2, 3], [row["revision"] for row in revisions])
        self.assertEqual(["CREATE", "DEACTIVATE", "ACTIVATE"], [row["action"] for row in revisions])
        self.assertEqual(original["title"], revisions[0]["snapshot"]["title"])
        self.assertEqual("更新后的标题", revisions[2]["snapshot"]["title"])

    def test_match_key_unique_per_project_and_projects_are_isolated(self):
        self.store.ensure_mock_seed(self.project_a)
        duplicate = self.seed_payload()
        with self.assertRaises(KnowledgeMatchConflict):
            self.store.create(self.project_a, "duplicate", "PPE_NO_HELMET", "head", duplicate, "owner")

        other, created = self.store.ensure_mock_seed(self.project_b)
        self.assertTrue(created)
        self.assertEqual(self.project_b, other["projectId"])
        self.assertEqual(1, len(self.store.list(self.project_a)))
        self.assertEqual(1, len(self.store.list(self.project_b)))

    def test_normal_category_has_no_risk_advice(self):
        self.store.ensure_mock_seed(self.project_a)
        self.assertIsNone(self.store.find_active_exact(self.project_a, "PPE_HELMET_OK", "helmet"))
        self.assertIsNone(self.store.find_active_exact(self.project_a, "PPE_NO_HELMET", "helmet"))

    def test_revision_rows_are_append_only_for_store_operations(self):
        item, _ = self.store.ensure_mock_seed(self.project_a)
        self.store.set_status(self.project_a, item["entryId"], INACTIVE, "owner", 1)
        with self.database.session() as session:
            rows = session.scalars(select(AlertAdviceKnowledgeRevisionRecord).where(
                AlertAdviceKnowledgeRevisionRecord.project_id == self.project_a
            ).order_by(AlertAdviceKnowledgeRevisionRecord.revision)).all()
            self.assertEqual([1, 2], [row.revision for row in rows])
            self.assertEqual("ACTIVE", rows[0].snapshot["status"])
            self.assertEqual("INACTIVE", rows[1].snapshot["status"])


class AlertAdviceKnowledgeMemoryTest(unittest.TestCase):
    def test_explicit_memory_store_uses_same_cas_and_seed_semantics(self):
        store = AlertAdviceKnowledgeStore()
        item, created = store.ensure_mock_seed("project-memory")
        self.assertTrue(created)
        self.assertEqual(item["entryId"], store.find_active_exact("project-memory", "ppe_no_helmet", "head")["entryId"])
        with self.assertRaises(KnowledgeConflict):
            store.set_status("project-memory", item["entryId"], INACTIVE, "owner", 0)


if __name__ == "__main__":
    unittest.main()
