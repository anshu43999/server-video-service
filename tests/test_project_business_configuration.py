import copy
import hashlib
import json
import tempfile
import unittest
from types import SimpleNamespace
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.alerts.delivery import AlertDeliveryService, DeliveryError, LocalExternalAdapter
from app.alerts.verification import AlertVerificationStore, VerificationConfigConflict
from app.alerts.rules import RuleRegistry, RuleConflict
from app.alerts.disposition import AlertDispositionStore
from app.alerts.runtime import ServerAlertRuntime
from app.detection import Detection, InferenceResult, NormalizedBox
from app.dashboard import DashboardStatsService
from app.database import Base, DEFAULT_PROJECT_ID, DatabaseManager, ModelParameterProfileRecord, ProjectRecord
from app.model_parameters import ModelParameterConflict, ModelParameterStore
from app.project_auth import reset_memory_project_authorization_for_tests, set_memory_project
from app.project_delivery_policy import DeliveryPolicyConflict, ProjectDeliveryPolicyStore
from app.model_catalog import ModelCatalog
from app.project_business import _memory_model_assignments
from app.project_model_assignments import ProjectModelAssignments
from app.project_management import memory_audits_for_tests
from app.stream_config import StreamConfigStore, StreamConfiguration
from project_api_support import ProjectApiSupport
import app.main as main_module


MODEL = {"modelId": "business-model", "name": "Business model", "version": "1.0.0", "labels": ["head"]}


def parameter_values(store):
    profile = store.default_profile(MODEL, "server")
    return {"detection": copy.deepcopy(profile["detection"]),
            "alertRules": copy.deepcopy(profile["alertRules"])}


class ProjectBusinessMemoryTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        reset_memory_project_authorization_for_tests()

    def test_platform_default_project_override_and_reset_are_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ModelParameterStore(Path(directory) / "profiles.json")
            platform = parameter_values(store)
            platform["detection"]["confidenceThreshold"] = 0.4
            store.save(MODEL, "server", platform, "platform-admin", 0)

            project = store.get(MODEL, "server", DEFAULT_PROJECT_ID)
            self.assertEqual(project["source"], "inherited")
            self.assertEqual(project["revision"], 0)
            self.assertEqual(project["detection"]["confidenceThreshold"], 0.4)

            override = parameter_values(store)
            override["detection"]["confidenceThreshold"] = 0.52
            saved = store.save(MODEL, "server", override, "owner", 0, DEFAULT_PROJECT_ID)
            self.assertEqual(saved["revision"], 1)
            self.assertEqual(store.get(MODEL, "server")["detection"]["confidenceThreshold"], 0.4)
            with self.assertRaises(ModelParameterConflict):
                store.save(MODEL, "server", override, "stale", 0, DEFAULT_PROJECT_ID)

            reset = store.reset(MODEL, "server", "owner", DEFAULT_PROJECT_ID, 1)
            self.assertEqual(reset["source"], "inherited")
            self.assertEqual(reset["revision"], 2)
            self.assertEqual(reset["detection"]["confidenceThreshold"], 0.4)

            platform["detection"]["confidenceThreshold"] = 0.5
            store.save(MODEL, "server", platform, "platform-admin", 1)
            inherited = store.get(MODEL, "server", DEFAULT_PROJECT_ID)
            self.assertEqual(inherited["revision"], 2)
            self.assertEqual(inherited["inheritedRevision"], 2)
            self.assertEqual(inherited["detection"]["confidenceThreshold"], 0.5)

    async def test_delivery_policy_filters_channels_severity_and_project_lifecycle(self):
        project_id = "delivery-project"
        set_memory_project(project_id, "delivery-project")
        service = AlertDeliveryService(database_manager=None, retry_delay_seconds=0)
        service.policy_store.save(project_id, {
            "enabled": True, "channels": ["management"], "minimumSeverity": "MAJOR",
        }, 0)
        self.assertEqual(service.dispatch({"eventId": "minor", "severity": "MINOR"},
                                          ["management", "app"], project_id=project_id), [])
        ids = service.dispatch({"eventId": "important", "severity": "IMPORTANT"},
                               ["management", "app"], project_id=project_id)
        self.assertEqual(len(ids), 1)
        await service.drain()
        with self.assertRaises(DeliveryPolicyConflict):
            service.policy_store.save(project_id, {
                "enabled": False, "channels": [], "minimumSeverity": "MINOR",
            }, 0)
        set_memory_project(project_id, "delivery-project", lifecycle_state="ARCHIVED", revision=2)
        self.assertEqual(service.dispatch({"eventId": "critical", "severity": "CRITICAL"},
                                          ["management"], project_id=project_id), [])

    async def test_delivery_retry_is_cancelled_when_project_changes_lifecycle(self):
        project_id = "delivery-retry-project"
        set_memory_project(project_id, project_id)

        class SuspendAfterFailure(LocalExternalAdapter):
            async def send(inner_self, event):
                if inner_self.attempts == 0:
                    inner_self.attempts += 1
                    set_memory_project(project_id, project_id, lifecycle_state="SUSPENDED", revision=2)
                    raise DeliveryError("transient failure")
                await super().send(event)

        channel = SuspendAfterFailure("management")
        service = AlertDeliveryService(channels={"management": channel}, retry_delay_seconds=0)
        ids = service.dispatch({"eventId": "retry-stop", "severity": "CRITICAL"}, ["management"], project_id=project_id)
        self.assertEqual(1, len(ids))
        receipts = await service.drain()
        self.assertEqual("cancelled", receipts[0].status)
        self.assertEqual(1, channel.attempts)

    def test_verification_revision_conflict_does_not_change_policy_or_quota(self):
        store = AlertVerificationStore()
        first = store.configure(enabled=True, image_egress_authorized=True, daily_limit=2,
                                model_id="review-a", provider_configured=False,
                                project_id="verification-a", expected_revision=0)
        self.assertEqual(first["revision"], 1)
        event = {"eventId": "event-1", "projectId": "verification-a"}
        store.request(event, actor="owner", image_ref="image", project_id="verification-a")
        self.assertEqual(store.config("verification-a")["callsToday"], 0)
        with self.assertRaises(VerificationConfigConflict):
            store.configure(enabled=False, image_egress_authorized=False, daily_limit=0,
                            model_id="stale", provider_configured=False,
                            project_id="verification-a", expected_revision=0)
        current = store.config("verification-a")
        self.assertTrue(current["enabled"])
        self.assertEqual(current["dailyLimit"], 2)
        self.assertEqual(current["callsToday"], 0)
        self.assertEqual(current["modelId"], "review-a")

    def test_actual_runtime_and_dashboard_use_project_parameters_and_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ModelParameterStore(Path(directory) / "profiles.json")
            for pid, threshold in (("runtime-a", 0.55), ("runtime-b", 0.95)):
                values = parameter_values(store)
                values["alertRules"][0]["camera"]["minimumConfidence"] = threshold
                store.save(MODEL, "server", values, "owner", 0, pid)
            events = AlertDispositionStore()
            delivery = SimpleNamespace(dispatch=lambda *args, **kwargs: [])
            runtime = ServerAlertRuntime(lambda model_id: MODEL, store, events, delivery, Path(directory) / "evidence")
            result = InferenceResult(detections=(Detection(0, "head", 0.9, NormalizedBox(.1, .1, .2, .3)),),
                                     model_id=MODEL["modelId"], class_names=("head",), provides=("BOX",))
            now = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
            for offset in (900_000, 700_000, 500_000, 100_000):
                for pid in ("runtime-a", "runtime-b"):
                    runtime.process(source_id="same-source", project_id=pid, captured_at_us=now-offset, result=result)
            self.assertEqual(1, len(events.list(project_id="runtime-a")))
            self.assertEqual([], events.list(project_id="runtime-b"))
            verification = AlertVerificationStore()
            for pid, limit in (("runtime-a", 2), ("runtime-b", 9)):
                verification.configure(enabled=True, image_egress_authorized=True, daily_limit=limit,
                                       model_id="review", provider_configured=False, project_id=pid, expected_revision=0)
            verification.request(events.list(project_id="runtime-a")[0], actor="owner", image_ref="image", project_id="runtime-a")
            streams = {"a": SimpleNamespace(project_id="runtime-a", frames_received=1, last_error=None),
                       "b": SimpleNamespace(project_id="runtime-b", frames_received=0, last_error="error")}
            dashboard = DashboardStatsService(None, events, verification)
            a, b = (dashboard.build("today", streams, {}, pid) for pid in ("runtime-a", "runtime-b"))
            self.assertEqual((1, 0, 2), (a["summary"]["totalEvents"], a["verification"]["used"], a["verification"]["limit"]))
            self.assertEqual((0, 0, 9), (b["summary"]["totalEvents"], b["verification"]["used"], b["verification"]["limit"]))
            self.assertEqual(1, a["streams"]["online"])
            self.assertEqual(1, b["streams"]["errors"])

    def test_rules_same_identifiers_are_isolated_in_memory(self):
        assert_rule_isolation(self, RuleRegistry())


def assert_rule_isolation(test, store):
    rule = {"ruleId": "same-rule", "operator": "LINE_CROSS", "requires": ["BOX"]}
    for pid in ("project-a", "project-b"):
        store.upsert(rule, project_id=pid, expected_revision=0, actor="owner", request_id="rule-create")
    rejected = store.bind("same-rule", "same-source", ["BOX"], project_id="project-a", expected_revision=1, request_id="rule-reject")
    test.assertFalse(rejected["accepted"])
    test.assertIn("TRACK", rejected["missing"])
    bound = store.bind("same-rule", "same-source", ["BOX", "TRACK"], project_id="project-a", expected_revision=2, request_id="rule-bind")
    test.assertTrue(bound["accepted"])
    test.assertEqual([], store.bindings("same-rule", "project-b"))
    with test.assertRaises(RuleConflict):
        store.delete("same-rule", project_id="project-a", expected_revision=2)
    store.delete("same-rule", project_id="project-a", expected_revision=3)
    with test.assertRaises(KeyError):
        store.get("same-rule", "project-a")
    test.assertEqual(1, store.get("same-rule", "project-b")["ruleVersion"])
    audits = store.audits("same-rule", "project-a")
    test.assertEqual(["create", "reject", "bind", "delete"], [item["action"] for item in audits])
    test.assertEqual(1, audits[0]["after"]["ruleVersion"])
    test.assertEqual("rule-reject", audits[1]["requestId"])
    test.assertIn("before", audits[1])
    test.assertEqual(rejected, audits[2]["before"])
    test.assertEqual(bound, audits[2]["after"])


class ProjectBusinessSqliteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp.close()
        self.path = Path(temp.name)
        self.database = DatabaseManager(f"sqlite:///{self.path.as_posix()}")
        Base.metadata.create_all(self.database.engine)
        now = datetime.now(timezone.utc)
        with self.database.session() as session:
            for project_id in (DEFAULT_PROJECT_ID, "project-a", "project-b"):
                session.add(ProjectRecord(project_id=project_id, project_code=project_id,
                                          display_name=project_id, created_at=now, updated_at=now))

    def tearDown(self):
        self.database.close()
        self.path.unlink(missing_ok=True)

    def test_project_parameters_are_isolated_and_legacy_key_shape_remains_readable(self):
        store = ModelParameterStore(Path(str(self.path) + ".json"), self.database)
        values_a = parameter_values(store)
        values_b = parameter_values(store)
        values_a["detection"]["confidenceThreshold"] = 0.45
        values_b["detection"]["confidenceThreshold"] = 0.52
        store.save(MODEL, "server", values_a, "owner-a", 0, "project-a")
        store.save(MODEL, "server", values_b, "owner-b", 0, "project-b")
        self.assertEqual(store.get(MODEL, "server", "project-a")["detection"]["confidenceThreshold"], 0.45)
        self.assertEqual(store.get(MODEL, "server", "project-b")["detection"]["confidenceThreshold"], 0.52)
        with self.database.session() as session:
            rows = session.query(ModelParameterProfileRecord).filter(
                ModelParameterProfileRecord.project_id.in_(["project-a", "project-b"])).all()
            self.assertEqual({row.scope for row in rows}, {"PROJECT"})
            self.assertTrue(all(row.profile_key.startswith("mp-") for row in rows))

    def test_delivery_policies_are_project_scoped_and_persistent(self):
        store = ProjectDeliveryPolicyStore(self.database)
        store.save("project-a", {"enabled": True, "channels": ["app"],
                                  "minimumSeverity": "MAJOR"}, 0)
        store.save("project-b", {"enabled": False, "channels": ["management"],
                                  "minimumSeverity": "CRITICAL"}, 0)
        reopened = ProjectDeliveryPolicyStore(self.database)
        self.assertEqual(reopened.get("project-a")["channels"], ["app"])
        self.assertFalse(reopened.get("project-b")["enabled"])
        with self.assertRaises(DeliveryPolicyConflict):
            reopened.save("project-a", {"enabled": False, "channels": [],
                                         "minimumSeverity": "MINOR"}, 0)

    def test_rules_same_identifiers_are_isolated_in_database(self):
        assert_rule_isolation(self, RuleRegistry(self.database))

    def test_default_project_override_and_platform_profile_coexist(self):
        store = ModelParameterStore(Path(str(self.path) + ".json"), self.database)
        values = parameter_values(store)
        values["detection"]["confidenceThreshold"] = .4
        store.save(MODEL, "server", values, "admin", 0)
        values["detection"]["confidenceThreshold"] = .52
        store.save(MODEL, "server", values, "owner", 0, DEFAULT_PROJECT_ID)
        with self.database.session() as session:
            rows = session.query(ModelParameterProfileRecord).filter_by(project_id=DEFAULT_PROJECT_ID).all()
            self.assertEqual({"PLATFORM", "PROJECT"}, {row.scope for row in rows})
            self.assertEqual(2, len({row.profile_key for row in rows}))
        store.reset(MODEL, "server", "owner", DEFAULT_PROJECT_ID, 1)
        values["detection"]["confidenceThreshold"] = .5
        store.save(MODEL, "server", values, "admin", 1)
        inherited = store.get(MODEL, "server", DEFAULT_PROJECT_ID)
        self.assertEqual((2, 2, .5), (inherited["revision"], inherited["inheritedRevision"], inherited["detection"]["confidenceThreshold"]))

    def test_file_import_does_not_promote_project_override_to_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            legacy = ModelParameterStore(path)
            values = parameter_values(legacy)
            values["detection"]["confidenceThreshold"] = .4
            legacy.save(MODEL, "server", values, "admin", 0)
            values["detection"]["confidenceThreshold"] = .52
            legacy.save(MODEL, "server", values, "owner", 0, DEFAULT_PROJECT_ID)
            imported = ModelParameterStore(path, self.database)
            self.assertEqual(.4, imported.get(MODEL, "server")["detection"]["confidenceThreshold"])
            self.assertEqual("inherited", imported.get(MODEL, "server", DEFAULT_PROJECT_ID)["source"])
            with self.database.session() as session:
                self.assertEqual(1, session.query(ModelParameterProfileRecord).count())


class ProjectBusinessApiTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = ExitStack()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.patches.close)
        models = Path(self.temp.name) / "models"
        models.mkdir()
        artifact = models / "business.pt"
        artifact.write_bytes(b"business-model")
        registry = models / "registry.json"
        registry.write_text(json.dumps({"models": [{
            **MODEL, "scenario": "ppe", "purpose": "test", "runtime": "server-pt",
            "format": "pt", "path": "models/" + artifact.name, "sizeBytes": artifact.stat().st_size,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(), "releaseStatus": "PUBLISHED",
            "status": "PUBLISHED", "releaseEligible": True,
            "artifacts": [{"artifactId": "server", "format": "pt", "platform": "server",
                           "path": "models/" + artifact.name, "sizeBytes": artifact.stat().st_size,
                           "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}],
        }]}), encoding="utf-8")
        self.patches.enter_context(patch.object(main_module, "model_catalog", ModelCatalog(registry)))
        self.patches.enter_context(patch.object(
            main_module, "model_parameter_store", ModelParameterStore(models / "profiles.json")))
        self.patches.enter_context(patch.dict(_memory_model_assignments, {}, clear=True))
        self.patches.enter_context(patch.object(main_module, "rule_registry", RuleRegistry()))
        self.patches.enter_context(patch.object(main_module, "stream_config_store", StreamConfigStore(None)))
        self.patches.enter_context(patch.object(main_module, "project_model_assignments",
            ProjectModelAssignments(None, main_module.model_catalog, main_module.model_parameter_store,
                                    main_module.stream_config_store)))
        self.patches.enter_context(patch.object(main_module, "streams", main_module.ProjectStreamRegistry()))
        self.patches.enter_context(patch.object(main_module, "alert_delivery", AlertDeliveryService()))
        self.patches.enter_context(patch.object(main_module, "alert_verification_store", AlertVerificationStore()))
        self.start_project_api("business-api")
        main_module.project_model_assignments.save(self.project_id, MODEL["modelId"],
            MODEL["version"], "pc", 0, True, 0)
        account = self.client.post("/aiyoloapi/platform/accounts", headers=self.headers, json={
            "username": "business-user", "password": "temporary-test-password", "platformRole": "NORMAL_USER",
        }).json()
        self.client.post(self.project_path + "/members", headers=self.headers, json={
            "accountId": account["accountId"], "projectRole": "PROJECT_USER",
        })
        login = self.client.post("/aiyoloapi/auth/login", json={
            "username": "business-user", "password": "temporary-test-password",
        }).json()
        self.user_headers = {"Authorization": "Bearer " + login["accessToken"]}
        self.parameters = self.project_path + "/models/business-model/parameters?platform=server"

    def tearDown(self):
        self.stop_project_api()
        self.patches.close()
        self.temp.cleanup()

    def test_assignment_permissions_revision_and_session_actor(self):
        initial = self.client.get(self.parameters, headers=self.headers)
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.json()["source"], "inherited")
        values = parameter_values(main_module.model_parameter_store)
        values["detection"]["confidenceThreshold"] = 0.5
        self.assertEqual(self.client.put(self.parameters, headers=self.headers, json=values).status_code, 422)
        saved = self.client.put(self.parameters, headers={**self.headers, "X-Operator-Id": "forged"},
                                json={**values, "expectedRevision": 0})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["audit"][-1]["actor"], self.account_id)
        self.assertEqual(self.client.put(self.parameters, headers=self.headers,
                                         json={**values, "expectedRevision": 0}).status_code, 409)
        self.assertEqual(self.client.get(self.parameters, headers=self.user_headers).status_code, 200)
        self.assertEqual(self.client.put(self.parameters, headers=self.user_headers,
                                         json={**values, "expectedRevision": 1}).status_code, 403)

        other = self.client.post("/aiyoloapi/projects", headers=self.headers, json={
            "projectCode": "business-other", "displayName": "Other", "ownerAccountId": self.account_id,
        }).json()["projectId"]
        self.assertEqual(self.client.get(
            f"/aiyoloapi/projects/{other}/models/business-model/parameters?platform=server",
            headers=self.headers).status_code, 404)

    def test_rule_sources_are_server_derived_and_project_scoped(self):
        main_module.stream_config_store.create(StreamConfiguration(
            stream_id="stored-source", display_name="Stored", source_type="websocket", source_url=None,
            model_id=MODEL["modelId"], yolo_enabled=True, confidence=.5, max_fps=10,
            overlay_enabled=True, enabled=False, project_id=self.project_id))
        main_module.streams[("another-project", "foreign-source")] = SimpleNamespace(
            close=AsyncMock(), model_metadata=lambda: {"modelId": MODEL["modelId"], "provides": ["BOX", "TRACK"]})
        sources = self.client.get(self.project_path + "/capabilities/sources", headers=self.headers)
        self.assertEqual(["stored-source"], [item["sourceId"] for item in sources.json()["sources"]])
        rule = {"ruleId": "line", "name": "Line crossing", "operator": "LINE_CROSS", "requires": ["BOX"]}
        self.assertEqual(201, self.client.post(self.project_path + "/rules", headers=self.headers, json=rule).status_code)
        target = self.project_path + "/rules/line/validate"
        foreign = self.client.post(target, headers=self.headers, json={"sourceId": "foreign-source", "capabilities": ["BOX", "TRACK"]})
        self.assertEqual(404, foreign.status_code)
        mismatch = self.client.post(target, headers=self.headers, json={"sourceId": "stored-source", "modelId": "forged"})
        self.assertEqual(409, mismatch.status_code)
        forged = self.client.post(target, headers=self.headers, json={"sourceId": "stored-source", "capabilities": ["BOX", "TRACK"]})
        self.assertFalse(forged.json()["accepted"])
        self.assertIn("TRACK", forged.json()["missing"])

    def test_metrics_aggregate_only_selected_project_and_hide_platform_details(self):
        main_module.streams[(self.project_id, "local")] = SimpleNamespace(
            close=AsyncMock(), metrics=lambda: {"frames_received": 7, "frames_processed": 5, "frames_dropped": 2, "secret": "driver"})
        main_module.streams[("another-project", "foreign")] = SimpleNamespace(
            close=AsyncMock(), metrics=lambda: {"frames_received": 900, "frames_processed": 800, "frames_dropped": 100})
        metrics = self.client.get(self.project_path + "/metrics", headers=self.user_headers)
        self.assertEqual(200, metrics.status_code)
        self.assertEqual({"total": 1, "framesReceived": 7, "framesProcessed": 5, "framesDropped": 2}, metrics.json()["streams"])
        self.assertNotIn("system", metrics.json())
        self.assertNotIn("foreign", metrics.text)
        self.assertEqual(403, self.client.get("/aiyoloapi/metrics", headers=self.user_headers).status_code)
        self.assertEqual(200, self.client.get("/aiyoloapi/metrics", headers=self.headers).status_code)

    def test_archived_configuration_is_read_only_and_session_audit_is_complete(self):
        values = parameter_values(main_module.model_parameter_store)
        saved = self.client.put(self.parameters, headers={**self.headers, "X-Request-Id": "project-config-request"},
                                json={**values, "expectedRevision": 0})
        self.assertEqual(200, saved.status_code)
        audits = memory_audits_for_tests()["project"]
        audit = next(item for item in audits if item["requestId"] == saved.headers['x-request-id'])
        self.assertEqual(self.account_id, audit["actorAccountId"])
        self.assertIsNone(audit["previousRevision"])
        self.assertEqual(1, audit["newRevision"])
        self.assertIn("before", audit["changeSummary"])
        self.assertIn("after", audit["changeSummary"])
        platform = "/aiyoloapi/platform/models/business-model/parameters?platform=server"
        platform_saved = self.client.put(platform, headers={**self.headers, "X-Request-Id": "platform-config-request"},
                                         json={**values, "expectedRevision": 0})
        self.assertEqual(200, platform_saved.status_code)
        self.assertTrue(any(item["requestId"] == platform_saved.headers['x-request-id'] for item in memory_audits_for_tests()["platform"]))
        archived = self.client.post(self.project_path + "/archive", headers=self.headers, json={"expectedRevision": 1})
        self.assertEqual(200, archived.status_code)
        self.assertEqual(200, self.client.get(self.parameters, headers=self.headers).status_code)
        self.assertEqual(403, self.client.put(self.parameters, headers=self.headers, json={**values, "expectedRevision": 1}).status_code)
        self.assertEqual(403, self.client.put(self.project_path + "/delivery/policy", headers=self.headers,
                                             json={"enabled": False, "channels": [], "minimumSeverity": "MINOR", "expectedRevision": 0}).status_code)
        self.assertEqual(404, self.client.get(self.parameters, headers=self.user_headers).status_code)


if __name__ == "__main__":
    unittest.main()
