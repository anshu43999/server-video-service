import unittest

from app.protocol import MAX_FRAME_BYTES, MAX_FRAME_HEIGHT, MAX_FRAME_WIDTH, StreamState


class ProtocolTests(unittest.TestCase):
    def test_frozen_limits_and_states(self):
        self.assertEqual(MAX_FRAME_BYTES, 5 * 1024 * 1024)
        self.assertEqual((MAX_FRAME_WIDTH, MAX_FRAME_HEIGHT), (1920, 1080))
        self.assertEqual(StreamState.CREATED.value, "created")
        self.assertEqual(StreamState.OUTPUTTING.value, "outputting")


if __name__ == "__main__":
    unittest.main()
