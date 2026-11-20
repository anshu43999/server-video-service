from knowledge_support import helmet_mock_seed
import copy
import unittest

from app.alert_advice_knowledge import (
    ACTIVE, INACTIVE, AlertAdviceKnowledgeStore, KnowledgeConflict, KnowledgeError,
    KnowledgeMatchConflict, KnowledgeNotFound, normalize_match_key,
)
from app.system_alert_knowledge import SystemKnowledgeStore
from app.system_knowledge_draft import SystemKnowledgeDraft


class SystemKnowledgeDraftTests(unittest.TestCase):
    def setUp(self):
        self.draft = SystemKnowledgeDraft()
        self.seed = helmet_mock_seed()
        self.first = self.draft.create(self.seed["entryId"], self.seed["alertTypeId"],
                                      self.seed["recognitionCategoryId"], self.seed["payload"], "admin")

    def test_normalization_and_global_key_uniqueness_include_inactive_entries(self):
        self.assertEqual(("PPE_NO_HELMET", "HEAD"), normalize_match_key(" ppe_no_helmet ", "head"))
        self.draft.set_status(self.first["entryId"], INACTIVE, "admin", 1)
        with self.assertRaises(KnowledgeMatchConflict):
            self.draft.create("duplicate", "ppe_no_helmet", "head", self.seed["payload"], "admin")

    def test_cas_status_and_immutable_revision_snapshots(self):
        changed = self.draft.set_status(self.first["entryId"], INACTIVE, "admin", 1)
        self.assertEqual(2, changed["revision"])
        with self.assertRaises(KnowledgeConflict):
            self.draft.set_status(self.first["entryId"], ACTIVE, "stale", 1)
        updated = copy.deepcopy(self.seed["payload"])
        updated["title"] = "Updated title"
        self.draft.replace(self.first["entryId"], updated, "admin", 2, status=ACTIVE)
        history = self.draft.snapshot()["history"][self.first["entryId"]]
        self.assertEqual([1, 2, 3], [row["revision"] for row in history])
        self.assertEqual(["CREATE", "DEACTIVATE", "ACTIVATE"], [row["action"] for row in history])
        self.assertEqual(self.first, history[0]["snapshot"])
        self.assertEqual("Updated title", history[2]["snapshot"]["title"])

    def test_draft_input_output_and_old_history_do_not_alias(self):
        source = self.draft.snapshot()
        draft = SystemKnowledgeDraft(source)
        changed = draft.replace(self.first["entryId"], self.seed["payload"], "admin", 1)
        changed["title"] = "Do not mutate storage"
        exported = draft.snapshot()
        exported["history"][self.first["entryId"]][0]["snapshot"]["title"] = "Do not mutate history"
        self.assertEqual(self.first["title"], draft.snapshot()["entries"][0]["title"])
        self.assertEqual(self.first, draft.snapshot()["history"][self.first["entryId"]][0]["snapshot"])
        self.assertEqual(1, source["entries"][0]["revision"])

    def test_validation_failure_does_not_change_draft(self):
        original = self.draft.snapshot()
        for entry_id in ("", "bad/id", "x" * 129):
            with self.assertRaises(KnowledgeError):
                self.draft.create(entry_id, "CUSTOM", "HEAD", self.seed["payload"], "admin")
        with self.assertRaises(KnowledgeError):
            self.draft.set_status(self.first["entryId"], "UNKNOWN", "admin", 1)
        with self.assertRaises(KnowledgeNotFound):
            self.draft.replace("missing", self.seed["payload"], "admin", 1)
        self.assertEqual(original, self.draft.snapshot())

    def test_system_store_rejects_unknown_operations_without_changing_catalog(self):
        system = SystemKnowledgeStore()
        original = system.catalog()
        with self.assertRaises(KnowledgeError):
            system.mutate("snapshot", "admin")
        self.assertEqual(original, system.catalog())


class PublishedKnowledgeReaderTests(unittest.TestCase):
    def test_reader_requires_system_and_has_no_project_writes_or_local_fallback(self):
        with self.assertRaises(TypeError):
            AlertAdviceKnowledgeStore()
        with self.assertRaises(ValueError):
            AlertAdviceKnowledgeStore(system=None)
        reader = AlertAdviceKnowledgeStore(system=SystemKnowledgeStore())
        for name in ("create", "replace", "set_status", "ensure_mock_seed", "local_list", "database"):
            self.assertFalse(hasattr(reader, name))

    def test_global_reads_are_exact_and_return_independent_context_snapshots(self):
        reader = AlertAdviceKnowledgeStore(system=SystemKnowledgeStore())
        first = reader.find_active_exact("project-a", "ppe_no_helmet", "head")
        other = reader.find_active_exact("project-b", "PPE_NO_HELMET", "HEAD")
        self.assertEqual("project-a", first["projectId"])
        self.assertEqual("project-b", other["projectId"])
        first["adviceTemplate"]["steps"].clear()
        self.assertTrue(reader.get("project-a", first["entryId"])["adviceTemplate"]["steps"])
        self.assertIsNone(reader.find_active_exact("project-a", "PPE_NO_HELMET", "helmet"))
        self.assertIsNone(reader.find_active_exact("project-a", "PPE_HELMET_OK", "helmet"))


if __name__ == "__main__":
    unittest.main()
