import json
import re
import unittest
from pathlib import Path

from app.alerts.geometry import (
    EPS,
    Box,
    CrossDirection,
    Roi,
    RoiGeometryError,
    RoiRelation,
    RoiShape,
    RoiShapeMismatchError,
    SHAPE_CAPABILITY,
    box_in_roi,
    intersects,
    is_positive_crossing,
    overlap_area,
    point_in_polygon,
    point_in_roi,
    relation_holds,
    roi_area,
    side_sign,
    signed_side,
    step_side,
    union_overlap_area,
)

ROOT = Path(__file__).resolve().parents[1]
VECTOR_DIR = ROOT / "docs/alert-engine-conformance"
SQUARE = {"roiId": "square", "shape": "POLYGON", "points": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]}
NOTCH = {
    "roiId": "notch",
    "shape": "POLYGON",
    "points": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.5, 0.5], [0.1, 0.9]],
}
YARD = {"roiId": "yard", "shape": "RECT", "rect": {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5}}
GATE = {
    "roiId": "gate",
    "shape": "LINE",
    "points": [[0.5, 0.1], [0.5, 0.9]],
    "positiveDirection": "LEFT_TO_RIGHT",
}


def load_vector(vector_id: str) -> dict:
    return json.loads((VECTOR_DIR / f"{vector_id}.json").read_text(encoding="utf-8"))


class RoiConstructionTests(unittest.TestCase):
    """§5.1：退化几何必须在构造时拒绝，不允许求值期静默返回「不相交」。"""

    def assert_rejected(self, payload: dict, needle: str) -> None:
        with self.assertRaises(RoiGeometryError) as caught:
            Roi.from_mapping(payload)
        self.assertEqual(caught.exception.code, "ROI_GEOMETRY_INVALID")
        self.assertIn(needle, caught.exception.reason)

    def test_valid_shapes_are_accepted(self) -> None:
        for payload, shape in ((YARD, RoiShape.RECT), (SQUARE, RoiShape.POLYGON), (GATE, RoiShape.LINE)):
            roi = Roi.from_mapping(payload)
            self.assertIs(roi.shape, shape)

    def test_rect_rejects_degenerate_and_out_of_frame(self) -> None:
        self.assert_rejected({"roiId": "flat", "shape": "RECT", "rect": {"x": 0.1, "y": 0.1, "w": 0.0, "h": 0.4}}, "degenerate rect")
        self.assert_rejected({"roiId": "thin", "shape": "RECT", "rect": {"x": 0.1, "y": 0.1, "w": 0.4, "h": 0.0}}, "degenerate rect")
        self.assert_rejected({"roiId": "over", "shape": "RECT", "rect": {"x": 0.8, "y": 0.1, "w": 0.4, "h": 0.4}}, "frame boundary")
        self.assert_rejected({"roiId": "mixed", "shape": "RECT", "rect": {"x": 0.1, "y": 0.1, "w": 0.4, "h": 0.4}, "points": [[0.1, 0.1]]}, "not points")
        self.assert_rejected({"roiId": "empty", "shape": "RECT"}, "requires rect")

    def test_polygon_rejects_too_few_points_and_duplicates(self) -> None:
        self.assert_rejected({"roiId": "two", "shape": "POLYGON", "points": [[0.1, 0.1], [0.5, 0.5]]}, "at least 3")
        # 相邻重复点包含「末点与首点重合」这一种，闭合边同样是一条边。
        self.assert_rejected(
            {"roiId": "dup", "shape": "POLYGON", "points": [[0.1, 0.1], [0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]},
            "duplicate adjacent",
        )
        self.assert_rejected(
            {"roiId": "wrap", "shape": "POLYGON", "points": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.1]]},
            "duplicate adjacent",
        )

    def test_polygon_rejects_zero_area(self) -> None:
        self.assert_rejected(
            {"roiId": "line-like", "shape": "POLYGON", "points": [[0.1, 0.1], [0.5, 0.1], [0.9, 0.1]]},
            "area is zero",
        )

    def test_polygon_rejects_self_intersection(self) -> None:
        # 顶点落在非相邻边上：面积非零（0.32），只能靠自相交检查挡住。
        self.assert_rejected(
            {
                "roiId": "vertex-on-edge",
                "shape": "POLYGON",
                "points": [[0.1, 0.1], [0.5, 0.1], [0.9, 0.1], [0.9, 0.9], [0.5, 0.1], [0.1, 0.9]],
            },
            "self-intersect",
        )
        # 相邻边共线折回（尖刺）：面积非零（0.16），共线重叠必须拒绝。
        self.assert_rejected(
            {"roiId": "spike", "shape": "POLYGON", "points": [[0.1, 0.1], [0.9, 0.1], [0.5, 0.1], [0.5, 0.9]]},
            "self-intersect",
        )

    def test_polygon_keeps_a_redundant_collinear_vertex(self) -> None:
        # 一条直边上的多余顶点不改变区域，不属于 §5.1 的四类退化输入。
        roi = Roi.from_mapping(
            {
                "roiId": "redundant",
                "shape": "POLYGON",
                "points": [[0.1, 0.1], [0.5, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
            }
        )
        self.assertAlmostEqual(roi_area(roi), 0.64, places=9)

    def test_line_rejects_wrong_point_count_and_zero_length(self) -> None:
        self.assert_rejected({"roiId": "one", "shape": "LINE", "points": [[0.1, 0.1]], "positiveDirection": "LEFT_TO_RIGHT"}, "exactly 2")
        self.assert_rejected(
            {"roiId": "three", "shape": "LINE", "points": [[0.1, 0.1], [0.5, 0.5], [0.9, 0.9]], "positiveDirection": "LEFT_TO_RIGHT"},
            "exactly 2",
        )
        self.assert_rejected(
            {"roiId": "dot", "shape": "LINE", "points": [[0.5, 0.5], [0.5, 0.5]], "positiveDirection": "LEFT_TO_RIGHT"},
            "zero-length",
        )
        self.assert_rejected({"roiId": "nodir", "shape": "LINE", "points": [[0.1, 0.1], [0.9, 0.9]]}, "positiveDirection")

    def test_points_out_of_normalized_range_are_rejected(self) -> None:
        self.assert_rejected(
            {"roiId": "far", "shape": "POLYGON", "points": [[0.1, 0.1], [1.4, 0.1], [0.9, 0.9]]},
            "out of the normalized range",
        )

    def test_shape_string_is_coerced_before_validation(self) -> None:
        # 直接构造时传字符串不能被当成另一种形态校验（StrEnum 相等但不同一）。
        roi = Roi(roi_id="square", shape="POLYGON", points=tuple(tuple(p) for p in SQUARE["points"]))
        self.assertIs(roi.shape, RoiShape.POLYGON)
        with self.assertRaises(ValueError):
            Roi(roi_id="bad", shape="CIRCLE", points=((0.1, 0.1), (0.2, 0.2), (0.3, 0.4)))

    def test_every_degenerate_roi_in_the_golden_vector_is_rejected(self) -> None:
        vector = load_vector("reject-roi-geometry-degenerate")
        self.assertEqual(len(vector["rois"]), 3)
        for payload in vector["rois"]:
            with self.subTest(roi=payload["roiId"]):
                with self.assertRaises(RoiGeometryError) as caught:
                    Roi.from_mapping(payload)
                self.assertEqual(caught.exception.code, "ROI_GEOMETRY_INVALID")
        self.assertEqual(
            {rejection["code"] for rejection in vector["expectedRejections"]}, {"ROI_GEOMETRY_INVALID"}
        )


class ContainmentTests(unittest.TestCase):
    """§5.2：奇偶射线法，边界算内；框归属取框中心。"""

    def setUp(self) -> None:
        self.square = Roi.from_mapping(SQUARE)
        self.notch = Roi.from_mapping(NOTCH)
        self.yard = Roi.from_mapping(YARD)
        self.gate = Roi.from_mapping(GATE)

    def test_interior_point_is_inside(self) -> None:
        self.assertTrue(point_in_polygon((0.5, 0.5), self.square.outline))
        self.assertTrue(point_in_roi(self.square, (0.5, 0.5)))
        self.assertTrue(point_in_roi(self.yard, (0.25, 0.25)))

    def test_boundary_and_vertex_count_as_inside(self) -> None:
        for point in ((0.2, 0.5), (0.8, 0.5), (0.5, 0.2), (0.5, 0.8)):
            with self.subTest(point=point):
                self.assertTrue(point_in_roi(self.square, point))
        for vertex in SQUARE["points"]:
            with self.subTest(vertex=tuple(vertex)):
                self.assertTrue(point_in_roi(self.square, (vertex[0], vertex[1])))

    def test_rect_boundary_is_inside_and_one_epsilon_outside_is_not(self) -> None:
        self.assertTrue(point_in_roi(self.yard, (0.5, 0.25)))
        self.assertFalse(point_in_roi(self.yard, (0.5 + 1e-6, 0.25)))

    def test_outside_point_is_not_inside(self) -> None:
        for point in ((0.1, 0.1), (0.9, 0.5), (0.5, 0.9)):
            with self.subTest(point=point):
                self.assertFalse(point_in_roi(self.square, point))

    def test_concave_notch_excludes_the_wedge(self) -> None:
        # 凹多边形的缺口内部必须判定为外部，奇偶法在缺口上穿越偶数次。
        self.assertFalse(point_in_roi(self.notch, (0.5, 0.8)))
        self.assertTrue(point_in_roi(self.notch, (0.5, 0.3)))
        self.assertTrue(point_in_roi(self.notch, (0.2, 0.8)))
        self.assertTrue(point_in_roi(self.notch, (0.8, 0.8)))
        # 缺口顶点本身是边界，边界算内。
        self.assertTrue(point_in_roi(self.notch, (0.5, 0.5)))

    def test_box_membership_uses_the_center_not_the_whole_box(self) -> None:
        # §17 第 11 条：M07 用整框包含，规格改为框中心。
        mostly_out = Box(x=0.45, y=0.45, w=0.3, h=0.3)
        self.assertTrue(box_in_roi(self.square, mostly_out))
        center_out = Box(x=0.75, y=0.1, w=0.3, h=0.3)
        self.assertAlmostEqual(center_out.center[0], 0.9, places=9)
        self.assertFalse(box_in_roi(self.square, center_out))
        self.assertGreater(overlap_area(self.square, center_out), 0.0)

    def test_line_roi_has_no_interior(self) -> None:
        self.assertFalse(self.gate.has_interior)
        for call in (
            lambda: point_in_roi(self.gate, (0.5, 0.5)),
            lambda: box_in_roi(self.gate, Box(x=0.4, y=0.4, w=0.2, h=0.2)),
            lambda: overlap_area(self.gate, Box(x=0.4, y=0.4, w=0.2, h=0.2)),
            lambda: roi_area(self.gate),
            lambda: self.gate.outline,
        ):
            with self.subTest(call=call):
                with self.assertRaises(RoiShapeMismatchError) as caught:
                    call()
                self.assertEqual(caught.exception.code, "ROI_GEOMETRY_INVALID")

    def test_interior_shapes_reject_crossing_queries(self) -> None:
        for call in (
            lambda: signed_side(self.square, (0.5, 0.5)),
            lambda: side_sign(self.square, (0.5, 0.5)),
            lambda: step_side(self.square, 0, (0.5, 0.5)),
            lambda: is_positive_crossing(self.square, CrossDirection.LEFT_TO_RIGHT),
        ):
            with self.subTest(call=call):
                with self.assertRaises(RoiShapeMismatchError):
                    call()

    def test_relation_truth_table(self) -> None:
        # (relation, was_inside, is_inside) -> holds；was_inside=None 表示首帧无前一帧。
        cases = {
            (RoiRelation.INSIDE, None, True): True,
            (RoiRelation.INSIDE, None, False): False,
            (RoiRelation.INSIDE, False, True): True,
            (RoiRelation.INSIDE, True, True): True,
            (RoiRelation.INSIDE, True, False): False,
            (RoiRelation.ENTER, None, True): False,
            (RoiRelation.ENTER, False, True): True,
            (RoiRelation.ENTER, True, True): False,
            (RoiRelation.ENTER, False, False): False,
            (RoiRelation.EXIT, None, False): False,
            (RoiRelation.EXIT, True, False): True,
            (RoiRelation.EXIT, False, False): False,
            (RoiRelation.EXIT, True, True): False,
        }
        for (relation, was_inside, is_inside), expected in cases.items():
            with self.subTest(relation=relation, was=was_inside, now=is_inside):
                self.assertEqual(relation_holds(relation, was_inside, is_inside), expected)

    def test_inside_also_holds_on_the_enter_frame(self) -> None:
        self.assertTrue(relation_holds(RoiRelation.ENTER, False, True))
        self.assertTrue(relation_holds(RoiRelation.INSIDE, False, True))


class AreaTests(unittest.TestCase):
    """§5.2 相交判定与 §8.1 面积占比分子：交叠面积 > 0 才算相交，重叠只算一次。"""

    def setUp(self) -> None:
        self.yard = Roi.from_mapping(YARD)
        self.square = Roi.from_mapping(SQUARE)
        self.notch = Roi.from_mapping(NOTCH)

    def test_roi_area_matches_the_shoelace_area(self) -> None:
        self.assertAlmostEqual(roi_area(self.yard), 0.25, places=9)
        self.assertAlmostEqual(roi_area(self.square), 0.36, places=9)
        self.assertAlmostEqual(roi_area(self.notch), 0.48, places=9)

    def test_edge_touch_is_not_intersecting(self) -> None:
        touching = Box(x=0.5, y=0.1, w=0.2, h=0.2)
        self.assertAlmostEqual(overlap_area(self.yard, touching), 0.0, places=9)
        self.assertFalse(intersects(self.yard, touching))

    def test_partial_overlap_counts_only_the_overlapping_part(self) -> None:
        straddling = Box(x=0.4, y=0.3, w=0.2, h=0.2)
        self.assertAlmostEqual(overlap_area(self.yard, straddling), 0.02, places=9)
        self.assertTrue(intersects(self.yard, straddling))

    def test_golden_vector_area_ratio_is_reproduced(self) -> None:
        vector = load_vector("geometry-edge-touch-not-intersecting")
        roi = Roi.from_mapping(vector["rois"][0])
        boxes = [Box.from_mapping(d["box"]) for d in vector["observations"][0]["detections"]]
        numerator = union_overlap_area(roi, boxes)
        ratio = numerator / roi_area(roi)
        self.assertAlmostEqual(numerator, 0.06, places=9)
        self.assertAlmostEqual(ratio, vector["expectedEvents"][0]["measuredValue"], places=9)
        # 向量描述里的 0.48 是错误实现的值：把三个框都按整框面积累加。
        self.assertAlmostEqual(sum(box.area for box in boxes) / roi_area(roi), 0.48, places=9)
        # 正确实现下贴边那一框连「相交」都不成立，另外两框只贡献交叠部分。
        self.assertEqual([intersects(roi, box) for box in boxes], [True, False, True])

    def test_union_counts_overlapping_boxes_once(self) -> None:
        boxes = [Box(x=0.2, y=0.2, w=0.3, h=0.3), Box(x=0.4, y=0.4, w=0.3, h=0.3)]
        self.assertAlmostEqual(union_overlap_area(self.square, boxes), 0.17, places=9)
        self.assertAlmostEqual(sum(b.area for b in boxes), 0.18, places=9)

    def test_union_of_a_single_box_equals_its_overlap(self) -> None:
        box = Box(x=0.1, y=0.1, w=0.2, h=0.2)
        self.assertAlmostEqual(union_overlap_area(self.yard, [box]), overlap_area(self.yard, box), places=9)
        self.assertAlmostEqual(union_overlap_area(self.yard, []), 0.0, places=9)

    def test_concave_roi_overlap_follows_the_outline_not_the_bounding_box(self) -> None:
        band = Box(x=0.0, y=0.4, w=1.0, h=0.2)
        self.assertAlmostEqual(overlap_area(self.notch, band), 0.15, places=9)
        in_the_wedge = Box(x=0.45, y=0.7, w=0.1, h=0.1)
        self.assertAlmostEqual(overlap_area(self.notch, in_the_wedge), 0.0, places=9)
        self.assertFalse(intersects(self.notch, in_the_wedge))

    def test_full_frame_box_covers_the_whole_roi(self) -> None:
        frame = Box(x=0.0, y=0.0, w=1.0, h=1.0)
        self.assertAlmostEqual(overlap_area(self.notch, frame), roi_area(self.notch), places=9)


class LineCrossingTests(unittest.TestCase):
    """§5.2 跨线方向：side(p) = (p.x−A.x)·d.y − (p.y−A.y)·d.x，负→正记为 LEFT_TO_RIGHT。"""

    def setUp(self) -> None:
        self.gate = Roi.from_mapping(GATE)

    def test_sign_follows_the_spec_formula(self) -> None:
        # gate 由 (0.5,0.1) 指向 (0.5,0.9)：d = (0, 0.8)，左侧（x<0.5）为负。
        self.assertLess(signed_side(self.gate, (0.3, 0.5)), 0.0)
        self.assertGreater(signed_side(self.gate, (0.7, 0.5)), 0.0)
        self.assertEqual(side_sign(self.gate, (0.3, 0.5)), -1)
        self.assertEqual(side_sign(self.gate, (0.7, 0.5)), 1)

    def test_on_the_line_is_sign_zero(self) -> None:
        self.assertEqual(side_sign(self.gate, (0.5, 0.5)), 0)
        self.assertEqual(side_sign(self.gate, (0.5 + EPS / 2, 0.5)), 0)
        # 无限长直线语义：延长线上的点同样判 0，不检查是否落在 A、B 之间。
        self.assertEqual(side_sign(self.gate, (0.5, 0.99)), 0)

    def test_first_non_zero_sign_only_records(self) -> None:
        sign, direction = step_side(self.gate, 0, (0.3, 0.5))
        self.assertEqual((sign, direction), (-1, None))

    def test_staying_on_one_side_does_not_cross(self) -> None:
        self.assertEqual(step_side(self.gate, -1, (0.45, 0.5)), (-1, None))
        self.assertEqual(step_side(self.gate, 1, (0.7, 0.5)), (1, None))

    def test_touching_the_line_neither_crosses_nor_forgets_the_last_side(self) -> None:
        sign, direction = step_side(self.gate, -1, (0.5, 0.5))
        self.assertEqual((sign, direction), (-1, None))
        # 从线上离开回到原侧仍不算跨越。
        self.assertEqual(step_side(self.gate, sign, (0.3, 0.5)), (-1, None))

    def test_both_directions_are_labelled_per_spec(self) -> None:
        self.assertEqual(step_side(self.gate, -1, (0.7, 0.5)), (1, CrossDirection.LEFT_TO_RIGHT))
        self.assertEqual(step_side(self.gate, 1, (0.3, 0.5)), (-1, CrossDirection.RIGHT_TO_LEFT))

    def test_positive_direction_gate(self) -> None:
        self.assertTrue(is_positive_crossing(self.gate, CrossDirection.LEFT_TO_RIGHT))
        self.assertFalse(is_positive_crossing(self.gate, CrossDirection.RIGHT_TO_LEFT))
        self.assertFalse(is_positive_crossing(self.gate, None))
        reversed_gate = Roi.from_mapping({**GATE, "roiId": "gate-r", "positiveDirection": "RIGHT_TO_LEFT"})
        self.assertFalse(is_positive_crossing(reversed_gate, CrossDirection.LEFT_TO_RIGHT))
        self.assertTrue(is_positive_crossing(reversed_gate, CrossDirection.RIGHT_TO_LEFT))

    def test_golden_vector_walk_hits_the_positive_direction_once(self) -> None:
        vector = load_vector("op-line-cross-positive-direction")
        roi = Roi.from_mapping(vector["rois"][0])
        sign = 0
        hits = []
        for observation in vector["observations"]:
            box = Box.from_mapping(observation["detections"][0]["box"])
            sign, direction = step_side(roi, sign, box.center)
            if is_positive_crossing(roi, direction):
                hits.append(observation["capturedAtUs"])
        self.assertEqual(hits, [3000000])
        expected = vector["expectedEvents"][0]
        self.assertEqual(len(hits), expected["measuredValue"])
        self.assertEqual(hits[0], expected["confirmedAtUs"])

    def test_diagonal_line_sign_is_derived_not_guessed(self) -> None:
        # 斜线上 LEFT_TO_RIGHT 只是符号方向的标签：A→B 为 (0,0)→(1,1)，右下方为正。
        diagonal = Roi.from_mapping(
            {"roiId": "diag", "shape": "LINE", "points": [[0.0, 0.0], [1.0, 1.0]], "positiveDirection": "LEFT_TO_RIGHT"}
        )
        self.assertEqual(side_sign(diagonal, (0.8, 0.2)), 1)
        self.assertEqual(side_sign(diagonal, (0.2, 0.8)), -1)
        self.assertEqual(side_sign(diagonal, (0.4, 0.4)), 0)
        self.assertEqual(step_side(diagonal, -1, (0.8, 0.2)), (1, CrossDirection.LEFT_TO_RIGHT))


class VectorDrivenContainmentTests(unittest.TestCase):
    """§15：几何结论由金样向量裁判，不由实现反推。

    这四条向量都是单帧 `IN_REGION` / `INSIDE`，只用几何就能算出命中的主体集合，
    无需等 `M11-T05` 的求值器；把它们在这里跑一遍，向量与几何模块互为约束。
    """

    INSIDE_VECTORS = {
        "geometry-polygon-boundary-point": {"track:1", "track:2"},
        "geometry-polygon-concave-notch": {"track:1"},
        "geometry-center-point-inside": {"track:1", "track:2"},
        "baseline-m07-roi-inside-and-outside-unchanged": {"track:1"},
    }

    def test_inside_subjects_match_the_expected_events(self) -> None:
        for vector_id, expected_keys in self.INSIDE_VECTORS.items():
            with self.subTest(vector=vector_id):
                vector = load_vector(vector_id)
                rois = {payload["roiId"]: Roi.from_mapping(payload) for payload in vector["rois"]}
                rule = vector["rules"][0]
                self.assertEqual(rule["operator"], "IN_REGION")
                self.assertEqual(rule.get("roiRelation"), "INSIDE")
                roi = rois[rule["roiId"]]
                observation = vector["observations"][0]
                self.assertEqual(len(vector["observations"]), 1)
                hit = {
                    f"track:{detection['trackId']}"
                    for detection in observation["detections"]
                    if detection["label"] in rule["targetLabels"]
                    and detection["confidence"] >= rule["thresholds"]["minConfidence"]
                    and box_in_roi(roi, Box.from_mapping(detection["box"]))
                }
                self.assertEqual(hit, expected_keys)
                self.assertEqual(
                    hit, {event["subjectKey"] for event in vector["expectedEvents"]}
                )

    def test_every_geometry_vector_is_exercised_by_this_file(self) -> None:
        # 新增 geometry-*.json 时必须在本文件里给出对应断言，否则这里会红。
        source = Path(__file__).read_text(encoding="utf-8")
        vector_ids = sorted(path.stem for path in VECTOR_DIR.glob("geometry-*.json"))
        self.assertTrue(vector_ids)
        for vector_id in vector_ids:
            with self.subTest(vector=vector_id):
                self.assertIn(vector_id, source)


class PurityTests(unittest.TestCase):
    """§1 三条硬约束在几何层的落点：纯函数、无系统时钟、无业务类别名。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (ROOT / "app/alerts/geometry.py").read_text(encoding="utf-8")
        cls.spec = (ROOT / "docs/alert-engine-spec.md").read_text(encoding="utf-8")

    def test_no_clock_and_no_io_on_the_geometry_path(self) -> None:
        for banned in (
            "time.time",
            "datetime",
            "monotonic",
            "perf_counter",
            "Instant.now",
            "currentTimeMillis",
            "random",
            "open(",
            "requests",
            "logging",
        ):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, self.source)

    def test_no_business_class_name_in_the_engine_source(self) -> None:
        # 按整词匹配：注释里的 "fires"／"person-hours" 之类不该误伤，业务类别名一个都不许有。
        words = set(re.findall(r"[a-z]+", self.source.lower()))
        for business in ("person", "helmet", "vest", "material", "fire", "smoke", "phone", "excavator"):
            with self.subTest(business=business):
                self.assertNotIn(business, words)

    def test_geometry_values_are_immutable(self) -> None:
        for cls in (Box, Roi):
            with self.subTest(cls=cls.__name__):
                self.assertTrue(cls.__dataclass_params__.frozen)
        roi = Roi.from_mapping(SQUARE)
        self.assertIsInstance(roi.points, tuple)
        with self.assertRaises(Exception):
            roi.roi_id = "renamed"

    def test_shape_capability_matches_the_schema(self) -> None:
        capabilities = json.loads(
            (ROOT / "docs/alert-engine.schema.json").read_text(encoding="utf-8")
        )["$defs"]["Capability"]["enum"]
        self.assertEqual(
            SHAPE_CAPABILITY, {RoiShape.POLYGON: "POLYGON_ROI", RoiShape.LINE: "LINE_ROI"}
        )
        for capability in SHAPE_CAPABILITY.values():
            self.assertIn(capability, capabilities)
        self.assertNotIn(RoiShape.RECT, SHAPE_CAPABILITY)

    def test_epsilon_is_the_value_frozen_in_the_spec(self) -> None:
        self.assertEqual(EPS, 1e-9)
        self.assertIn("1e-9", self.spec)
        self.assertIn("### 5.3 数值约定", self.spec)
        # 几何容差与 §15.1 的向量比对容差是两件事，规格明确写开。
        self.assertIn("1e-6", self.spec)


if __name__ == "__main__":
    unittest.main()
