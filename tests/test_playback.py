"""ADR-003 replaces playable URLs with a non-enumerating retirement contract."""
import unittest
from contextlib import nullcontext
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.config import settings
from app.main import app

class PlaybackApiTests(unittest.TestCase):
    def test_all_playback_ids_fail_without_resolving_resources_or_returning_urls(self):
        with nullcontext(TestClient(app)) as client, patch("app.main.get_stream", side_effect=AssertionError("must not look up a stream")):
            for prefix in ("/aiyoloapi/streams", "/aiyoloapi/projects/unknown/streams"):
                for name in ("missing", "existing", "foreign"):
                    with self.subTest(prefix=prefix, name=name):
                        response = client.get(f"{prefix}/{name}/playback")
                        self.assertEqual(410, response.status_code, response.text)
                        self.assertEqual("live_video_retired", response.json()["detail"]["code"])
                        self.assertNotIn("url", response.text)
                        self.assertIn("no-store", response.headers["cache-control"])
