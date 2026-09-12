import unittest

from app.alerts.observation import (
    NonMonotonicTimestampError,
    ObservationEnvelope,
    ObservationError,
    ObservationIngestor,
    validate_operator_compatibility,
)


class ObservationEnvelopeTests(unittest.TestCase):
    def test_accepts_all_four_payload_families_and_round_trips(self):
        raw = {
            "sourceId": "cam-07", "frameSeq": 9, "capturedAtUs": 1000,
            "provides": ["BOX", "TRACK", "MASK", "SCALAR"],
            "detections": [{"label": "person", "confidence": 0.9, "box": {"x": .1, "y": .2, "w": .3, "h": .4}, "trackId": "t1"}],
            "classifications": [{"label": "fire", "confidence": .7}],
            "masks": [{"label": "smoke", "confidence": .6, "areaRatio": .2, "polygon": [[.1, .1], [.2, .1], [.2, .2]]}],
            "scalars": [{"metricId": "pm25-01", "value": 83.2, "unit": "ug/m3"}],
        }
        envelope = ObservationEnvelope.from_mapping(raw)
        self.assertEqual(envelope.source_id, "cam-07")
        self.assertEqual(envelope.actual_capabilities, {"BOX", "TRACK", "MASK", "SCALAR"})
        self.assertEqual(envelope.to_mapping()["scalars"][0]["metricId"], "pm25-01")

    def test_empty_envelope_is_valid_and_frame_sequence_may_jump(self):
        state = ObservationIngestor()
        state.ingest({"sourceId": "cam", "frameSeq": 1, "capturedAtUs": 10, "provides": []})
        state.ingest({"sourceId": "cam", "frameSeq": 99, "capturedAtUs": 10, "provides": []})
        self.assertEqual(state.last_timestamp("cam"), 10)

    def test_timestamp_must_be_monotonic_per_source(self):
        state = ObservationIngestor()
        state.ingest({"sourceId": "cam", "frameSeq": 1, "capturedAtUs": 20, "provides": []})
        with self.assertRaises(NonMonotonicTimestampError):
            state.ingest({"sourceId": "cam", "frameSeq": 2, "capturedAtUs": 19, "provides": []})
        state.ingest({"sourceId": "other", "frameSeq": 1, "capturedAtUs": 1, "provides": []})

    def test_boxless_classification_is_explicitly_rejected_for_box_operator(self):
        observation = {"sourceId": "cls", "frameSeq": 1, "capturedAtUs": 1, "provides": [], "classifications": [{"label": "fire", "confidence": .8}]}
        rejection = validate_operator_compatibility(observation, "IN_REGION", subject_kind="frame", rule_id="r1")
        self.assertIsNotNone(rejection)
        self.assertEqual(rejection.code, "CAPABILITY_UNSATISFIED")
        self.assertEqual(rejection.missing, ("BOX",))

    def test_frame_subject_rejects_temporal_operator(self):
        observation = {"sourceId": "cls", "frameSeq": 1, "capturedAtUs": 1, "provides": []}
        rejection = validate_operator_compatibility(observation, "DWELL", subject_kind="frame")
        self.assertEqual(rejection.code, "SUBJECT_KIND_UNSUPPORTED")

    def test_declared_vs_actual_capability_mismatch_is_exposed(self):
        state = ObservationIngestor()
        envelope = state.ingest({"sourceId": "cam", "frameSeq": 1, "capturedAtUs": 1, "provides": ["BOX"], "detections": [{"label": "x", "confidence": .5}]})
        self.assertEqual(envelope.capability_mismatches, ("BOX",))
        self.assertEqual(state.capability_mismatch_count, 1)

    def test_unknown_fields_and_invalid_values_are_rejected(self):
        with self.assertRaises(ObservationError):
            ObservationEnvelope.from_mapping({"sourceId": "cam", "frameSeq": 0, "capturedAtUs": 1, "provides": [], "oops": 1})
        with self.assertRaises(ObservationError):
            ObservationEnvelope.from_mapping({"sourceId": "cam", "frameSeq": 0, "capturedAtUs": 1, "provides": [], "scalars": [{"metricId": "bad id", "value": 1}]})


if __name__ == "__main__":
    unittest.main()
