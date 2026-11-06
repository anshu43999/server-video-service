import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch
import unittest

from tools.player_compatibility_probe import main


class PlayerCompatibilityRetirementTests(unittest.TestCase):
    def test_probe_never_opens_network_or_launches_player(self):
        output = io.StringIO()
        with patch("socket.socket", side_effect=AssertionError("network")), patch("subprocess.Popen", side_effect=AssertionError("player")), redirect_stdout(output):
            self.assertEqual(2, main())
        self.assertEqual("live_video_retired", json.loads(output.getvalue())["error"])


if __name__ == "__main__":
    unittest.main()
