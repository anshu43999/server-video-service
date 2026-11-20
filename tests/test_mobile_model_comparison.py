import io
import json
import unittest
import zipfile
from unittest.mock import Mock, patch

import numpy as np
from tools.compare_mobile_model_outputs import (
    android_input, buffer_bytes, digest, embedded_metadata, graph_bytes_hash, phone_artifact, summarize, verify_identity,
)
from tools.reproduce_mobile_export_offline import FingerprintAudit, block_network
from tools.audit_mobile_weight_aliasing import same_weight


class MobileModelComparisonTests(unittest.TestCase):
    def test_weight_alias_requires_bytes_shape_and_quantization(self):
        a = dict(shape=[2, 3, 3, 4], type=9, sha256='same', zeros=[0], scales=[.01])
        self.assertTrue(same_weight(a, dict(a)))
        self.assertTrue(same_weight(a, dict(a, scales=[.010000001])))
        for change in ({'shape': [2, 3, 3, 5]}, {'type': 0}, {'sha256': 'other'},
                       {'zeros': [1]}, {'scales': [.02]}, {'scales': []}):
            self.assertFalse(same_weight(a, dict(a, **change)))

    def test_constant_pointer_reuse_detects_different_bytes(self):
        audit = FingerprintAudit()
        audit.observe(('cpu', (4, 4), 1234), 'first')
        audit.observe(('cpu', (4, 4), 1234), 'first')
        self.assertEqual(audit.collisions, [])
        audit.observe(('cpu', (4, 4), 1234), 'second')
        self.assertEqual(len(audit.collisions), 1)
        self.assertEqual(audit.collisions[0]['previousSha256'], 'first')
        self.assertEqual(audit.collisions[0]['newSha256'], 'second')

    def test_diagnostic_network_guard_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'network disabled'):
            block_network('example.invalid', 443)

    def test_external_constants_are_not_omitted(self):
        buffer = Mock()
        buffer.DataLength.return_value = 0
        buffer.Offset.return_value = 3
        buffer.Size.return_value = 4
        self.assertEqual(buffer_bytes(buffer, b'abcDATAend'), b'DATA')
        buffer.Size.return_value = 20
        with self.assertRaises(ValueError):
            buffer_bytes(buffer, b'abcDATAend')
        buffer.Size.return_value = 0
        self.assertEqual(buffer_bytes(buffer, b'abc'), b'')
        buffer.DataLength.return_value = 2
        buffer.DataAsNumpy.return_value = np.array([1, 2], dtype=np.uint8)
        self.assertEqual(buffer_bytes(buffer, b'abc'), bytes([1, 2]))

    def output(self, rows):
        return np.array(rows, dtype=np.float32).T[None]

    def test_letterbox_portrait_dimensions_and_padding(self):
        value, transform = android_input(np.zeros((900, 600, 3), dtype=np.uint8))
        self.assertEqual(value.shape, (1, 3, 640, 640))
        self.assertEqual(value.dtype, np.float32)
        self.assertEqual(transform["padding"], [106, 0, 107, 0])
        self.assertEqual(transform["resizedWidth"], 427)
        np.testing.assert_array_equal(value[0, :, :, 106:533], 0)
        np.testing.assert_allclose(value[0, :, :, :106], 114 / 255)

    def test_identity_rgb_order_and_normalization(self):
        rgb = np.array([[[255, 0, 127], [0, 255, 0]], [[1, 2, 3], [4, 5, 6]]], dtype=np.uint8)
        value, _ = android_input(rgb, 2)
        np.testing.assert_allclose(value[0], rgb.transpose(2, 0, 1).astype(np.float32) * np.float32(1 / 255))

    def test_resize_interpolates_without_uint8_rounding(self):
        rgb = np.zeros((2, 2, 3), dtype=np.uint8)
        rgb[0, 1] = 1
        value, _ = android_input(rgb, 4)
        self.assertAlmostEqual(float(value[0, 0, 0, 1]), .25 / 255, places=8)

    def test_best_class_filtered_without_reassignment(self):
        raw = self.output([[.5, .5, .4, .4, .7, .8]])
        result = summarize(raw, ["head", "helmet"], enabled={"head"})
        self.assertEqual(result["rawBestAboveThreshold"], 1)
        self.assertEqual(result["nmsCount"], 0)

    def test_empty_enabled_is_not_all(self):
        raw = self.output([[.5, .5, .4, .4, .8]])
        self.assertEqual(summarize(raw, ["head"], enabled=set())["nmsCount"], 0)
        self.assertEqual(summarize(raw, ["head"])["nmsCount"], 1)

    def test_nms_is_class_aware_and_deterministic(self):
        raw = self.output([[.5, .5, .4, .4, .8, .1], [.5, .5, .4, .4, .8, .1], [.5, .5, .4, .4, .1, .9]])
        result = summarize(raw, ["head", "helmet"])
        self.assertEqual(result["validCandidatesAfterClassFilter"], 3)
        self.assertEqual([item["candidate"] for item in result["nms"]], [2, 0])

    def test_disabled_candidates_do_not_consume_limit(self):
        raw = self.output([[.5, .5, .4, .4, .1, .99], [.2, .2, .1, .1, .6, .1]])
        result = summarize(raw, ["head", "helmet"], enabled={"head"}, limit=1)
        self.assertEqual(result["nms"][0]["candidate"], 1)

    def test_low_scores_produce_no_candidate_not_fake_success(self):
        raw = self.output([[.5, .5, .4, .4, .004, .025]])
        result = summarize(raw, ["head", "helmet"])
        self.assertEqual(result["rawBestAboveThreshold"], 0)
        self.assertEqual(result["nmsCount"], 0)

    def test_invalid_output_is_rejected(self):
        with self.assertRaises(ValueError):
            summarize(np.zeros((1, 7, 4)), ["head"])
        with self.assertRaises(ValueError):
            summarize(self.output([[.5, .5, .4, .4, np.nan]]), ["head"])

    def test_boxes_clip_before_nms_and_invalid_boxes_drop(self):
        raw = self.output([[0, 0, .4, .4, .8], [.5, .5, -1, .4, .9]])
        result = summarize(raw, ["head"])
        self.assertEqual(result["nmsCount"], 1)
        np.testing.assert_allclose(result["nms"][0]["boxNormalizedInput"], [0, 0, .2, .2])

    def test_artifact_and_source_hashes_must_match(self):
        manifest = {"modelFile": {"sha256": digest(b"model"), "sizeBytes": 5},
                    "source": {"revision": "source"}, "input": {"layout": "NCHW"},
                    "output": {"coordinateSpace": "normalized-input"}}
        verify_identity(b"model", manifest, "source")
        with self.assertRaises(ValueError):
            verify_identity(b"other", manifest, "source")
        with self.assertRaises(ValueError):
            verify_identity(b"model", manifest, "wrong")

    def test_zip_metadata_does_not_extract_files(self):
        stream = io.BytesIO(b"flatbuffer-prefix")
        with zipfile.ZipFile(stream, "a") as archive:
            archive.writestr("metadata.json", json.dumps({"version": "test", "privateField": "exclude"}))
        self.assertEqual(embedded_metadata(stream.getvalue()), {"version": "test"})
        self.assertIsNone(embedded_metadata(b"no zip"))
        self.assertEqual(graph_bytes_hash(stream.getvalue()), digest(b"flatbuffer-prefix"))
        self.assertEqual(graph_bytes_hash(b"raw"), digest(b"raw"))

    @patch("tools.compare_mobile_model_outputs.subprocess.run")
    def test_phone_paths_reject_traversal_before_adb(self, run):
        for directory in ["files/suite-model-artifacts/../shared_prefs", "/files/suite-model-artifacts/a", "files/suite-model-artifacts/a;id"]:
            with self.assertRaises(ValueError):
                phone_artifact("device", directory)
        run.assert_not_called()

    @patch("tools.compare_mobile_model_outputs.subprocess.run")
    def test_emulator_is_rejected(self, run):
        with self.assertRaises(ValueError):
            phone_artifact("emulator-5554", "files/suite-model-artifacts/a")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
