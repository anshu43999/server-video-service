import base64
import json
import unittest
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import Request

from app.alerts.verification import AlertVerificationStore
from app.alerts.verification_provider import (
    OpenAICompatibleVerificationProvider,
    VerificationProviderError,
)


IMAGE = "data:image/jpeg;base64," + base64.b64encode(b"jpeg-fixture").decode("ascii")


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit):
        return self.payload


class VerificationProviderTests(unittest.TestCase):
    def test_adapter_sends_inline_image_and_maps_verdict(self):
        seen = {}

        def opener(request: Request, timeout: float):
            seen.update(url=request.full_url, timeout=timeout, body=json.loads(request.data),
                        auth=request.get_header("Authorization"), attempt=request.get_header("Idempotency-key"))
            return FakeResponse({"choices": [{"message": {"content": '{"verdict":"FALSE_POSITIVE","reason":"not a violation"}'}}]})

        provider = OpenAICompatibleVerificationProvider("https://review.example/v1", "secret-key", opener=opener)
        result = provider.review(event={"eventId": "same", "projectId": "project-a", "label": "helmet"},
                                 image_data=IMAGE, model_id="vision-1", prompt_version="verify-v1",
                                 attempt_id="attempt-fixture")
        self.assertEqual("SUSPECTED_FALSE_POSITIVE", result.verdict)
        self.assertEqual("https://review.example/v1/chat/completions", seen["url"])
        self.assertEqual("Bearer secret-key", seen["auth"])
        self.assertEqual("attempt-fixture", seen["attempt"])
        image = seen["body"]["messages"][1]["content"][1]["image_url"]["url"]
        self.assertEqual(IMAGE, image)

    def test_adapter_rejects_urls_and_sanitizes_provider_failures(self):
        provider = OpenAICompatibleVerificationProvider("https://review.example", "secret-key",
                                                       opener=lambda *_, **__: (_ for _ in ()).throw(OSError("secret")))
        with self.assertRaises(VerificationProviderError) as missing:
            provider.review(event={}, image_data="https://foreign/image.jpg", model_id="m", prompt_version="v1")
        self.assertEqual("MISSING_IMAGE", missing.exception.kind)
        with self.assertRaises(VerificationProviderError) as network:
            provider.review(event={}, image_data=IMAGE, model_id="m", prompt_version="v1")
        self.assertEqual("NETWORK", network.exception.kind)

    def test_project_store_records_provider_result_without_image_or_cross_project_state(self):
        class Provider:
            def review(self, **kwargs):
                self.project = kwargs["event"].get("projectId")
                return type("Result", (), {"verdict": "CONFIRMED", "reason": "matched", "source": "TEST_PROVIDER"})()

        provider = Provider()
        store = AlertVerificationStore(provider=provider)
        store.configure(enabled=True, image_egress_authorized=True, daily_limit=3, model_id="m",
                        provider_configured=True, project_id="project-a")
        event = {"eventId": "shared", "projectId": "project-a", "label": "helmet"}
        result = store.request(event, actor="account-a", image_ref="/project-a/evidence", image_data=IMAGE,
                               project_id="project-a")
        self.assertEqual("CONFIRMED", result["status"])
        self.assertNotIn("imageData", result)
        self.assertEqual("project-a", result["projectId"])
        with self.assertRaises(ValueError):
            store.request({**event, "projectId": "project-b"}, actor="account-b", image_data=IMAGE,
                          project_id="project-a")

    def test_adapter_timeout_has_unknown_outcome_and_http_429_is_explicitly_retryable(self):
        for error, expected in ((TimeoutError("private timeout"), "TIMEOUT_UNKNOWN"),
                                (HTTPError("https://review.example", 429, "limited", {}, BytesIO()), "RATE_LIMITED")):
            def opener(*args, **kwargs):
                raise error
            provider = OpenAICompatibleVerificationProvider("https://review.example", "secret", opener=opener)
            with self.assertRaises(VerificationProviderError) as caught:
                provider.review(event={}, image_data=IMAGE, model_id="m", prompt_version="v1")
            self.assertEqual(expected, caught.exception.kind)
            self.assertNotIn("private", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
