"""One immutable class policy per runtime; full model labels remain unchanged."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from app.detector import YoloDetector
from app.stream import StreamSession


class CategoryRuntimeFilterTests(unittest.TestCase):
    def detector(self, enabled):
        detector = YoloDetector("same.pt", classes=["first", "second"], enabled_labels=enabled,
                                max_detections=1)
        detector._model = Mock()
        detector._model.predict.return_value = [SimpleNamespace(boxes=SimpleNamespace(
            xyxy=[[0, 0, 20, 20], [30, 30, 50, 50]], conf=[.95, .85], cls=[0, 1], id=None))]
        return detector

    def test_filter_keeps_original_ids_and_passes_policy_before_nms_limit(self):
        detector = self.detector(["second"])
        result = detector.infer(np.zeros((100, 100, 3), dtype=np.uint8))
        self.assertEqual([(1, "second")], [(d.class_id, d.label) for d in result.detections])
        self.assertEqual(("first", "second"), result.class_names)
        self.assertEqual([1], detector._model.predict.call_args.kwargs["classes"])
        self.assertEqual(1, detector._model.predict.call_args.kwargs["max_det"])

    def test_empty_policy_is_empty_without_prediction_and_sessions_do_not_leak(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        empty, first, second = self.detector([]), self.detector(["first"]), self.detector(["second"])
        self.assertEqual((), empty.infer(frame).detections)
        empty._model.predict.assert_not_called()
        self.assertEqual("first", first.infer(frame).detections[0].label)
        self.assertEqual("second", second.infer(frame).detections[0].label)
        self.assertEqual("first", first.infer(frame).detections[0].label)

    def test_stream_rebind_replaces_policy_without_changing_model_path_or_labels(self):
        stream = StreamSession("test", "test")
        for labels in (["second"], []):
            stream.bind_model(model_id="same", model_path="same.pt", labels=["first", "second"],
                              enabled_labels=labels)
            self.assertEqual(frozenset(labels), stream.detector.enabled_labels)
            self.assertEqual(("first", "second"), stream.detector.class_names)
            self.assertEqual("same.pt", stream.detector.model_path)

    def test_real_yolo_postprocessing_filters_best_class_before_max_det_without_relabeling(self):
        import torch
        from ultralytics.utils.nms import non_max_suppression

        # Three candidates; disabled best class has an enabled runner-up. It must
        # be rejected, not relabeled, and must not consume the max_det=1 slot.
        tensor = torch.tensor([[[10., 40., 70.], [10., 40., 70.], [8., 8., 8.],
                                [8., 8., 8.], [.99, .1, .2], [.98, .8, .7]]])
        result = non_max_suppression(tensor, conf_thres=.25, iou_thres=.45,
                                     classes=[1], max_det=1, nc=2)[0]
        self.assertEqual((1, 6), tuple(result.shape))
        self.assertEqual(1, int(result[0, 5]))
        self.assertAlmostEqual(.8, float(result[0, 4]), places=5)
