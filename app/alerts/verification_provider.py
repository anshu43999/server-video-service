"""Provider boundary for project-scoped alert verification.

The service owns provider credentials and image egress.  This module keeps the
wire adapter replaceable and deliberately accepts only inline image data so a
provider can never fetch a project URL on its own.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


class VerificationProviderError(RuntimeError):
    """A safe, user-facing provider failure without credentials or payloads."""

    def __init__(self, kind: str, message: str = "verification provider unavailable") -> None:
        self.kind = kind
        super().__init__(message)


@dataclass(frozen=True)
class VerificationProviderResult:
    verdict: str
    reason: str
    source: str = "SERVER_PROVIDER"


class VerificationProvider(Protocol):
    def review(
        self,
        *,
        event: Mapping[str, Any],
        image_data: str,
        model_id: str,
        prompt_version: str,
        attempt_id: str | None = None,
    ) -> VerificationProviderResult:
        ...


class OpenAICompatibleVerificationProvider:
    """Bounded OpenAI-compatible chat-completions adapter.

    The endpoint and key are deployment-only inputs.  They are never returned
    by the project configuration API or written into verification records.
    """

    _DATA_IMAGE = re.compile(r"^data:image/(?:png|jpeg|jpg|webp);base64,[A-Za-z0-9+/=\r\n]+$", re.I)
    _VERDICTS = {
        "TRUE_POSITIVE": "CONFIRMED",
        "CONFIRMED": "CONFIRMED",
        "FALSE_POSITIVE": "SUSPECTED_FALSE_POSITIVE",
        "SUSPECTED_FALSE_POSITIVE": "SUSPECTED_FALSE_POSITIVE",
        "UNCERTAIN": "INCONCLUSIVE",
        "INCONCLUSIVE": "INCONCLUSIVE",
    }

    def __init__(self, endpoint: str, api_key: str, *, timeout_seconds: float = 60.0,
                 opener=urlopen) -> None:
        raw = endpoint.strip()
        parts = urlsplit(raw)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            raise ValueError("verification provider endpoint must be an HTTP(S) URL without credentials")
        if parts.query or parts.fragment:
            raise ValueError("verification provider endpoint must not contain query or fragment")
        path = parts.path.rstrip("/")
        if not path.endswith("/chat/completions"):
            path += "/chat/completions"
        self.endpoint = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
        self._api_key = api_key.strip()
        if not self._api_key:
            raise ValueError("verification provider API key is required")
        self.timeout_seconds = min(max(float(timeout_seconds), 1.0), 120.0)
        self._opener = opener

    def review(self, *, event: Mapping[str, Any], image_data: str, model_id: str,
               prompt_version: str, attempt_id: str | None = None) -> VerificationProviderResult:
        if not self._DATA_IMAGE.fullmatch(image_data.strip()):
            raise VerificationProviderError("MISSING_IMAGE", "review evidence is not an inline image")
        safe_event = {
            key: str(event.get(key) or "")[:256]
            for key in ("eventId", "ruleId", "label", "severity", "sourceId", "subjectKey")
        }
        body = {
            "model": model_id,
            "temperature": 0,
            "max_tokens": 256,
            "messages": [
                {"role": "system", "content": (
                    'Return one JSON object only: {"verdict":"TRUE_POSITIVE|FALSE_POSITIVE|UNCERTAIN",'
                    '"reason":"short explanation"}.'
                )},
                {"role": "user", "content": [
                    {"type": "text", "text": f"prompt={prompt_version}; event={json.dumps(safe_event, ensure_ascii=False)}"},
                    {"type": "image_url", "image_url": {"url": image_data, "detail": "low"}},
                ]},
            ],
        }
        request = Request(
            self.endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Accept": "application/json", "Content-Type": "application/json",
                     "Authorization": f"Bearer {self._api_key}"},
            method="POST",
        )
        if attempt_id:
            request.add_header("X-Request-ID", attempt_id)
            request.add_header("Idempotency-Key", attempt_id)
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                status = int(getattr(response, "status", 200))
                payload = response.read(2 * 1024 * 1024)
        except HTTPError as exc:
            kind = ("AUTHENTICATION" if exc.code in {401, 403} else "RATE_LIMITED" if exc.code == 429
                    else "TIMEOUT_UNKNOWN" if exc.code == 408
                    else "INVALID_REQUEST" if 400 <= exc.code < 500 else "PROVIDER_UNAVAILABLE")
            exc.close()
            raise VerificationProviderError(kind) from exc
        except TimeoutError as exc:
            raise VerificationProviderError("TIMEOUT_UNKNOWN") from exc
        except (URLError, OSError) as exc:
            raise VerificationProviderError("NETWORK") from exc
        if status < 200 or status >= 300:
            raise VerificationProviderError("PROVIDER_UNAVAILABLE")
        try:
            root = json.loads(payload.decode("utf-8"))
            content = root["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
            if not isinstance(content, str):
                raise ValueError
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\\s*|\\s*```$", "", content, flags=re.I | re.S).strip()
            result = json.loads(content)
            raw_verdict = str(result.get("verdict", "")).strip().upper()
            verdict = self._VERDICTS.get(raw_verdict)
            if verdict is None:
                raise ValueError
            reason = str(result.get("reason", "")).strip()[:4096]
            if not reason:
                raise ValueError
            return VerificationProviderResult(verdict=verdict, reason=reason)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise VerificationProviderError("MALFORMED_RESPONSE") from exc

