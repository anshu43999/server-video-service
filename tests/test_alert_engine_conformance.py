"""一致性金样向量的语料校验与执行入口（M11-T02）。

向量目录 `docs/alert-engine-conformance/` 是服务端 M11 与 App 侧 M15 的共同裁判：
App 侧**原样复制**这些 JSON 到测试资源后逐条执行（`M15-T05`）。因此这里做两件事：

1. **语料校验（现在就跑）**：向量本身合法、与 `docs/alert-engine.schema.json` 不矛盾、
   覆盖规格 §15.4 要求的全部场景。向量写错了不能等到引擎落地才发现。
2. **执行比对（引擎落地后自动开始跑）**：把 §15.1 的九条比对规则写成可执行代码，
   引擎只要提供 `app.alerts.engine.run_vector(vector)` 就会被这套向量逐条判定。

改这里的断言等于改规格：先改 docs/alert-engine-spec.md 与 Schema，再改向量，再改两侧实现（§18）。
只用标准库（`.venv` 没有 pytest / jsonschema）。
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VECTOR_DIR = ROOT / "docs/alert-engine-conformance"
SCHEMA = json.loads((ROOT / "docs/alert-engine.schema.json").read_text(encoding="utf-8"))
DEFS = SCHEMA["$defs"]

CAPABILITIES = set(DEFS["Capability"]["enum"])
SUBJECT_KINDS = set(DEFS["SubjectKind"]["enum"])
SEVERITIES = DEFS["Severity"]["enum"]
SEVERITY_ORDER = {name: i for i, name in enumerate(SEVERITIES)}
OPERATORS = DEFS["Operator"]["enum"]
RESERVED_OPERATORS = set(SCHEMA["x-notImplemented"]["operators"])
IMPLEMENTED_OPERATORS = [op for op in OPERATORS if op not in RESERVED_OPERATORS]
EVENT_STATES = set(DEFS["Event"]["properties"]["state"]["enum"])
AREA_SOURCES = set(DEFS["Event"]["properties"]["areaSource"]["oneOf"][0]["enum"])
REJECTION_CODES = set(DEFS["RejectionReason"]["properties"]["code"]["enum"])
THRESHOLD_FIELDS = set(DEFS["Thresholds"]["properties"])
VECTOR_FIELDS = set(DEFS["ConformanceVector"]["properties"])
VECTOR_REQUIRED = DEFS["ConformanceVector"]["required"]
SUBJECT_KEY_RE = re.compile(DEFS["SubjectKey"]["pattern"])
VECTOR_ID_RE = re.compile(DEFS["ConformanceVector"]["properties"]["vectorId"]["pattern"])

# 能力由谁提供：观测只声明 BOX / TRACK / MASK / SCALAR，
# POLYGON_ROI / LINE_ROI 由绑定的 ROI 形态提供（§6）。
ROI_SHAPE_CAPABILITY = {"POLYGON": "POLYGON_ROI", "LINE": "LINE_ROI"}


def _load_vectors():
    items = []
    for path in sorted(VECTOR_DIR.glob("*.json")):
        items.append((path, json.loads(path.read_text(encoding="utf-8"))))
    return items


VECTORS = _load_vectors()
BY_ID = {vector["vectorId"]: vector for _path, vector in VECTORS}


def _rejected_rule_ids(vector):
    """被显式拒绝的规则：故意写成非法，不参与「合法规则」的各项检查。"""
    return {r["ruleId"] for r in vector.get("expectedRejections", []) if "ruleId" in r}


def _rois(vector):
    return {roi["roiId"]: roi for roi in vector.get("rois", [])}


def _sort_key(event):
    return (
        event.get("confirmedAtUs", 0),
        event.get("subjectKey", ""),
        SEVERITY_ORDER.get(event.get("severity"), 0),
    )


class VectorCorpusTests(unittest.TestCase):
    """向量语料自身的合法性与覆盖度。引擎未落地时这一类也必须全绿。"""

    def test_corpus_is_not_empty(self) -> None:
        self.assertTrue(VECTORS, "docs/alert-engine-conformance/ 下没有向量")
        self.assertGreaterEqual(len(VECTORS), 25, "覆盖 §15.4 全部场景至少需要 25 条向量")

    def test_vector_id_matches_file_name(self) -> None:
        for path, vector in VECTORS:
            with self.subTest(path.name):
                self.assertEqual(vector["vectorId"], path.stem)
                self.assertRegex(vector["vectorId"], VECTOR_ID_RE)

    def test_vector_envelope_matches_the_frozen_schema(self) -> None:
        for path, vector in VECTORS:
            with self.subTest(path.name):
                for field in VECTOR_REQUIRED:
                    self.assertIn(field, vector)
                self.assertEqual(
                    set(vector) - VECTOR_FIELDS, set(), "ConformanceVector 不允许多余字段"
                )
                self.assertEqual(vector["specVersion"], "v1")
                self.assertTrue(vector["description"].strip(), "向量必须自带说明")
                self.assertGreaterEqual(len(vector["observations"]), 1)
                self.assertGreaterEqual(len(vector["rules"]), 1)

    def test_rules_are_structurally_valid(self) -> None:
        for path, vector in VECTORS:
            for rule in vector["rules"]:
                with self.subTest(path.name, rule=rule["ruleId"]):
                    self.assertIn(rule["subjectKind"], SUBJECT_KINDS)
                    self.assertIn(rule["operator"], OPERATORS)
                    self.assertLessEqual(set(rule["requires"]), CAPABILITIES)
                    self.assertLessEqual(set(rule["thresholds"]), THRESHOLD_FIELDS)
                    self.assertIsInstance(rule["ruleVersion"], int)
                    for band in rule.get("severityBands", []):
                        self.assertEqual(set(band), {"severity", "atLeast"})
                        self.assertIn(band["severity"], SEVERITIES)
                    bands = rule.get("severityBands", [])
                    self.assertEqual(
                        bands,
                        sorted(bands, key=lambda b: (b["atLeast"], SEVERITY_ORDER[b["severity"]])),
                        "severityBands 必须按 atLeast 升序，两侧才能取同一档",
                    )
                    for band_a, band_b in zip(bands, bands[1:]):
                        self.assertLess(
                            SEVERITY_ORDER[band_a["severity"]], SEVERITY_ORDER[band_b["severity"]]
                        )
                    if "escalation" in rule:
                        self.assertEqual(set(rule["escalation"]), {"escalateAfterMs", "toSeverity"})
                        self.assertIn(rule["escalation"]["toSeverity"], SEVERITIES)

    def test_reserved_operators_only_appear_as_explicit_rejections(self) -> None:
        for path, vector in VECTORS:
            rejected = {
                r["ruleId"]
                for r in vector.get("expectedRejections", [])
                if r.get("code") == "OPERATOR_NOT_IMPLEMENTED"
            }
            for rule in vector["rules"]:
                if rule["operator"] in RESERVED_OPERATORS:
                    with self.subTest(path.name, rule=rule["ruleId"]):
                        self.assertIn(
                            rule["ruleId"],
                            rejected,
                            "预留算子只能出现在等待 OPERATOR_NOT_IMPLEMENTED 的规则里",
                        )

    def test_observations_advance_time_monotonically_per_source(self) -> None:
        for path, vector in VECTORS:
            last = {}
            for observation in vector["observations"]:
                source = observation["sourceId"]
                with self.subTest(path.name, source=source, seq=observation["frameSeq"]):
                    captured = observation["capturedAtUs"]
                    self.assertIsInstance(captured, int, "capturedAtUs 是微秒整数")
                    self.assertGreaterEqual(
                        captured, last.get(source, 0), "同源 capturedAtUs 必须单调不减（§11.3）"
                    )
                    self.assertLessEqual(set(observation["provides"]), CAPABILITIES)
                    self.assertNotIn(
                        "POLYGON_ROI", observation["provides"], "ROI 能力由 ROI 提供，不由观测声明"
                    )
                    self.assertNotIn("LINE_ROI", observation["provides"])
                last[source] = captured

    def test_payloads_stay_in_normalized_coordinates(self) -> None:
        def unit(value, label):
            self.assertGreaterEqual(value, 0.0, label)
            self.assertLessEqual(value, 1.0, label)

        for path, vector in VECTORS:
            with self.subTest(path.name):
                for observation in vector["observations"]:
                    for detection in observation.get("detections", []):
                        unit(detection["confidence"], "confidence")
                        if "box" in detection:
                            b = detection["box"]
                            unit(b["x"], "box.x")
                            unit(b["y"], "box.y")
                            unit(b["x"] + b["w"], "box 右边界")
                            unit(b["y"] + b["h"], "box 下边界")
                    for classification in observation.get("classifications", []):
                        unit(classification["confidence"], "classification.confidence")
                    for mask in observation.get("masks", []):
                        unit(mask["areaRatio"], "mask.areaRatio")
                for roi in vector.get("rois", []):
                    if roi["shape"] == "RECT":
                        r = roi["rect"]
                        unit(r["x"] + r["w"], "rect 右边界")
                        unit(r["y"] + r["h"], "rect 下边界")
                    else:
                        for point in roi["points"]:
                            unit(point[0], "point.x")
                            unit(point[1], "point.y")

    def test_roi_references_resolve_and_carry_the_right_geometry(self) -> None:
        for path, vector in VECTORS:
            rois = _rois(vector)
            self.assertEqual(len(rois), len(vector.get("rois", [])), "roiId 重复")
            for rule in vector["rules"]:
                if "roiId" not in rule:
                    continue
                with self.subTest(path.name, rule=rule["ruleId"]):
                    self.assertIn(rule["roiId"], rois, "规则引用了不存在的 ROI")
                    roi = rois[rule["roiId"]]
                    if roi["shape"] == "POLYGON":
                        self.assertGreaterEqual(len(roi["points"]), 3)
                    elif roi["shape"] == "LINE":
                        self.assertEqual(len(roi["points"]), 2)
                        self.assertIn(
                            roi["positiveDirection"], {"LEFT_TO_RIGHT", "RIGHT_TO_LEFT"}
                        )

    def test_accepted_rules_have_every_capability_they_require(self) -> None:
        """§6 第 3 步：requires ⊆ 观测能力 ∪ ROI 能力，否则必须写成显式拒绝。"""
        for path, vector in VECTORS:
            rejected = _rejected_rule_ids(vector)
            rois = _rois(vector)
            provided = set()
            for observation in vector["observations"]:
                provided |= set(observation["provides"])
            for rule in vector["rules"]:
                if rule["ruleId"] in rejected:
                    continue
                roi_caps = set()
                if "roiId" in rule and rule["roiId"] in rois:
                    shape = rois[rule["roiId"]]["shape"]
                    if shape in ROI_SHAPE_CAPABILITY:
                        roi_caps.add(ROI_SHAPE_CAPABILITY[shape])
                with self.subTest(path.name, rule=rule["ruleId"]):
                    self.assertLessEqual(
                        set(rule["requires"]),
                        provided | roi_caps,
                        "能力不满足的规则必须列进 expectedRejections，而不是静默不触发（C-3）",
                    )

    def test_expected_events_use_the_frozen_sort_order(self) -> None:
        for path, vector in VECTORS:
            events = vector.get("expectedEvents")
            if not events:
                continue
            with self.subTest(path.name):
                self.assertEqual(
                    events,
                    sorted(events, key=_sort_key),
                    "§15.1 第 5 条：按 confirmedAtUs、subjectKey、severity 升序",
                )

    def test_expected_events_reference_declared_rules_and_sources(self) -> None:
        for path, vector in VECTORS:
            rules = {rule["ruleId"]: rule for rule in vector["rules"]}
            sources = {observation["sourceId"] for observation in vector["observations"]}
            rejected = _rejected_rule_ids(vector)
            for event in vector.get("expectedEvents", []):
                with self.subTest(path.name, rule=event.get("ruleId")):
                    self.assertIn(event["ruleId"], rules)
                    self.assertNotIn(event["ruleId"], rejected, "被拒绝的规则不产生事件")
                    self.assertIn(event["sourceId"], sources)
                    self.assertRegex(event["subjectKey"], SUBJECT_KEY_RE)
                    kind = event["subjectKey"].split(":", 1)[0]
                    self.assertEqual(kind, rules[event["ruleId"]]["subjectKind"])
                    self.assertEqual(event["operator"], rules[event["ruleId"]]["operator"])
                    self.assertIn(event["severity"], SEVERITIES)
                    if "state" in event:
                        self.assertIn(event["state"], EVENT_STATES)
                        self.assertNotEqual(
                            event["state"], "CANDIDATE", "§15.1 第 6 条：候选不进 expectedEvents"
                        )
                    if event.get("areaSource") is not None:
                        self.assertIn(event["areaSource"], AREA_SOURCES)
                    if "notifySeverity" in event:
                        self.assertGreaterEqual(
                            SEVERITY_ORDER[event["notifySeverity"]],
                            SEVERITY_ORDER[event["severity"]],
                            "提级只会抬高通知级别，不会压低",
                        )
                    if event.get("escalatedAtUs") is None and "notifySeverity" in event:
                        self.assertEqual(event["notifySeverity"], event["severity"])
                    if "endedAtUs" in event and event["endedAtUs"] is not None:
                        self.assertGreaterEqual(event["endedAtUs"], event["confirmedAtUs"])
                    if "startedAtUs" in event:
                        self.assertLessEqual(event["startedAtUs"], event["confirmedAtUs"])

    def test_expected_rejections_use_the_frozen_codes(self) -> None:
        for path, vector in VECTORS:
            rules = {rule["ruleId"] for rule in vector["rules"]}
            for rejection in vector.get("expectedRejections", []):
                with self.subTest(path.name, rule=rejection.get("ruleId")):
                    self.assertIs(rejection["accepted"], False)
                    self.assertIn(rejection["code"], REJECTION_CODES)
                    if "ruleId" in rejection:
                        self.assertIn(rejection["ruleId"], rules)
                    if rejection["code"] == "CAPABILITY_UNSATISFIED":
                        self.assertTrue(rejection.get("missing"), "能力不足必须给出 missing 集合")
                        self.assertLessEqual(set(rejection["missing"]), CAPABILITIES)

    # --- §15.4 覆盖度 -------------------------------------------------------

    def test_every_implemented_operator_has_at_least_one_vector(self) -> None:
        covered = set()
        for _path, vector in VECTORS:
            rejected = _rejected_rule_ids(vector)
            for rule in vector["rules"]:
                if rule["ruleId"] not in rejected:
                    covered.add(rule["operator"])
        self.assertEqual(
            set(IMPLEMENTED_OPERATORS) - covered, set(), "每个已实现算子至少要有一条向量"
        )

    def test_severity_bands_are_probed_on_both_sides_of_every_boundary(self) -> None:
        vector = BY_ID["severity-band-boundaries"]
        bands = vector["rules"][0]["severityBands"]
        measured = [(e["measuredValue"], e["severity"]) for e in vector["expectedEvents"]]
        self.assertGreaterEqual(len(bands), 3, "三档都要有")
        for band in bands:
            at_least = band["atLeast"]
            self.assertTrue(
                any(abs(value - at_least) < 1e-9 for value, _ in measured),
                "缺少 atLeast 上的一帧：%s" % at_least,
            )
            self.assertTrue(
                any(value < at_least for value, _ in measured),
                "缺少 atLeast 下方的一帧：%s" % at_least,
            )
        self.assertEqual({severity for _, severity in measured}, set(SEVERITIES))

    def test_unattended_escalation_is_covered(self) -> None:
        escalated = [
            event
            for _path, vector in VECTORS
            for event in vector.get("expectedEvents", [])
            if event.get("escalatedAtUs")
        ]
        self.assertTrue(escalated, "缺少未处置提级向量")
        for event in escalated:
            self.assertNotEqual(
                event["notifySeverity"], event["severity"], "提级只动通知级别，事实级别不变（§10.2）"
            )
            self.assertGreaterEqual(event["escalatedAtUs"], event["confirmedAtUs"])

    def test_cooldown_suppression_and_severity_release_are_covered(self) -> None:
        suppressed = [
            event
            for _path, vector in VECTORS
            for event in vector.get("expectedEvents", [])
            if event.get("suppressedCount", 0) >= 2
        ]
        self.assertTrue(suppressed, "缺少 suppressedCount 累加的向量")
        released = False
        for _path, vector in VECTORS:
            by_subject = {}
            for event in vector.get("expectedEvents", []):
                key = (event["ruleId"], event["sourceId"], event["subjectKey"])
                by_subject.setdefault(key, set()).add(event["severity"])
            if any(len(levels) >= 2 for levels in by_subject.values()):
                released = True
        self.assertTrue(released, "缺少「同一主体级别升高另开实例并放行」的向量")

    def test_all_three_rejection_codes_are_covered(self) -> None:
        codes = {
            rejection["code"]
            for _path, vector in VECTORS
            for rejection in vector.get("expectedRejections", [])
        }
        for code in (
            "CAPABILITY_UNSATISFIED",
            "SUBJECT_KIND_UNSUPPORTED",
            "OPERATOR_NOT_IMPLEMENTED",
            "ROI_REQUIRED",
            "ROI_GEOMETRY_INVALID",
            "TARGET_LABELS_REQUIRED",
        ):
            self.assertIn(code, codes)

    def test_absence_has_a_paired_control_vector(self) -> None:
        fires = BY_ID["op-absence-empty-envelope"]
        silent = BY_ID["absence-stream-loss-silent"]
        self.assertTrue(fires["expectedEvents"], "空信封必须能推进 ABSENCE 并告警")
        self.assertEqual(silent["expectedEvents"], [], "断流不得伪造 ABSENCE（§11.4）")
        self.assertEqual(
            fires["rules"][0]["thresholds"], silent["rules"][0]["thresholds"],
            "一对对照向量必须用同一套阈值，否则证明不了差异来自断流",
        )

    def test_rate_window_capacity_bound_is_covered(self) -> None:
        vector = BY_ID["rate-window-capacity-bound"]
        self.assertGreaterEqual(len(vector["observations"]), 20, "容量上限要靠足够多的观测压出来")
        self.assertIn("rateWindowMs", vector["rules"][0]["thresholds"])
        self.assertEqual(len(vector["expectedEvents"]), 1, "窗口正确过期时只会有一个事件")

    def test_track_loss_ends_the_event(self) -> None:
        vector = BY_ID["track-loss-ends-event"]
        self.assertTrue(
            any("lostTrackIds" in o for o in vector["observations"]), "缺少跟踪丢失输入"
        )
        self.assertEqual(vector["expectedEvents"][0]["state"], "ENDED")
        self.assertIsNotNone(vector["expectedEvents"][0]["endedAtUs"])

    def test_candidate_break_takes_a_new_started_at(self) -> None:
        vector = BY_ID["op-dwell-accumulates-and-resets"]
        first = min(o["capturedAtUs"] for o in vector["observations"])
        event = vector["expectedEvents"][0]
        self.assertTrue(
            any(not o.get("detections") for o in vector["observations"]), "缺少中断候选的空信封"
        )
        self.assertGreater(
            event["startedAtUs"], first, "§11.1：中断后重新成立要取新的 startedAtUs"
        )

    def test_three_geometry_edge_cases_are_covered(self) -> None:
        for vector_id in (
            "geometry-polygon-boundary-point",
            "geometry-edge-touch-not-intersecting",
            "geometry-center-point-inside",
            "geometry-polygon-concave-notch",
        ):
            self.assertIn(vector_id, BY_ID)

    def test_m07_baseline_group_exists(self) -> None:
        baselines = [vid for vid in BY_ID if vid.startswith("baseline-m07-")]
        self.assertGreaterEqual(len(baselines), 4, "M07 基线向量至少一组")
        for vector_id in baselines:
            self.assertTrue(BY_ID[vector_id]["expectedEvents"] is not None)

    def test_empty_expected_events_is_written_explicitly(self) -> None:
        """§15.1 第 7 条：`expectedEvents: []` 是强断言，不能靠省略字段表达。"""
        for vector_id in ("absence-stream-loss-silent", "reject-roi-geometry-degenerate"):
            vector = BY_ID[vector_id]
            self.assertIn("expectedEvents", vector)
            self.assertEqual(vector["expectedEvents"], [])


# ============================================================== 执行器比对（§15.1）
# 引擎落地后（M11-T05）只需提供 app/alerts/engine.py 的 run_vector(vector)：
#     def run_vector(vector: dict) -> dict:
#         return {"events": [...], "rejections": [...]}
# 事件字段名与 Schema 的 Event 一致，拒绝字段名与 RejectionReason 一致。
# 下面这套比对规则本身是冻结项，App 侧（M15-T05）必须实现同样的比对语义。
try:  # pragma: no cover - 引擎尚未落地
    from app.alerts.engine import run_vector  # type: ignore
except Exception:  # noqa: BLE001 - 任何导入失败都当作「引擎还没有」
    run_vector = None

ENGINE_AVAILABLE = run_vector is not None
EXACT_FIELDS = {
    "startedAtUs",
    "confirmedAtUs",
    "endedAtUs",
    "escalatedAtUs",
    "suppressedCount",
    "ruleVersion",
}


def _rejection_key(rejection):
    return rejection.get("ruleId", "")


class VectorExecutionTests(unittest.TestCase):
    """把向量喂给真实引擎并逐条比对。引擎未落地时整类跳过（跳过信息里写着谁来接）。"""

    def _assert_field(self, name, expected, actual, context):
        message = "%s.%s 期望 %r，实际 %r" % (context, name, expected, actual)
        if expected is None or actual is None or isinstance(expected, (str, bool)):
            self.assertEqual(actual, expected, message)
        elif name in EXACT_FIELDS:
            self.assertEqual(actual, expected, message)  # 时间戳与计数必须精确相等
        else:
            self.assertAlmostEqual(actual, expected, delta=1e-6, msg=message)

    def _compare_events(self, vector_id, expected_events, actual_events):
        expected_sorted = sorted(expected_events, key=_sort_key)
        actual_sorted = sorted(actual_events, key=_sort_key)
        self.assertEqual(
            len(actual_sorted),
            len(expected_sorted),
            "%s 事件实例数量不符：期望 %d，实际 %d"
            % (vector_id, len(expected_sorted), len(actual_sorted)),
        )
        for index, (expected, actual) in enumerate(zip(expected_sorted, actual_sorted)):
            context = "%s#%d" % (vector_id, index)
            for name, value in expected.items():
                self.assertIn(name, actual, "%s 缺少字段 %s" % (context, name))
                self._assert_field(name, value, actual[name], context)

    def _compare_rejections(self, vector_id, expected_rejections, actual_rejections):
        expected_sorted = sorted(expected_rejections, key=_rejection_key)
        actual_sorted = sorted(actual_rejections, key=_rejection_key)
        self.assertEqual(
            len(actual_sorted),
            len(expected_sorted),
            "%s 拒绝数量不符：期望 %d，实际 %d"
            % (vector_id, len(expected_sorted), len(actual_sorted)),
        )
        for expected, actual in zip(expected_sorted, actual_sorted):
            self.assertIs(actual["accepted"], False)
            self.assertEqual(actual["code"], expected["code"], vector_id)
            if "ruleId" in expected:
                self.assertEqual(actual["ruleId"], expected["ruleId"], vector_id)
            if "missing" in expected:
                self.assertEqual(
                    set(actual.get("missing", [])), set(expected["missing"]), vector_id
                )  # 集合比较，忽略顺序（§15.1 第 8 条）

    @unittest.skipUnless(
        ENGINE_AVAILABLE,
        "告警引擎尚未落地：M11-T05 提供 app/alerts/engine.py::run_vector(vector) 后本类自动开始执行",
    )
    def test_engine_matches_every_vector(self) -> None:
        for path, vector in VECTORS:
            with self.subTest(path.name):
                result = run_vector(vector)
                self._compare_events(
                    vector["vectorId"],
                    vector.get("expectedEvents", []),
                    result.get("events", []),
                )
                self._compare_rejections(
                    vector["vectorId"],
                    vector.get("expectedRejections", []),
                    result.get("rejections", []),
                )


if __name__ == "__main__":
    unittest.main()
