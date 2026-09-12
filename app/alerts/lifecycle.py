"""Event lifecycle state machine for runtime alert consumers (M11-T06).

The vector evaluator is intentionally stateless from the caller's perspective;
this module provides the small mutable coordinator used by streaming runtimes.
It keeps immutable fact fields from the confirmation moment and only mutates
lifecycle/notification fields afterwards.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
import hashlib


SEVERITY_ORDER = {"MINOR": 1, "MAJOR": 2, "CRITICAL": 3}


@dataclass
class EventRecord:
    event_id: str
    rule_id: str
    rule_version: int
    source_id: str
    subject_key: str
    operator: str
    severity: str
    notify_severity: str
    started_at_us: int
    confirmed_at_us: int | None = None
    ended_at_us: int | None = None
    state: str = "CANDIDATE"
    suppressed_count: int = 0
    measured_value: float | int | None = None
    effective_thresholds: dict[str, Any] = field(default_factory=dict)
    escalated_at_us: int | None = None
    disposition: dict[str, Any] = field(default_factory=lambda: {"status": "OPEN", "actor": None, "actedAtUs": None})
    evidence: dict[str, Any] = field(default_factory=dict)
    detection_results: Any = None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "eventId": self.event_id, "ruleId": self.rule_id,
            "ruleVersion": self.rule_version, "sourceId": self.source_id,
            "subjectKey": self.subject_key, "operator": self.operator,
            "severity": self.severity, "notifySeverity": self.notify_severity,
            "escalatedAtUs": self.escalated_at_us, "startedAtUs": self.started_at_us,
            "confirmedAtUs": self.confirmed_at_us, "endedAtUs": self.ended_at_us,
            "state": self.state, "suppressedCount": self.suppressed_count,
            "measuredValue": self.measured_value,
            "effectiveThresholds": dict(self.effective_thresholds),
            "disposition": dict(self.disposition),
            "evidence": dict(self.evidence),
            "detectionResults": self.detection_results,
        }


class EventStateMachine:
    """Deterministic candidate/confirmation/cooldown coordinator.

    ``on_hit`` accepts a rule mapping and a hit mapping.  A hit is considered a
    candidate until ``confirmed`` is true (or ``candidate_frames`` reaches the
    rule's ``minConsecutiveFrames``).  Methods return the affected snapshot,
    or ``None`` when a hit was suppressed/no state changed.
    """

    def __init__(self) -> None:
        self._events: dict[tuple[str, str, str, str], EventRecord] = {}
        self._candidates: dict[tuple[str, str, str], EventRecord] = {}
        self._last_timestamp: dict[str, int] = {}

    @staticmethod
    def _id(rule_id: str, source: str, subject: str, ts: int, severity: str) -> str:
        raw = f"{rule_id}\0{source}\0{subject}\0{ts}\0{severity}".encode()
        return "evt-" + hashlib.sha256(raw).hexdigest()[:24]

    @staticmethod
    def _thresholds(rule: Mapping[str, Any], source: str) -> dict[str, Any]:
        out = dict(rule.get("thresholds") or {})
        out.update(((rule.get("scope") or {}).get("thresholdOverrides") or {}).get(source) or {})
        return out

    def _check_time(self, source: str, timestamp_us: int) -> None:
        previous = self._last_timestamp.get(source)
        if previous is not None and timestamp_us < previous:
            raise ValueError(f"capturedAtUs must be monotonic for source {source!r}")
        self._last_timestamp[source] = timestamp_us

    def on_hit(self, rule: Mapping[str, Any], hit: Mapping[str, Any], *, confirmed: bool | None = None,
               candidate_frames: int = 1) -> EventRecord | None:
        source = str(hit.get("sourceId", hit.get("source_id", "")))
        subject = str(hit.get("subjectKey", hit.get("subject_key", "")))
        ts = int(hit.get("capturedAtUs", hit.get("timestampUs", hit.get("timestamp_us", 0))))
        if not source or not subject:
            raise ValueError("sourceId and subjectKey are required")
        self._check_time(source, ts)
        rid = str(rule.get("ruleId", "")); op = str(rule.get("operator", "" )).upper()
        thresholds = self._thresholds(rule, source)
        if isinstance(rule.get("escalation"), Mapping):
            esc = rule["escalation"]
            thresholds.setdefault("escalateAfterMs", esc.get("escalateAfterMs"))
            thresholds.setdefault("escalateToSeverity", esc.get("toSeverity"))
        key = (rid, source, subject)
        min_frames = int(thresholds.get("minConsecutiveFrames", 1))
        if confirmed is None:
            confirmed = candidate_frames >= min_frames
        severity = str(hit.get("severity") or "MINOR").upper()
        value = hit.get("measuredValue", hit.get("measured_value"))
        if not confirmed:
            candidate = self._candidates.get(key)
            if candidate is None:
                candidate = EventRecord(self._id(rid, source, subject, ts, severity), rid,
                    int(rule.get("ruleVersion", 1)), source, subject, op, severity, severity, ts,
                    measured_value=value, effective_thresholds=thresholds)
                self._candidates[key] = candidate
            return candidate

        candidate = self._candidates.pop(key, None)
        cooldown_us = int(thresholds.get("cooldownMs", 0)) * 1000
        existing_same = self._events.get((rid, source, subject, severity))
        highest = max((SEVERITY_ORDER.get(e.severity, 0) for e in self._events.values()
                       if e.rule_id == rid and e.source_id == source and e.subject_key == subject), default=0)
        upgrade = SEVERITY_ORDER.get(severity, 0) > highest
        if existing_same and cooldown_us and not upgrade and ts - int(existing_same.confirmed_at_us or 0) < cooldown_us:
            existing_same.suppressed_count += 1
            existing_same.state = "COOLDOWN"
            return existing_same
        started = candidate.started_at_us if candidate else ts
        event = EventRecord(self._id(rid, source, subject, ts, severity), rid,
            int(rule.get("ruleVersion", 1)), source, subject, op, severity, severity, started,
            confirmed_at_us=ts, state="CONFIRMED", measured_value=value,
            effective_thresholds=thresholds)
        self._events[(rid, source, subject, severity)] = event
        return event

    def on_condition_lost(self, rule_id: str, source_id: str, subject_key: str, timestamp_us: int) -> list[EventRecord]:
        self._check_time(source_id, timestamp_us)
        key = (rule_id, source_id, subject_key)
        candidate = self._candidates.pop(key, None)
        result: list[EventRecord] = []
        if candidate:
            candidate.state = "ENDED"; candidate.ended_at_us = timestamp_us; result.append(candidate)
        for k, event in list(self._events.items()):
            if k[:3] != key or event.state not in {"CONFIRMED", "COOLDOWN"}:
                continue
            # End time is a fact of the first condition loss; repeated empty
            # envelopes must not rewrite it or extend a cooldown window.
            if event.ended_at_us is None:
                event.ended_at_us = timestamp_us
                event.state = "COOLDOWN" if event.effective_thresholds.get("cooldownMs", 0) else "ENDED"
            result.append(event)
        return result

    def escalate_unattended(self, timestamp_us: int) -> list[EventRecord]:
        changed: list[EventRecord] = []
        for event in self._events.values():
            escalation = None
            # Escalation config is stored by callers in effective thresholds.
            after = event.effective_thresholds.get("escalateAfterMs")
            to = event.effective_thresholds.get("escalateToSeverity", event.effective_thresholds.get("toSeverity"))
            if after is None or not to or event.escalated_at_us is not None or event.disposition.get("status") != "OPEN":
                continue
            if timestamp_us - int(event.confirmed_at_us or timestamp_us) >= int(after) * 1000 and SEVERITY_ORDER.get(str(to), 0) > SEVERITY_ORDER.get(event.notify_severity, 0):
                event.notify_severity = str(to); event.escalated_at_us = timestamp_us; changed.append(event)
        return changed

    def acknowledge(self, event_id: str, actor: str, timestamp_us: int, *, false_positive: bool = False) -> EventRecord:
        """Record disposition and stop unattended escalation for an event."""
        for event in self._events.values():
            if event.event_id == event_id:
                self._check_time(event.source_id, timestamp_us)
                status = "FALSE_POSITIVE" if false_positive else "ACKNOWLEDGED"
                action = {
                    "status": status,
                    "actor": actor, "actedAtUs": timestamp_us,
                }
                history = list((event.disposition or {}).get("history") or [])
                history.append(dict(action))
                event.disposition = {
                    **action, "history": history,
                }
                if false_positive:
                    event.state = "ENDED"
                    if event.ended_at_us is None:
                        event.ended_at_us = timestamp_us
                return event
        raise KeyError(event_id)

    def snapshot(self) -> list[dict[str, Any]]:
        return [e.to_mapping() for e in self._events.values()]

    def reset(self) -> None:
        self._events.clear(); self._candidates.clear(); self._last_timestamp.clear()
