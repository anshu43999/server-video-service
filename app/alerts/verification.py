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

from sqlalchemy import delete, select

from ..database import (
    AlertVerificationConfigRecord,
    AlertVerificationRecord,
    DatabaseManager,
)


class AlertVerificationStore:
    def __init__(self, daily_limit: int = 100, database_manager: DatabaseManager | None = None) -> None:
        self._lock = threading.RLock()
        self._results: dict[str, dict[str, Any]] = {}
        self._calls_today = 0
        self._day = self._day_key()
        self.daily_limit = max(0, int(daily_limit))
        self.enabled = False
        self.image_egress_authorized = False
        self.model_id = ""
        self.provider_configured = False
        self._database = database_manager

    @property
    def database_manager(self) -> DatabaseManager | None:
        return self._database

    def configure_database(self, database_manager: DatabaseManager | None) -> None:
        with self._lock:
            self._database = database_manager

    def _config_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "imageEgressAuthorized": self.image_egress_authorized,
            "dailyLimit": self.daily_limit,
            "modelId": self.model_id,
            "providerConfigured": self.provider_configured,
            "day": self._day,
        }

    def _load_config(self, session) -> None:
        row = session.get(AlertVerificationConfigRecord, "default")
        if row is None:
            return
        payload = dict(row.payload or {})
        self.enabled = bool(payload.get("enabled", self.enabled))
        self.image_egress_authorized = bool(payload.get("imageEgressAuthorized", self.image_egress_authorized))
        self.daily_limit = max(0, int(payload.get("dailyLimit", row.calls_day)))
        self.model_id = str(payload.get("modelId") or "")
        self.provider_configured = bool(payload.get("providerConfigured", self.provider_configured))
        stored_day = payload.get("day")
        self._day = int(stored_day) if stored_day is not None else self._day_key()
        self._calls_today = int(row.calls_today or 0)
        self._rollover()

    def _save_config(self, session) -> None:
        row = session.get(AlertVerificationConfigRecord, "default")
        payload = self._config_payload()
        if row is None:
            session.add(AlertVerificationConfigRecord(
                config_key="default", calls_day=self.daily_limit,
                calls_today=self._calls_today, payload=payload,
            ))
        else:
            row.calls_day = self.daily_limit
            row.calls_today = self._calls_today
            row.payload = payload

    @staticmethod
    def _day_key() -> int:
        return int(time.time() // 86400)

    def _rollover(self) -> None:
        day = self._day_key()
        if day != self._day:
            self._day = day
            self._calls_today = 0

    def get(self, event_id: str) -> dict[str, Any] | None:
        if self._database is not None:
            with self._database.session() as session:
                row = session.get(AlertVerificationRecord, event_id)
                return deepcopy(dict(row.payload)) if row else None
        with self._lock:
            result = self._results.get(event_id)
            return deepcopy(result) if result else None

    def request(self, event: Mapping[str, Any], *, actor: str, image_ref: str | None = None) -> dict[str, Any]:
        event_id = str(event.get("eventId") or event.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("eventId is required")
        with self._lock:
            if self._database is not None:
                return self._request_database(event, event_id, actor, image_ref)
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

    def _request_database(self, event: Mapping[str, Any], event_id: str, actor: str,
                          image_ref: str | None) -> dict[str, Any]:
        database_manager = self._database
        with self._database.session() as session:
            # Test and embedded callers may intentionally use an in-memory alert
            # store while this singleton is database-backed. Keep that explicit
            # isolation working without weakening the production FK contract.
            from ..database import AlertEventRecord
            if session.get(AlertEventRecord, event_id) is None:
                self._database = None
                try:
                    return self.request(event, actor=actor, image_ref=image_ref)
                finally:
                    self._database = database_manager
            config = session.scalar(select(AlertVerificationConfigRecord).where(
                AlertVerificationConfigRecord.config_key == "default"
            ).with_for_update())
            if config is not None:
                self.enabled = bool((config.payload or {}).get("enabled", self.enabled))
                self.image_egress_authorized = bool((config.payload or {}).get("imageEgressAuthorized", self.image_egress_authorized))
                self.daily_limit = max(0, int((config.payload or {}).get("dailyLimit", config.calls_day)))
                self.model_id = str((config.payload or {}).get("modelId") or "")
                self.provider_configured = bool((config.payload or {}).get("providerConfigured", self.provider_configured))
                self._day = int((config.payload or {}).get("day", self._day_key()))
                self._calls_today = int(config.calls_today or 0)
            self._rollover()
            existing = session.get(AlertVerificationRecord, event_id)
            if existing is not None:
                return deepcopy(dict(existing.payload))
            now = time.time_ns() // 1000
            base = {
                "eventId": event_id, "status": "PENDING", "verdict": None,
                "reason": "已接受人工发起请求", "modelId": self.model_id,
                "promptVersion": "verify-v1", "latencyMs": 0,
                "requestedAtUs": now, "completedAtUs": None, "source": "MANUAL_PC",
                "actor": actor, "image": image_ref,
            }
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
            session.add(AlertVerificationRecord(event_id=event_id, status=base["status"], payload=base))
            self._save_config(session)
            return deepcopy(base)

    def reset(self) -> None:
        with self._lock:
            self._results.clear()
            self._calls_today = 0
            self._day = self._day_key()
            if self._database is not None:
                with self._database.session() as session:
                    session.execute(delete(AlertVerificationRecord))
                    session.execute(delete(AlertVerificationConfigRecord))

    def configure(self, *, enabled: bool, image_egress_authorized: bool,
                  daily_limit: int, model_id: str, provider_configured: bool) -> dict[str, Any]:
        with self._lock:
            self.enabled = bool(enabled)
            self.image_egress_authorized = bool(image_egress_authorized)
            self.daily_limit = max(0, int(daily_limit))
            self.model_id = str(model_id or "").strip()
            self.provider_configured = bool(provider_configured)
            self._rollover()
            if self._database is not None:
                with self._database.session() as session:
                    row = session.scalar(select(AlertVerificationConfigRecord).where(
                        AlertVerificationConfigRecord.config_key == "default"
                    ).with_for_update())
                    if row is not None:
                        self._calls_today = int(row.calls_today or 0)
                        self._day = int((row.payload or {}).get("day", self._day_key()))
                        self._rollover()
                    self.enabled = bool(enabled)
                    self.image_egress_authorized = bool(image_egress_authorized)
                    self.daily_limit = max(0, int(daily_limit))
                    self.model_id = str(model_id or "").strip()
                    self.provider_configured = bool(provider_configured)
                    self._save_config(session)
            return {
                "enabled": self.enabled,
                "imageEgressAuthorized": self.image_egress_authorized,
                "dailyLimit": self.daily_limit,
                "modelId": self.model_id,
                "providerConfigured": self.provider_configured,
                "callsToday": self._calls_today,
            }

    def config(self) -> dict[str, Any]:
        with self._lock:
            if self._database is not None:
                with self._database.session() as session:
                    self._load_config(session)
            return {
                "enabled": self.enabled,
                "imageEgressAuthorized": self.image_egress_authorized,
                "dailyLimit": self.daily_limit,
                "modelId": self.model_id,
                "providerConfigured": self.provider_configured,
                "callsToday": self._calls_today,
            }


alert_verification_store = AlertVerificationStore()
