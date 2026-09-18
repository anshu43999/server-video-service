import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.alerts.disposition import AlertDispositionStore
from app.alerts.runtime import ServerAlertRuntime
from app.detection import Detection, InferenceResult, NormalizedBox
from app.model_parameters import ModelParameterStore


MODEL = {"modelId": "runtime-model", "name": "Runtime model", "version": "1.0.0", "labels": ["head", "helmet"]}


class CaptureDelivery:
    def __init__(self):
        self.events = []

    def dispatch(self, event):
        self.events.append(event["eventId"])
        return ["delivery-test"]


class ServerAlertRuntimeTests(unittest.TestCase):
    def test_model_defaults_generate_confirmed_event_end_it_and_save_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            events = AlertDispositionStore()
            delivery = CaptureDelivery()
            runtime = ServerAlertRuntime(
                model_provider=lambda model_id: MODEL,
                parameter_store=ModelParameterStore(Path(temp) / "profiles.json"),
                event_store=events,
                delivery_service=delivery,
                evidence_root=Path(temp) / "evidence",
            )
            box = NormalizedBox(0.1, 0.1, 0.2, 0.3)
            result = InferenceResult(
                detections=(Detection(0, "head", 0.9, box),),
                model_id="runtime-model", class_names=("head", "helmet"),
                frame_width=100, frame_height=100, provides=("BOX",),
            )
            for timestamp in (1_000_000_000_000, 1_000_200_000_000, 1_000_400_000_000, 1_000_800_000_000):
                emitted = runtime.process(
                    source_id="camera-1", captured_at_us=timestamp,
                    result=result, frame=np.zeros((100, 100, 3), dtype=np.uint8),
                )
            self.assertEqual(len(emitted), 1)
            event_id = emitted[0]["eventId"]
            self.assertEqual(emitted[0]["origin"], "SERVER_STREAM")
            self.assertEqual(emitted[0]["streamId"], "camera-1")
            self.assertEqual(delivery.events, [event_id])
            self.assertTrue((Path(temp) / "evidence" / f"{event_id}.jpg").is_file())
            self.assertEqual(events.get(event_id)["state"], "CONFIRMED")

            ended = runtime.process(
                source_id="camera-1", captured_at_us=1_001_000_000_000,
                result=InferenceResult(model_id="runtime-model", class_names=("head", "helmet"), provides=("BOX",)),
            )
            self.assertEqual(ended, [])
            self.assertEqual(events.get(event_id)["state"], "ENDED")
            self.assertEqual(delivery.events, [event_id])

    def test_disabled_category_never_creates_event(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ModelParameterStore(Path(temp) / "profiles.json")
            delivery = CaptureDelivery()
            runtime = ServerAlertRuntime(
                model_provider=lambda model_id: MODEL,
                parameter_store=store,
                event_store=AlertDispositionStore(),
                delivery_service=delivery,
                evidence_root=Path(temp) / "evidence",
            )
            # helmet is disabled by the default profile.
            result = InferenceResult(
                detections=(Detection(1, "helmet", 0.99),), model_id="runtime-model",
                class_names=("head", "helmet"), provides=("BOX",),
            )
            for timestamp in (2_000_000_000_000, 2_000_200_000_000, 2_000_400_000_000, 2_000_800_000_000):
                runtime.process(source_id="camera-2", captured_at_us=timestamp, result=result)
            self.assertEqual(delivery.events, [])


if __name__ == "__main__":
    unittest.main()
