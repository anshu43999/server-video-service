import copy
import unittest

from app.alert_advice_knowledge import AlertAdviceKnowledgeStore, helmet_mock_seed
from app.alert_advice_service import (
    AlertAdviceService,
    GenerationFailure,
    MockAdviceGenerator,
    MockKnowledgeRetriever,
    RetrievedKnowledge,
    RetrievalFailure,
)


class WrongKeyRetriever:
    provider = "SIMULATED_KNOWLEDGE_BASE"

    def retrieve(self, project_id, event_snapshot, match_key):
        seed = helmet_mock_seed()["payload"]
        return RetrievedKnowledge(
            "wrong", 1, ("PPE_NO_HELMET", "HELMET"), seed["adviceTemplate"],
            tuple(seed["references"]), seed["riskDescription"], seed["applicability"],
        )


class EmptyReferenceRetriever:
    provider = "SIMULATED_KNOWLEDGE_BASE"

    def retrieve(self, project_id, event_snapshot, match_key):
        seed = helmet_mock_seed()["payload"]
        return RetrievedKnowledge(
            "empty-reference", 1, match_key, seed["adviceTemplate"], tuple(),
            seed["riskDescription"], seed["applicability"],
        )


class MediaTrap(dict):
    def get(self, key, default=None):
        if key in {"evidenceBytes", "snapshotDataUrl", "localPath", "objectStorageCredentials"}:
            raise AssertionError("media field was read")
        return super().get(key, default)


class AlertAdviceServiceTests(unittest.TestCase):
    def setUp(self):
        self.store = AlertAdviceKnowledgeStore()
        self.store.ensure_mock_seed("project-a")
        self.event = {
            "eventId": "event-1", "alertTypeId": " ppe_no_helmet ",
            "recognitionCategoryId": "head", "evidenceBytes": b"private",
            "snapshotDataUrl": "data:image/jpeg;base64,private", "displayName": "未佩戴安全帽",
        }

    def service(self, *, retrieval_failure=None, generation_failure=None):
        return AlertAdviceService(
            MockKnowledgeRetriever(self.store, failure=retrieval_failure),
            MockAdviceGenerator(failure=generation_failure),
        )

    def test_generated_exact_match_uses_simulated_providers_and_snapshot_revision(self):
        result = self.service().generate("project-a", MediaTrap(self.event))
        self.assertEqual("GENERATED", result["status"])
        self.assertEqual({"alertTypeId": "PPE_NO_HELMET", "recognitionCategoryId": "HEAD"}, result["matchKey"])
        self.assertEqual("mock-ppe-no-helmet-head", result["knowledgeEntryId"])
        self.assertEqual(1, result["knowledgeRevision"])
        self.assertEqual("SIMULATED_KNOWLEDGE_BASE", result["retrievalProvider"])
        self.assertEqual("SIMULATED_LLM", result["generationProvider"])
        self.assertTrue(result["advice"]["steps"])
        self.assertTrue(result["references"])
        self.assertNotIn("evidenceBytes", str(result))
        self.assertNotIn("snapshotDataUrl", str(result))

    def test_event_fallback_is_stable_and_never_uses_display_or_model_name(self):
        fallback = self.service().generate("project-a", {"ruleId": "ppe_no_helmet", "label": "head"})
        self.assertEqual("GENERATED", fallback["status"])
        missing = self.service().generate("project-a", {"displayName": "PPE_NO_HELMET", "modelName": "HEAD"})
        self.assertEqual("NO_MATCH", missing["status"])
        self.assertEqual("EVENT_MATCH_KEY_UNAVAILABLE", missing["reasonCode"])

    def test_no_match_does_not_fall_back_across_category_or_project(self):
        category = self.service().generate("project-a", {**self.event, "recognitionCategoryId": "HELMET"})
        other_project = self.service().generate("project-b", self.event)
        self.assertEqual("KNOWLEDGE_NOT_MATCHED", category["reasonCode"])
        self.assertEqual("KNOWLEDGE_NOT_MATCHED", other_project["reasonCode"])

    def test_retrieval_failure_and_key_mismatch_are_terminal_without_generation(self):
        failed = self.service(retrieval_failure=RetrievalFailure("SIMULATED_RETRIEVER_FAILURE")).generate("project-a", self.event)
        self.assertEqual("FAILED_RETRIEVAL", failed["status"])
        self.assertEqual("RETRIEVING", failed["error"]["stage"])
        mismatch = AlertAdviceService(WrongKeyRetriever(), MockAdviceGenerator()).generate("project-a", self.event)
        self.assertEqual("FAILED_RETRIEVAL", mismatch["status"])
        self.assertEqual("RETRIEVAL_KEY_MISMATCH", mismatch["reasonCode"])
        self.assertFalse(mismatch["error"]["retryable"])

    def test_generation_failure_preserves_references_as_partial(self):
        result = self.service(generation_failure=GenerationFailure("SIMULATED_GENERATOR_FAILURE")).generate("project-a", self.event)
        self.assertEqual("PARTIAL", result["status"])
        self.assertIsNone(result["advice"])
        self.assertTrue(result["references"])
        self.assertEqual("SIMULATED_GENERATOR_FAILURE", result["error"]["code"])

    def test_knowledge_without_steps_is_partial_and_steps_are_not_invented(self):
        payload = copy.deepcopy(helmet_mock_seed()["payload"])
        payload["adviceTemplate"]["steps"] = []
        self.store.create("project-a", "policy-only", "FIRE", "SMOKE", payload, "owner")
        result = self.service().generate("project-a", {"alertTypeId": "FIRE", "recognitionCategoryId": "SMOKE"})
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual("KNOWLEDGE_HAS_NO_ADVICE_STEPS", result["reasonCode"])
        self.assertIsNone(result["advice"])
        self.assertTrue(result["references"])

    def test_generation_failure_without_references_is_failed_generation(self):
        service = AlertAdviceService(
            EmptyReferenceRetriever(), MockAdviceGenerator(failure=GenerationFailure("SIMULATED_GENERATOR_FAILURE")),
        )
        result = service.generate("project-a", self.event)
        self.assertEqual("FAILED_GENERATION", result["status"])
        self.assertEqual([], result["references"])


if __name__ == "__main__":
    unittest.main()
