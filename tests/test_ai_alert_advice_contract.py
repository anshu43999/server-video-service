import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "docs" / "ai-alert-advice-v1.schema.json"
GOLDEN = ROOT / "docs" / "ai-alert-advice-v1-golden.json"
CONTRACT = ROOT / "docs" / "ai-alert-advice-api-v1.md"


class AlertAdviceContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        cls.golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        cls.contract = CONTRACT.read_text(encoding="utf-8")

    def test_contract_assets_are_versioned_and_linked(self):
        self.assertEqual("1.0", self.golden["contractVersion"])
        version = self.schema["$defs"]["adviceGeneration"]["properties"]["contractVersion"]["const"]
        self.assertEqual("1.0", version)
        self.assertIn("ai-alert-advice-v1.schema.json", self.contract)

    def test_normalization_and_exact_match_do_not_fallback(self):
        vector = self.golden["normalization"][0]
        normalize = lambda value: value.strip().upper()
        actual = {key: normalize(value) for key, value in vector["input"].items()}
        self.assertEqual(vector["expected"], actual)
        for case in self.golden["exactMatchCases"]:
            request = tuple(normalize(value) for value in case["request"])
            self.assertEqual(case["matched"], tuple(case["knowledge"]) == request)
        self.assertIn("模型 ID、模型名称、展示名称、中文翻译、相似类别和证据内容都不能参与兜底匹配", self.contract)

    def test_generation_status_and_providers_are_closed_enums(self):
        generation = self.schema["$defs"]["adviceGeneration"]["properties"]
        self.assertEqual(
            {"GENERATED", "NO_MATCH", "PARTIAL", "FAILED_RETRIEVAL", "FAILED_GENERATION"},
            set(generation["status"]["enum"]),
        )
        self.assertEqual(
            {"SIMULATED_KNOWLEDGE_BASE", "KNOWLEDGE_BASE"},
            set(generation["retrievalProvider"]["enum"]),
        )
        self.assertEqual({"SIMULATED_LLM", "LLM"}, set(generation["generationProvider"]["enum"]))

    def test_generated_golden_separates_advice_from_policy_excerpt(self):
        generated = self.golden["generated"]
        self.assertEqual("GENERATED", generated["status"])
        self.assertTrue(generated["advice"]["steps"])
        self.assertTrue(generated["references"])
        instruction = generated["advice"]["steps"][0]["instruction"]
        excerpt = generated["references"][0]["excerpt"]
        self.assertNotEqual(instruction, excerpt)
        self.assertEqual("MOCK_KNOWLEDGE_BASE", generated["references"][0]["sourceType"])
        self.assertIn("模拟", generated["sourceNotice"])
        self.assertIn("不构成违规认定", generated["advice"]["cautions"][0])

    def test_no_match_and_partial_results_are_explicit(self):
        self.assertEqual("NO_MATCH", self.golden["noMatch"]["status"])
        self.assertEqual([], self.golden["noMatch"]["references"])
        self.assertEqual("NO_MATCH", self.golden["eventKeyUnavailable"]["status"])
        self.assertIsNone(self.golden["eventKeyUnavailable"]["matchKey"])
        self.assertEqual("PARTIAL", self.golden["partial"]["status"])
        self.assertTrue(self.golden["partial"]["referencesMustBePreserved"])

    def test_contract_forbids_media_and_automatic_disposition(self):
        properties = self.schema["$defs"]["adviceGeneration"]["properties"]
        for field in self.golden["forbiddenFields"]:
            self.assertNotIn(field, properties)
        self.assertIn("不得自动确认、关闭、标记误报告警或创建处置事实", self.contract)
        self.assertIn("不读取、复制或外发证据图片/视频", self.contract)

    def test_permission_matrix_has_separate_capabilities(self):
        capabilities = (
            "project.alert_knowledge.read",
            "project.alert_knowledge.manage",
            "project.alert_advice.generate",
            "project.alert_advice.read",
            "project.alert_advice.history.read",
        )
        for capability in capabilities:
            self.assertIn(capability, self.contract)

    def test_android_service_integration_golden_is_safe_and_complete(self):
        plan = json.loads((ROOT / "docs" / "mobile-alert-advice-service-integration-v1-golden.json").read_text(encoding="utf-8"))
        self.assertEqual("1.0", plan["serverContractVersion"])
        self.assertEqual("M114", plan["androidBaseline"])
        self.assertEqual({}, plan["request"]["body"])
        self.assertIn("/projects/project-a/alerts/event-helmet-1/", plan["request"]["path"])
        mapped = {item["serverStatus"]: item for item in plan["mappings"]}
        self.assertEqual({"GENERATED", "NO_MATCH", "PARTIAL", "FAILED_RETRIEVAL", "FAILED_GENERATION"}, set(mapped))
        self.assertTrue(mapped["PARTIAL"]["preserveReferences"])
        self.assertEqual("GENERATING", mapped["PARTIAL"]["stage"])
        self.assertTrue(plan["retry"]["unknownHttpOutcomeUsesSameIdempotencyKey"])
        self.assertFalse(plan["localModes"]["networkFailureMaySilentlyFallback"])
        self.assertFalse(plan["localModes"]["offlineGenerationAllowed"])
        forbidden = set(plan["forbiddenRequestFields"])
        self.assertTrue({"alertTypeId", "recognitionCategoryId", "snapshotDataUrl", "mediaUri", "internalPrompt"}.issubset(forbidden))
        self.assertIn("PROJECT_ID_MISMATCH", plan["requiredRejections"])
        self.assertIn("EVENT_ID_MISMATCH", plan["requiredRejections"])


if __name__ == "__main__":
    unittest.main()
