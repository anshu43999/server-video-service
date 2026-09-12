"""Manual multimodal verification coordination for alert events.

The first server integration deliberately stops at a safe coordination boundary: it records a
manual request, enforces privacy/quota/deduplication rules, and returns a diagnosable failure when
no provider is configured. A provider adapter can be added without changing the HTTP contract.
"""
from __future__ import annotations

from copy import deepcopy
import threading
import time
from typing import Any, Mapping


class AlertVerificationStore:
    def __init__(self, daily_limit: int = 100) -> None:
        self._lock = threading.RLock()
        self._results: dict[str, dict[str, Any]] = {}
        self._calls_today = 0
        self._day = self._day_key()
        self.daily_limit = max(0, int(daily_limit))
        self.enabled = False
        self.image_egress_authorized = False
        self.model_id = ""
        self.provider_configured = False

    @staticmethod
    def _day_key() -> int:
        return int(time.time() // 86400)

    def _rollover(self) -> None:
        day = self._day_key()
        if day != self._day:
            self._day = day
            self._calls_today = 0

    def get(self, event_id: str) -> dict[str, Any] | None:
        with self._lock:
            result = self._results.get(event_id)
            return deepcopy(result) if result else None

    def request(self, event: Mapping[str, Any], *, actor: str, image_ref: str | None = None) -> dict[str, Any]:
        event_id = str(event.get("eventId") or event.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("eventId is required")
        with self._lock:
            self._rollover()
            existing = self._results.get(event_id)
            if existing:
                return deepcopy(existing)
            now = time.time_ns() // 1000
            base = {
                "eventId": event_id,
                "status": "PENDING",
                "verdict": None,
                "reason": "已接受人工发起请求",
                "modelId": self.model_id,
                "promptVersion": "verify-v1",
                "latencyMs": 0,
                "requestedAtUs": now,
                "completedAtUs": None,
                "source": "MANUAL_PC",
                "actor": actor,
                "image": image_ref,
            }
            # These checks are intentionally ordered from privacy to spend.
            if not self.enabled:
                base.update(status="FAILED", reason="智能复核未开启", failureKind="DISABLED")
            elif not self.image_egress_authorized:
                base.update(status="FAILED", reason="未授权图像出站，未发送任何图片", failureKind="NOT_AUTHORIZED")
            elif not image_ref:
                base.update(status="FAILED", reason="告警缺少可用证据图片", failureKind="MISSING_IMAGE")
            elif self._calls_today >= self.daily_limit:
                base.update(status="FAILED", reason="今日复核额度已用尽", failureKind="QUOTA_EXHAUSTED")
            elif not self.provider_configured:
                self._calls_today += 1
                base.update(status="FAILED", reason="未配置可用的复核供应商或模型", failureKind="NOT_CONFIGURED")
            else:
                self._calls_today += 1
                base.update(status="FAILED", reason="服务端复核适配器尚未启用", failureKind="PROVIDER_UNAVAILABLE")
            base["completedAtUs"] = time.time_ns() // 1000
            self._results[event_id] = base
            return deepcopy(base)

    def reset(self) -> None:
        with self._lock:
            self._results.clear()
            self._calls_today = 0
            self._day = self._day_key()


alert_verification_store = AlertVerificationStore()

