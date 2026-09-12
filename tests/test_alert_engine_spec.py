import json
import re
import unittest
from pathlib import Path


class AlertEngineSpecTests(unittest.TestCase):
    """公共告警引擎规格与 JSON Schema 的契约测试（M11-T01）。

    这份规格由服务端 M11 与 App 侧 M15 共用，是「一份规格两处实现」的唯一裁判。
    因此这里断言的是**冻结项**：改动本文件里的任何断言都意味着规格变更，必须先改
    docs/alert-engine-spec.md 与 docs/alert-engine.schema.json，再同步两侧实现。
    """

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.spec = (root / "docs/alert-engine-spec.md").read_text(encoding="utf-8")
        cls.schema = json.loads(
            (root / "docs/alert-engine.schema.json").read_text(encoding="utf-8")
        )
        cls.defs = cls.schema["$defs"]

    # --- 规格文档 -----------------------------------------------------------

    def test_spec_is_frozen_and_points_at_the_machine_contract(self) -> None:
        self.assertIn("状态：**冻结**", self.spec)
        self.assertIn("alert-engine.schema.json", self.spec)
        self.assertIn("alert-engine-conformance/", self.spec)

    def test_spec_is_an_alarm_engine_not_an_early_warning_engine(self) -> None:
        self.assertIn("这是一个**告警**引擎，不是预警引擎", self.spec)
        self.assertIn("趋势外推", self.spec)
        self.assertIn("不推测未来状态", self.spec)
        self.assertIn("不设「预警」档", self.spec)

    def test_spec_declares_the_five_layers(self) -> None:
        for layer in ("观测接入", "特征聚合", "规则求值", "事件生命周期", "投递处置"):
            self.assertIn(layer, self.spec)

    def test_spec_bans_the_system_clock_on_the_evaluation_path(self) -> None:
        self.assertIn("求值器是纯函数，时间只来自观测", self.spec)
        for banned in ("System.currentTimeMillis", "time.time()", "Instant.now()"):
            self.assertIn(banned, self.spec)

    def test_spec_keeps_the_engine_free_of_business_class_names(self) -> None:
        self.assertIn("引擎源码中不得出现任何业务类别名", self.spec)

    def test_spec_defines_five_subject_kinds(self) -> None:
        for kind in ("track:", "roi:", "metric:", "source:", "frame:"):
            self.assertIn(kind, self.spec)
        self.assertIn("subjectKey", self.spec)

    def test_spec_defines_seven_threshold_families(self) -> None:
        for field in (
            "minConfidence",
            "minConsecutiveFrames",
            "minDwellMs",
            "minCount",
            "minAreaRatio",
            "rateWindowMs",
            "minRateHits",
            "cooldownMs",
            "severityBands",
        ):
            self.assertIn(field, self.spec)
        self.assertIn("运行时可改", self.spec)
        self.assertIn("不重启进程", self.spec)

    def test_spec_requires_polygon_and_line_roi(self) -> None:
        for shape in ("RECT", "POLYGON", "LINE"):
            self.assertIn(shape, self.spec)
        self.assertIn("多边形是必须支持的形态", self.spec)
        self.assertIn("自相交", self.spec)

    def test_spec_separates_observed_severity_from_notification_severity(self) -> None:
        self.assertIn("notifySeverity", self.spec)
        self.assertIn("escalatedAtUs", self.spec)
        self.assertIn("提级**只影响通知**", self.spec)

    def test_spec_dedup_key_carries_severity(self) -> None:
        self.assertIn("(ruleId, sourceId, subjectKey, severity)", self.spec)
        self.assertIn("级别升高必然放行", self.spec)

    def test_spec_binds_the_app_side_to_the_same_contract(self) -> None:
        self.assertIn("M15", self.spec)
        self.assertIn("金样向量是唯一裁判", self.spec)
        self.assertIn("不允许", self.spec)

    def test_spec_marks_the_reserved_features_unimplemented(self) -> None:
        for reserved in ("RELATION", "METRIC_THRESHOLD", "COMPOSITE", "clipUri"):
            self.assertIn(reserved, self.spec)
        self.assertIn("OPERATOR_NOT_IMPLEMENTED", self.spec)

    # --- JSON Schema --------------------------------------------------------

    def test_schema_is_draft_2020_12_and_versioned(self) -> None:
        self.assertEqual(
            self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
        )
        self.assertEqual(self.schema["x-specVersion"], "v1")

    def test_schema_exposes_the_six_contract_objects(self) -> None:
        for name in (
            "Observation",
            "Rule",
            "Roi",
            "Event",
            "RejectionReason",
            "ConformanceVector",
        ):
            self.assertIn(name, self.defs)

    def test_schema_operator_enum_matches_the_spec(self) -> None:
        implemented = [
            "PRESENCE",
            "IN_REGION",
            "LINE_CROSS",
            "DWELL",
            "COUNT",
            "AREA_RATIO",
            "RATE",
            "ABSENCE",
        ]
        reserved = ["RELATION", "METRIC_THRESHOLD", "COMPOSITE"]
        self.assertEqual(
            self.defs["Operator"]["enum"], implemented + reserved
        )
        self.assertEqual(
            self.schema["x-notImplemented"]["operators"], reserved
        )

    def test_schema_severity_has_exactly_three_bands(self) -> None:
        self.assertEqual(
            self.defs["Severity"]["enum"], ["MINOR", "MAJOR", "CRITICAL"]
        )
        self.assertNotIn("WARNING", json.dumps(self.schema, ensure_ascii=False))

    def test_schema_capability_and_subject_kind_enums(self) -> None:
        self.assertEqual(
            self.defs["Capability"]["enum"],
            ["BOX", "TRACK", "MASK", "SCALAR", "POLYGON_ROI", "LINE_ROI"],
        )
        self.assertEqual(
            self.defs["SubjectKind"]["enum"],
            ["track", "roi", "metric", "source", "frame"],
        )

    def test_schema_subject_key_pattern_accepts_five_kinds_only(self) -> None:
        pattern = re.compile(self.defs["SubjectKey"]["pattern"])
        for good in ("track:12", "roi:pit-north", "metric:pm25-01", "source:cam-07", "frame:img-8a3f"):
            self.assertRegex(good, pattern)
        for bad in ("12", "zone:1", "track:", "track:a:b", "track:" + "x" * 65):
            self.assertNotRegex(bad, pattern)

    def test_schema_roi_requires_three_points_for_polygon_and_two_for_line(self) -> None:
        branches = self.defs["Roi"]["allOf"]
        polygon = next(b for b in branches if b["if"]["properties"]["shape"]["const"] == "POLYGON")
        line = next(b for b in branches if b["if"]["properties"]["shape"]["const"] == "LINE")
        self.assertEqual(polygon["then"]["properties"]["points"]["minItems"], 3)
        self.assertEqual(line["then"]["properties"]["points"]["minItems"], 2)
        self.assertEqual(line["then"]["properties"]["points"]["maxItems"], 2)
        self.assertIn("positiveDirection", line["then"]["required"])

    def test_schema_thresholds_cover_the_seven_families(self) -> None:
        self.assertEqual(
            set(self.defs["Thresholds"]["properties"]),
            {
                "minConfidence",
                "minConsecutiveFrames",
                "minDwellMs",
                "minCount",
                "minAreaRatio",
                "rateWindowMs",
                "minRateHits",
                "cooldownMs",
            },
        )
        self.assertIn("severityBands", self.defs["Rule"]["properties"])
        self.assertIn(
            "thresholdOverrides", self.defs["Rule"]["properties"]["scope"]["properties"]
        )

    def test_schema_timestamps_are_microseconds_and_durations_milliseconds(self) -> None:
        self.assertIn("微秒", self.defs["TimestampUs"]["description"])
        self.assertIn("毫秒", self.defs["DurationMs"]["description"])
        self.assertIn("capturedAtUs", self.defs["Observation"]["required"])

    def test_schema_reserves_clip_evidence_as_null(self) -> None:
        clip = self.defs["Event"]["properties"]["evidence"]["properties"]["clipUri"]
        self.assertEqual(clip["type"], "null")
        self.assertIn("FR-M11-EVIDENCE-DEPTH", clip["description"])

    def test_schema_event_keeps_fact_and_notification_severity_apart(self) -> None:
        props = self.defs["Event"]["properties"]
        for name in ("severity", "notifySeverity", "escalatedAtUs", "suppressedCount", "effectiveThresholds"):
            self.assertIn(name, props)
        for name in ("severity", "notifySeverity"):
            self.assertIn(name, self.defs["Event"]["required"])

    def test_schema_rejection_codes_cover_the_three_hard_refusals(self) -> None:
        codes = self.defs["RejectionReason"]["properties"]["code"]["enum"]
        for code in (
            "CAPABILITY_UNSATISFIED",
            "SUBJECT_KIND_UNSUPPORTED",
            "OPERATOR_NOT_IMPLEMENTED",
        ):
            self.assertIn(code, codes)
        self.assertEqual(
            self.defs["RejectionReason"]["properties"]["accepted"]["const"], False
        )

    def test_schema_observation_allows_an_entirely_empty_payload(self) -> None:
        required = self.defs["Observation"]["required"]
        for payload in ("detections", "classifications", "masks", "scalars"):
            self.assertNotIn(payload, required)
        self.assertIn("lostTrackIds", self.defs["Observation"]["properties"])

    def test_schema_conformance_vector_is_pinned_to_spec_v1(self) -> None:
        vector = self.defs["ConformanceVector"]
        self.assertEqual(vector["properties"]["specVersion"]["const"], "v1")
        for name in ("observations", "rules"):
            self.assertIn(name, vector["required"])
        for name in ("expectedEvents", "expectedRejections"):
            self.assertIn(name, vector["properties"])


if __name__ == "__main__":
    unittest.main()
