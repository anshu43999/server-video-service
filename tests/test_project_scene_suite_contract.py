import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "project_scene_suite_v2.json"


class ProjectSceneSuiteV2ContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.suite = self.fixture["suite"]
        self.members = {member["memberId"]: member for member in self.suite["models"]}
        self.plans = {plan["planId"]: plan for plan in self.suite["plans"]}

    def test_mixed_input_members_and_plan_specific_capabilities(self):
        self.assertEqual(2, self.suite["suiteContractVersion"])
        self.assertEqual({"image", "video"}, set(self.suite["inputTypes"]))
        self.assertEqual({"image"}, set(self.members["member-helmet-image"]["inputTypes"]))
        self.assertEqual({"video"}, set(self.members["member-ppe-video"]["inputTypes"]))
        self.assertEqual(["member-helmet-image"], self.plans["image-safety"]["memberIds"])
        self.assertEqual(["member-ppe-video"], self.plans["video-ppe"]["memberIds"])
        self.assertEqual("sync", self.plans["combined-image"]["execution"])
        self.assertFalse(self.plans["combined-image"]["executionSupported"])

    def test_every_plan_member_supports_every_plan_input(self):
        for plan in self.plans.values():
            for member_id in plan["memberIds"]:
                self.assertIn(member_id, self.members)
                self.assertTrue(
                    set(plan["inputTypes"]).issubset(self.members[member_id]["inputTypes"]),
                    f"{plan['planId']} selects an incompatible member",
                )

    def test_member_identity_is_stable_and_positions_are_not_identity(self):
        self.assertEqual(len(self.members), len(self.suite["models"]))
        self.assertEqual(len(self.plans), len(self.suite["plans"]))
        self.assertEqual({0, 1, 2}, {member["position"] for member in self.members.values()})
        for member in self.members.values():
            self.assertRegex(member["memberId"], r"^member-[a-z0-9-]+$")
            self.assertIn(member["target"], {"pc", "mobile"})

    def test_installation_is_partial_and_retention_has_many_sources(self):
        installation = self.suite["installation"]
        self.assertEqual("partial", installation["status"])
        self.assertNotEqual(set(installation["requiredMemberIds"]), set(installation["readyMemberIds"]))
        self.assertEqual("standalone", self.fixture["standaloneRetention"]["type"])
        self.assertEqual("suite", self.fixture["suiteRetention"]["type"])
        self.assertEqual(self.fixture["standaloneRetention"]["modelId"], "helmet")
        self.assertEqual(self.fixture["suiteRetention"]["memberId"], "member-helmet-image")

    def test_v2_fixture_does_not_claim_remote_video_or_multi_model_execution(self):
        self.assertNotIn("rtsp", json.dumps(self.fixture).lower())
        self.assertFalse(self.suite["executionSupported"])
        self.assertFalse(self.plans["combined-image"]["executionSupported"])

    def test_v3_multimember_resolve_is_explicit_and_not_runtime_authorization(self):
        contract = self.fixture["multiMemberResolveV3"]
        request, response = contract["request"], contract["response"]
        self.assertEqual(3, request["clientContractVersion"])
        self.assertEqual(["sync"], request["supportedExecutionModes"])
        self.assertEqual("sync", response["execution"])
        self.assertEqual(3, response["resolveContractVersion"])
        self.assertEqual(["member-helmet-image", "member-ppe-image"],
                         [member["memberId"] for member in response["members"]])
        for member in response["members"]:
            snapshot = member["parameterSnapshot"]
            self.assertEqual(("project-a", member["modelId"], member["version"], "android"),
                             (snapshot["projectId"], snapshot["modelId"], snapshot["modelVersion"],
                              snapshot["platform"]))
            self.assertEqual(member["parameterRevision"], snapshot["revision"])
            self.assertEqual(64, len(member["artifactSha256"]))
        self.assertTrue(response["resolutionOnly"])
        self.assertFalse(response["runtimeAuthorization"])


if __name__ == "__main__":
    unittest.main()
