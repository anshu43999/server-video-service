"""M08-T01：结构化检测结果、能力申报与可关闭叠加的回归测试。

只用标准库与 cv2（叠加需要），不需要 ultralytics：
与 ultralytics 的转换用鸭子类型桩对象驱动，保证坐标归一化与退化框丢弃有真实覆盖。
"""

from __future__ import annotations

import asyncio
import json
import re
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.detection import (
    CAPABILITY_BOX,
    CAPABILITY_MASK,
    CAPABILITY_TRACK,
    Detection,
    FrameDetections,
    InferenceResult,
    NormalizedBox,
    iso8601_from_us,
)
from app.config import settings
from app.detector import build_detections, decode_image, derive_provides, resolve_label
from app.overlay import class_color, draw_overlay, format_label
from app.stream import StreamSession

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "docs/alert-engine.schema.json").read_text(encoding="utf-8"))
PROTOCOL = (ROOT / "docs/video-protocol.md").read_text(encoding="utf-8")

# 业务类别名不得出现在推理与叠加代码里（场景通过 Manifest 与场景包注入）。
BUSINESS_WORDS = ("helmet", "hardhat", "smoke", "smoking", "fire", "flame", "phone", "vest", "intrusion")


class FakeBoxes:
    """模仿 ultralytics Results.boxes 的取值接口。"""

    def __init__(self, xyxy, conf, cls, ids=None):
        self.xyxy = xyxy
        self.conf = conf
        self.cls = cls
        self.id = ids


class FakeResult:
    def __init__(self, boxes=None):
        self.boxes = boxes


def protocol_detection_example() -> dict:
    """取 docs/video-protocol.md §6.2 里的检测消息示例，作为线上格式的唯一来源。"""
    section = PROTOCOL.split("### 6.2")[1]
    block = re.search(r"```json(.*?)```", section, re.S)
    assert block, "§6.2 缺少 JSON 示例"
    return json.loads(block.group(1).strip())


class NormalizedBoxTests(unittest.TestCase):
    def test_pixel_box_becomes_normalized_top_left_box(self):
        box = NormalizedBox.from_pixel_box(31, 44, 43, 112, 100, 200)
        self.assertEqual(box.to_wire(), {"x": 0.31, "y": 0.22, "w": 0.12, "h": 0.34})

    def test_out_of_frame_corners_are_clamped(self):
        box = NormalizedBox.from_pixel_box(-20, -1, 640, 480, 320, 240)
        self.assertEqual(box.to_wire(), {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0})

    def test_reversed_corners_are_ordered(self):
        self.assertEqual(
            NormalizedBox.from_pixel_box(80, 60, 20, 10, 100, 100),
            NormalizedBox.from_pixel_box(20, 10, 80, 60, 100, 100),
        )

    def test_degenerate_box_is_dropped_instead_of_raising(self):
        self.assertIsNone(NormalizedBox.from_pixel_box(10, 20, 10, 44, 100, 200))
        self.assertIsNone(NormalizedBox.from_pixel_box(10, 20, 30, 20, 100, 200))

    def test_zero_frame_size_is_an_error(self):
        with self.assertRaises(ValueError):
            NormalizedBox.from_pixel_box(0, 0, 10, 10, 0, 100)

    def test_box_rejects_out_of_range_and_non_finite_values(self):
        for kwargs in (
            {"x": -0.1, "y": 0.1, "w": 0.2, "h": 0.2},
            {"x": 0.9, "y": 0.1, "w": 0.2, "h": 0.2},
            {"x": 0.1, "y": 0.9, "w": 0.2, "h": 0.2},
            {"x": 0.1, "y": 0.1, "w": 0.0, "h": 0.2},
            {"x": 0.1, "y": 0.1, "w": 0.2, "h": -0.2},
            {"x": float("nan"), "y": 0.1, "w": 0.2, "h": 0.2},
            {"x": 0.1, "y": 0.1, "w": float("inf"), "h": 0.2},
        ):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                NormalizedBox(**kwargs)

    def test_pixel_round_trip_keeps_the_region(self):
        box = NormalizedBox(0.25, 0.5, 0.25, 0.25)
        self.assertEqual(box.as_pixels(400, 200), (100, 100, 200, 150))

    def test_box_is_frozen(self):
        with self.assertRaises(Exception):
            NormalizedBox(0.1, 0.1, 0.2, 0.2).x = 0.5


class DetectionShapeTests(unittest.TestCase):
    def setUp(self):
        self.detection = Detection(0, "person", 0.8712, NormalizedBox(0.31, 0.22, 0.12, 0.34))

    def test_wire_shape_matches_protocol_example(self):
        example = protocol_detection_example()
        self.assertEqual(set(self.detection.to_wire()), set(example["detections"][0]))

    def test_wire_confidence_is_rounded_and_box_is_nested(self):
        payload = self.detection.to_wire()
        self.assertEqual(payload["confidence"], 0.8712)
        self.assertEqual(payload["class_name"], "person")
        self.assertEqual(set(payload["box"]), {"x", "y", "w", "h"})

    def test_alert_payload_matches_schema_detection(self):
        allowed = set(SCHEMA["$defs"]["Detection"]["properties"])
        required = set(SCHEMA["$defs"]["Detection"]["required"])
        payload = self.detection.to_alert_detection()
        self.assertTrue(set(payload) <= allowed, f"unexpected keys: {set(payload) - allowed}")
        self.assertTrue(required <= set(payload))

    def test_track_id_appears_in_both_payloads_only_when_present(self):
        self.assertNotIn("track_id", self.detection.to_wire())
        self.assertNotIn("trackId", self.detection.to_alert_detection())
        tracked = Detection(0, "person", 0.5, NormalizedBox(0.1, 0.1, 0.2, 0.2), track_id="7")
        self.assertEqual(tracked.to_wire()["track_id"], "7")
        self.assertEqual(tracked.to_alert_detection()["trackId"], "7")

    def test_boxless_detection_omits_box(self):
        classification = Detection(3, "class-3", 0.4)
        self.assertNotIn("box", classification.to_wire())
        self.assertNotIn("box", classification.to_alert_detection())

    def test_invalid_detection_fields_are_rejected(self):
        with self.assertRaises(ValueError):
            Detection(0, "", 0.5)
        with self.assertRaises(ValueError):
            Detection(0, "person", 1.5)
        with self.assertRaises(ValueError):
            Detection(-1, "person", 0.5)
        with self.assertRaises(ValueError):
            Detection(0, "person", 0.5, track_id="bad id")

    def test_track_id_charset_matches_schema_pattern(self):
        schema_pattern = SCHEMA["$defs"]["Detection"]["properties"]["trackId"]["pattern"]
        self.assertTrue(re.match(schema_pattern, "track_7.a-b"))
        Detection(0, "person", 0.5, track_id="track_7.a-b")


class UltralyticsAdapterTests(unittest.TestCase):
    """build_detections 用鸭子类型驱动，不需要装 ultralytics。"""

    def test_boxes_become_normalized_detections(self):
        result = FakeResult(FakeBoxes([[31, 44, 43, 112]], [0.9], [0]))
        detections = build_detections(result, 100, 200, ("person", "car"))
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].label, "person")
        self.assertEqual(detections[0].class_id, 0)
        self.assertEqual(detections[0].box.to_wire(), {"x": 0.31, "y": 0.22, "w": 0.12, "h": 0.34})

    def test_labels_fall_back_to_class_id_without_names(self):
        result = FakeResult(FakeBoxes([[0, 0, 50, 50]], [0.5], [7]))
        self.assertEqual(build_detections(result, 100, 100)[0].label, "7")
        self.assertEqual(resolve_label(2, ("a", "b")), "2")
        self.assertEqual(resolve_label(1, ("a", "   ")), "1")

    def test_degenerate_boxes_are_dropped(self):
        result = FakeResult(FakeBoxes([[10, 10, 10, 50], [10, 10, 60, 50]], [0.6, 0.7], [0, 0]))
        self.assertEqual(len(build_detections(result, 100, 100, ("person",))), 1)

    def test_track_ids_are_carried_and_stringified(self):
        result = FakeResult(FakeBoxes([[10, 10, 60, 50]], [0.6], [0], ids=[3.0]))
        self.assertEqual(build_detections(result, 100, 100, ("person",))[0].track_id, "3")

    def test_confidence_is_clamped_into_range(self):
        result = FakeResult(FakeBoxes([[10, 10, 60, 50], [20, 20, 70, 60]], [1.4, -0.2], [0, 0]))
        detections = build_detections(result, 100, 100, ("person",))
        self.assertEqual([item.confidence for item in detections], [1.0, 0.0])

    def test_missing_or_short_payloads_yield_no_detections(self):
        self.assertEqual(build_detections(FakeResult(None), 100, 100), ())
        self.assertEqual(build_detections(FakeResult(FakeBoxes([[1, 2, 3]], [0.5], [0])), 100, 100), ())
        self.assertEqual(build_detections(object(), 100, 100), ())

    def test_tensor_like_payloads_are_accepted(self):
        class Arr:
            def __init__(self, value):
                self._value = value

            def tolist(self):
                return self._value

        result = FakeResult(FakeBoxes(Arr([[10, 10, 60, 50]]), Arr([0.5]), Arr([1])))
        self.assertEqual(build_detections(result, 100, 100, ("a", "b"))[0].label, "b")

    def test_provides_declares_box_even_for_an_empty_frame(self):
        self.assertEqual(derive_provides(()), (CAPABILITY_BOX,))

    def test_provides_adds_track_only_when_track_ids_exist(self):
        boxed = Detection(0, "person", 0.5, NormalizedBox(0.1, 0.1, 0.2, 0.2))
        tracked = Detection(0, "person", 0.5, NormalizedBox(0.1, 0.1, 0.2, 0.2), track_id="1")
        self.assertEqual(derive_provides((boxed,)), (CAPABILITY_BOX,))
        self.assertEqual(derive_provides((boxed, tracked)), (CAPABILITY_BOX, CAPABILITY_TRACK))

    def test_declared_capabilities_exist_in_the_alert_schema(self):
        allowed = set(SCHEMA["$defs"]["Capability"]["enum"])
        self.assertTrue({CAPABILITY_BOX, CAPABILITY_TRACK, CAPABILITY_MASK} <= allowed)


class InferenceResultTests(unittest.TestCase):
    def test_unavailable_result_carries_reason_and_no_detections(self):
        result = InferenceResult.unavailable("model not found", 640, 480)
        self.assertEqual(result.fallback_reason, "model not found")
        self.assertEqual(result.detections, ())
        self.assertEqual((result.frame_width, result.frame_height), (640, 480))
        self.assertEqual(result.provides, ())

    def test_counts_and_tracking_flag(self):
        boxed = Detection(0, "person", 0.5, NormalizedBox(0.1, 0.1, 0.2, 0.2))
        result = InferenceResult(detections=(boxed,), provides=(CAPABILITY_BOX,))
        self.assertEqual(result.detection_count, 1)
        self.assertFalse(result.has_tracking)
        tracked = InferenceResult(detections=(boxed, Detection(0, "person", 0.5, track_id="9")))
        self.assertTrue(tracked.has_tracking)


class FrameDetectionsTests(unittest.TestCase):
    def setUp(self):
        self.result = InferenceResult(
            detections=(Detection(0, "person", 0.8712, NormalizedBox(0.31, 0.22, 0.12, 0.34)),),
            model_id="yolo11n",
            class_names=("person", "car"),
            frame_width=1280,
            frame_height=720,
            inference_ms=18.437,
            provides=(CAPABILITY_BOX,),
        )
        self.frame = FrameDetections("inspection-001", 1024, 1_788_000_000_123_456, self.result)

    def test_wire_message_shape_matches_protocol_example(self):
        self.assertEqual(set(self.frame.to_wire()), set(protocol_detection_example()))

    def test_wire_message_values(self):
        payload = self.frame.to_wire()
        self.assertEqual(payload["stream_id"], "inspection-001")
        self.assertEqual(payload["frame_seq"], 1024)
        self.assertEqual(payload["model"], "yolo11n")
        self.assertEqual(payload["inference_ms"], 18.44)
        self.assertRegex(payload["captured_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2}$")

    def test_observation_matches_schema_observation(self):
        definition = SCHEMA["$defs"]["Observation"]
        envelope = self.frame.to_observation()
        self.assertTrue(set(envelope) <= set(definition["properties"]))
        self.assertTrue(set(definition["required"]) <= set(envelope))
        self.assertRegex(envelope["sourceId"], SCHEMA["$defs"]["Observation"]["properties"]["sourceId"]["pattern"])
        self.assertEqual(envelope["capturedAtUs"], 1_788_000_000_123_456)
        self.assertEqual(envelope["model"], {"modelId": "yolo11n", "classNames": ["person", "car"]})
        self.assertEqual(envelope["provides"], ["BOX"])

    def test_empty_payload_still_produces_an_envelope(self):
        empty = FrameDetections("cam-1", 5, 1_000_000, InferenceResult(provides=(CAPABILITY_BOX,)))
        envelope = empty.to_observation()
        self.assertEqual(envelope["detections"], [])
        self.assertEqual(envelope["frameSeq"], 5)
        self.assertNotIn("frameWidth", envelope)

    def test_source_id_charset_is_enforced_with_an_override(self):
        for stream_id in ("x" * 65, "巡检-001", "has space"):
            with self.subTest(stream_id=stream_id):
                frame = FrameDetections(stream_id, 1, 1_000_000, self.result)
                with self.assertRaises(ValueError):
                    frame.to_observation()
                self.assertEqual(frame.to_observation("cam-07")["sourceId"], "cam-07")

    def test_iso8601_helper_keeps_millisecond_precision(self):
        self.assertTrue(iso8601_from_us(1_788_000_000_123_456).endswith(iso8601_from_us(1_788_000_000_123_456)[-6:]))
        self.assertIn(".123", iso8601_from_us(1_788_000_000_123_456))


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((100, 200, 3), dtype=np.uint8)
        self.detections = (Detection(0, "person", 0.9, NormalizedBox(0.25, 0.25, 0.5, 0.5)),)

    def test_overlay_returns_a_new_frame_and_leaves_input_untouched(self):
        painted = draw_overlay(self.frame, self.detections)
        self.assertIsNot(painted, self.frame)
        self.assertEqual(int(self.frame.sum()), 0)
        self.assertGreater(int(painted.sum()), 0)

    def test_overlay_draws_on_the_declared_region(self):
        painted = draw_overlay(self.frame, self.detections)
        x1, y1, x2, y2 = self.detections[0].box.as_pixels(200, 100)
        border = painted[y1 : y1 + 2, x1 : x2, :]
        self.assertGreater(int(border.sum()), 0)
        self.assertEqual(int(painted[y2 + 5 :, :, :].sum()), 0)

    def test_no_detections_keeps_pixels_identical(self):
        self.assertTrue(np.array_equal(draw_overlay(self.frame, ()), self.frame))

    def test_boxless_detection_is_skipped(self):
        painted = draw_overlay(self.frame, (Detection(1, "class-1", 0.5),))
        self.assertTrue(np.array_equal(painted, self.frame))

    def test_class_color_is_stable_and_separates_classes(self):
        self.assertEqual(class_color(3), class_color(3))
        self.assertNotEqual(class_color(0), class_color(1))
        for class_id in range(12):
            self.assertTrue(all(0 <= channel <= 255 for channel in class_color(class_id)))

    def test_label_text_carries_confidence_and_track(self):
        detection = Detection(0, "person", 0.876, track_id="4")
        self.assertEqual(format_label(detection), "#4 person 0.88")
        self.assertEqual(format_label(Detection(0, "person", 0.876), show_confidence=False), "person")

    def test_missing_frame_is_an_error(self):
        with self.assertRaises(ValueError):
            draw_overlay(None, self.detections)


class SourceContractTests(unittest.TestCase):
    """M08-T01 的结构性承诺：结果结构与推理运行时解耦，代码里没有业务类别名。"""

    def setUp(self):
        self.detection_source = (ROOT / "app/detection.py").read_text(encoding="utf-8")
        self.detector_source = (ROOT / "app/detector.py").read_text(encoding="utf-8")
        self.overlay_source = (ROOT / "app/overlay.py").read_text(encoding="utf-8")

    def test_value_objects_do_not_depend_on_cv2_or_ultralytics(self):
        for forbidden in ("cv2", "ultralytics", "numpy", "torch"):
            self.assertNotIn(forbidden, self.detection_source, f"app/detection.py 不应依赖 {forbidden}")

    def test_inference_no_longer_returns_only_a_plotted_image(self):
        self.assertNotIn("plot()", self.detector_source)
        self.assertIn("def infer", self.detector_source)
        self.assertNotIn("def annotate", self.detector_source)

    def test_overlay_is_derived_from_structured_detections(self):
        self.assertIn("from .detection import Detection", self.overlay_source)
        self.assertNotIn("ultralytics", self.overlay_source)

    def test_no_business_class_names_in_inference_or_overlay(self):
        for name, source in (
            ("app/detection.py", self.detection_source),
            ("app/detector.py", self.detector_source),
            ("app/overlay.py", self.overlay_source),
        ):
            words = set(re.findall(r"[a-z]+", source.lower()))
            for business in BUSINESS_WORDS:
                self.assertNotIn(business, words, f"{name} 出现业务类别名 {business}")


def sample_jpeg() -> bytes:
    image = np.zeros((48, 64, 3), dtype=np.uint8)
    image[:, :, 2] = 200
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


def expected_publish_bytes(payload: bytes) -> bytes:
    """按 _publish_frame 的参数直接编码原始帧，用于确认叠加关闭时不改画面。"""
    quality = max(10, min(settings.jpeg_quality, 100))
    ok, encoded = cv2.imencode(".jpg", decode_image(payload), [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    assert ok
    return encoded.tobytes()


class StreamStructuredOutputTests(unittest.TestCase):
    """叠加可关闭、结构化结果照常产出（M08-T01 的验收面）。"""

    def _stub_session(self, stream_id: str, overlay_enabled: bool) -> StreamSession:
        session = StreamSession(stream_id)
        session.yolo_enabled = True
        session.overlay_enabled = overlay_enabled
        session.detector.infer = lambda frame: InferenceResult(
            detections=(Detection(0, "person", 0.9, NormalizedBox(0.25, 0.25, 0.5, 0.5)),),
            model_id="stub",
            class_names=("person",),
            frame_width=frame.shape[1],
            frame_height=frame.shape[0],
            inference_ms=1.0,
            provides=(CAPABILITY_BOX,),
        )
        return session

    @staticmethod
    async def _wait_for_frame(session: StreamSession, timeout: float = 2.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while session.latest_detections is None and loop.time() < deadline:
            await asyncio.sleep(0.01)

    def test_overlay_off_publishes_the_untouched_frame_but_keeps_detections(self):
        async def scenario():
            payload = sample_jpeg()
            session = self._stub_session("overlay-off", False)
            session._last_input = 0
            await session.ingest_jpeg(payload)
            await self._wait_for_frame(session)
            self.assertEqual(session.latest_jpeg, expected_publish_bytes(payload))
            self.assertEqual(session.latest_detections.result.detection_count, 1)
            self.assertEqual(session.frames_processed, 1)

        asyncio.run(scenario())

    def test_overlay_on_changes_the_published_frame(self):
        async def scenario():
            payload = sample_jpeg()
            session = self._stub_session("overlay-on", True)
            session._last_input = 0
            await session.ingest_jpeg(payload)
            await self._wait_for_frame(session)
            self.assertNotEqual(session.latest_jpeg, expected_publish_bytes(payload))
            self.assertEqual(session.latest_detections.result.detection_count, 1)

        asyncio.run(scenario())

    def test_frame_identity_increments_and_time_never_goes_backwards(self):
        async def scenario():
            session = self._stub_session("identity", False)
            observed = []
            for _ in range(3):
                session._last_input = 0
                await session.ingest_jpeg(sample_jpeg())
                await self._wait_for_frame(session)
                record = session.latest_detections
                observed.append((record.frame_seq, record.captured_at_us))
                session.latest_detections = None
            self.assertEqual([seq for seq, _ in observed], [1, 2, 3])
            stamps = [stamp for _, stamp in observed]
            self.assertEqual(stamps, sorted(stamps))

        asyncio.run(scenario())

    def test_observation_envelope_is_reachable_from_a_live_session(self):
        async def scenario():
            session = self._stub_session("cam-07", False)
            session._last_input = 0
            await session.ingest_jpeg(sample_jpeg())
            await self._wait_for_frame(session)
            envelope = session.latest_detections.to_observation()
            self.assertEqual(envelope["sourceId"], "cam-07")
            self.assertEqual(envelope["provides"], ["BOX"])
            self.assertEqual(len(envelope["detections"]), 1)
            self.assertEqual(session.metrics()["detections_last"], 1)

        asyncio.run(scenario())

    def test_disabling_yolo_drops_stale_detections(self):
        async def scenario():
            session = self._stub_session("toggle", False)
            session._last_input = 0
            await session.ingest_jpeg(sample_jpeg())
            await self._wait_for_frame(session)
            self.assertIsNotNone(session.latest_detections)
            await session.set_yolo(False)
            self.assertIsNone(session.latest_detections)
            self.assertEqual(session.metrics()["detections_last"], 0)

        asyncio.run(scenario())

    def test_missing_model_falls_back_without_fabricating_detections(self):
        async def scenario():
            session = StreamSession("missing-model")
            session.detector.model_path = "models/definitely-missing-model.pt"
            await session.set_yolo(True)
            session._last_input = 0
            await session.ingest_jpeg(sample_jpeg())
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 2.0
            while session.latest_jpeg is None and loop.time() < deadline:
                await asyncio.sleep(0.01)
            self.assertIsNotNone(session.latest_jpeg)
            self.assertIsNone(session.latest_detections)
            self.assertEqual(session.frames_fallback, 1)
            self.assertEqual(session.frames_processed, 0)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
