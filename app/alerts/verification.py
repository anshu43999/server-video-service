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
    DEFAULT_PROJECT_ID,
    DatabaseManager,
)
from ..project_business import audit_change, lock_project
from .verification_provider import VerificationProvider
from .verification_attempts import VerificationAttempts


class VerificationConfigConflict(ValueError):
    pass


class AlertVerificationStore(VerificationAttempts):
    def __init__(self, daily_limit: int = 100, database_manager: DatabaseManager | None = None,
                 provider: VerificationProvider | None = None) -> None:
        self._lock = threading.RLock()
        self._results: dict[tuple[str, str], dict[str, Any]] = {}
        self._calls_today = 0
        self._revision = 0
        self._day = self._day_key()
        self.daily_limit = max(0, int(daily_limit))
        self.enabled = False
        self.image_egress_authorized = False
        self.model_id = ""
        self.provider_configured = False
        self._database = database_manager
        self._provider = provider
        self._active_project = DEFAULT_PROJECT_ID
        self._project_states: dict[str, dict[str, Any]] = {}

    def _state_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "image_egress_authorized": self.image_egress_authorized,
            "daily_limit": self.daily_limit,
            "model_id": self.model_id,
            "provider_configured": self.provider_configured,
            "day": self._day,
            "calls_today": self._calls_today,
            "revision": self._revision,
        }

    def _switch_project(self, project_id: str) -> None:
        if project_id == self._active_project:
            return
        self._project_states[self._active_project] = self._state_payload()
        state = self._project_states.get(project_id, {
            "enabled": False,
            "image_egress_authorized": False,
            "daily_limit": 100,
            "model_id": "",
            "provider_configured": False,
            "day": self._day_key(),
            "calls_today": 0,
            "revision": 0,
        })
        self._restore_state(state)
        self._active_project = project_id

    def _restore_state(self, state) -> None:
        self.enabled = bool(state["enabled"])
        self.image_egress_authorized = bool(state["image_egress_authorized"])
        self.daily_limit = int(state["daily_limit"])
        self.model_id = str(state["model_id"])
        self.provider_configured = bool(state["provider_configured"])
        self._day = int(state["day"])
        self._calls_today = int(state["calls_today"])
        self._revision = int(state["revision"])

    @property
    def database_manager(self) -> DatabaseManager | None:
        return self._database

    def configure_database(self, database_manager: DatabaseManager | None) -> None:
        with self._lock:
            self._database = database_manager

    def configure_provider(self, provider: VerificationProvider | None) -> None:
        """Replace the process provider; credentials never enter project state."""
        with self._lock:
            self._provider = provider

    @property
    def provider_available(self) -> bool:
        with self._lock:
            return self._provider is not None

    def _config_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "imageEgressAuthorized": self.image_egress_authorized,
            "dailyLimit": self.daily_limit,
            "modelId": self.model_id,
            "providerConfigured": self.provider_configured,
            "day": self._day,
            "revision": self._revision,
        }

    def _load_config(self, session, project_id: str) -> None:
        row = session.get(AlertVerificationConfigRecord, (project_id, "default"))
        if row is None:
            return
        payload = dict(row.payload or {})
        self._revision = int(payload.get("revision", 0))
        self.enabled = bool(payload.get("enabled", self.enabled))
        self.image_egress_authorized = bool(payload.get("imageEgressAuthorized", self.image_egress_authorized))
        self.daily_limit = max(0, int(payload.get("dailyLimit", row.calls_day)))
        self.model_id = str(payload.get("modelId") or "")
        self.provider_configured = bool(payload.get("providerConfigured", self.provider_configured))
        stored_day = payload.get("day")
        self._day = int(stored_day) if stored_day is not None else self._day_key()
        self._calls_today = int(row.calls_today or 0)
        self._rollover()

    def _save_config(self, session, project_id: str) -> None:
        row = session.get(AlertVerificationConfigRecord, (project_id, "default"))
        payload = self._config_payload()
        if row is None:
            session.add(AlertVerificationConfigRecord(
                project_id=project_id,
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

    def get(self, event_id: str, project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any] | None:
        with self._lock:
            if self._database is not None:
                with self._database.session() as session:
                    lock_project(session, project_id, enforce_lifecycle=False)
                    row = session.get(AlertVerificationRecord, (project_id, event_id))
                    if row is None:
                        return None
                    result = self._expire_payload(row.payload)
                    if result != row.payload:
                        row.status, row.payload = result["status"], result
                    return self._public_result(result)
            result = self._results.get((project_id, event_id))
            if result is not None:
                result = self._expire_payload(result)
                self._results[(project_id, event_id)] = result
            return self._public_result(result) if result else None

    def reset(self, *, allow_database_delete: bool = False) -> None:
        with self._lock:
            if self._database is not None and not allow_database_delete:
                raise ValueError("database reset requires explicit allow_database_delete=True on an isolated test database")
            self._results.clear()
            self._project_states.clear()
            self._active_project = DEFAULT_PROJECT_ID
            self._calls_today = 0
            self._revision = 0
            self._day = self._day_key()
            if self._database is not None:
                with self._database.session() as session:
                    session.execute(delete(AlertVerificationRecord))
                    session.execute(delete(AlertVerificationConfigRecord))

    def configure(self, *, enabled: bool, image_egress_authorized: bool,
                  daily_limit: int, model_id: str, provider_configured: bool,
                  project_id: str = DEFAULT_PROJECT_ID, expected_revision: int | None = None,
                  context=None, request_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            self._switch_project(project_id)
            previous_state = self._state_payload()

            def update(session):
                if session is not None:
                    lock_project(session, project_id)
                    self._load_config(session, project_id)
                self._rollover()
                before = self._config_payload()
                if expected_revision is not None and expected_revision != self._revision:
                    raise VerificationConfigConflict("verification policy was changed by another operator")
                self.enabled = bool(enabled)
                self.image_egress_authorized = bool(image_egress_authorized)
                self.daily_limit = max(0, int(daily_limit))
                self.model_id = str(model_id or "").strip()
                self.provider_configured = bool(provider_configured)
                self._revision += 1
                if session is not None:
                    self._save_config(session, project_id)
                audit_change(session, context, request_id, "verification_policy.update",
                             "verification_policy", "default", before, self._config_payload())
            try:
                if self._database is not None:
                    with self._database.session() as session:
                        update(session)
                else:
                    update(None)
            except Exception:
                self._project_states[project_id] = previous_state
                self._restore_state(previous_state)
                raise
            self._project_states[project_id] = self._state_payload()
            return self.config(project_id)

    def config(self, project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
        with self._lock:
            self._switch_project(project_id)
            if self._database is not None:
                with self._database.session() as session:
                    self._load_config(session, project_id)
            self._rollover()
            self._project_states[project_id] = self._state_payload()
            return {
                "projectId": project_id,
                "revision": self._revision,
                "enabled": self.enabled,
                "imageEgressAuthorized": self.image_egress_authorized,
                "dailyLimit": self.daily_limit,
                "modelId": self.model_id,
                "providerConfigured": self.provider_configured,
                "callsToday": self._calls_today,
            }

    def statistics(self, project_id: str, start_us: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        with self._lock:
            if self._database is not None:
                with self._database.session() as session:
                    rows = session.scalars(select(AlertVerificationRecord).where(
                        AlertVerificationRecord.project_id == project_id)).all()
                    results = [self._public_result(row.payload) for row in rows
                               if int(row.payload.get("requestedAtUs", 0)) >= start_us]
            else:
                results = [self._public_result(value) for (pid, _), value in self._results.items()
                           if pid == project_id and int(value.get("requestedAtUs", 0)) >= start_us]
            return results, self.config(project_id)


alert_verification_store = AlertVerificationStore()


def result_status(verdict: str) -> str:
    return {
        "CONFIRMED": "CONFIRMED",
        "SUSPECTED_FALSE_POSITIVE": "SUSPECTED_FALSE_POSITIVE",
        "INCONCLUSIVE": "INCONCLUSIVE",
    }.get(verdict, "INCONCLUSIVE")
