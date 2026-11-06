"""Publishing is removed; old authorization is a deny-only tombstone."""
import importlib.util
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.media_authorization import MediaAuthorizationRequest, authorize_media_read, create_media_authorization_router


class PublisherRetirementTests(unittest.TestCase):
    def test_publisher_module_is_removed(self):
        self.assertIsNone(importlib.util.find_spec("app.publisher"))

    def test_every_old_action_fails_without_session_lookup(self):
        with patch("app.auth._session_user", side_effect=AssertionError("session lookup")):
            for action in ("read", "playback", "publish", "api", "metrics", "pprof", "unknown", ""):
                with self.subTest(action=action), self.assertRaises(HTTPException) as rejected:
                    authorize_media_read(MediaAuthorizationRequest(action=action, password="retired-secret"), object())
                self.assertEqual(403, rejected.exception.status_code)
                self.assertEqual("live_video_retired", rejected.exception.detail)

    def test_http_callback_rejects_malformed_empty_and_old_valid_payloads(self):
        app = FastAPI()
        app.include_router(create_media_authorization_router())
        with TestClient(app) as client:
            for body in (b"", b"not-json", b'{}', b'{"action":"publish","password":"old"}'):
                response = client.post("/aiyoloapi/internal/media/authorize", content=body)
                self.assertEqual(403, response.status_code)
                self.assertEqual({"detail": "live_video_retired"}, response.json())


if __name__ == "__main__":
    unittest.main()
