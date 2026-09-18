"""Build real management-dashboard statistics from persisted business data."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy import select

from .alerts.disposition import AlertDispositionStore
from .database import (
    AlertEventRecord,
    AlertVerificationConfigRecord,
    AlertVerificationRecord,
    DatabaseManager,
)


RANGE_DAYS = {"today": 1, "7d": 7, "30d": 30}


def _event_time(event: Mapping[str, Any]) -> datetime | None:
    value = event.get("confirmedAtUs") or event.get("startedAtUs")
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1_000_000, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _severity_key(value: Any) -> str:
    return str(value or "").strip().upper()


def _category(event: Mapping[str, Any]) -> str:
    return str(
        event.get("displayName")
        or event.get("label")
        or event.get("ruleId")
        or "未分类"
    ).strip() or "未分类"


def _response_minutes(event: Mapping[str, Any]) -> float | None:
    started = event.get("confirmedAtUs") or event.get("startedAtUs")
    disposition = event.get("disposition") or {}
    acted = disposition.get("actedAtUs")
    if acted is None or started is None:
        return None
    try:
        value = (int(acted) - int(started)) / 60_000_000
    except (TypeError, ValueError):
        return None
    return round(value, 2) if value >= 0 else None


class DashboardStatsService:
    """Query persisted event data and combine it with live process telemetry."""

    def __init__(self, database: DatabaseManager | None, event_store: AlertDispositionStore) -> None:
        self.database = database
        self.event_store = event_store

    def _load_events(self, start: datetime, end: datetime) -> tuple[list[dict[str, Any]], str]:
        if self.database is not None:
            with self.database.session() as session:
                rows = session.scalars(
                    select(AlertEventRecord)
                    .where(AlertEventRecord.created_at >= start, AlertEventRecord.created_at <= end)
                    .order_by(AlertEventRecord.created_at.asc())
                ).all()
                events: list[dict[str, Any]] = []
                for row in rows:
                    item = dict(row.payload or {})
                    item.setdefault("eventId", row.event_id)
                    item.setdefault("disposition", {"status": row.disposition_status})
                    created_at = row.created_at
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    item["_dashboard_created_at"] = created_at
                    events.append(item)
                return events, self.database.backend

        now = datetime.now(timezone.utc)
        events = []
        for event in self.event_store.list():
            event_time = _event_time(event)
            if event_time is not None and start <= event_time <= min(now, end):
                item = dict(event)
                item["_dashboard_created_at"] = event_time
                events.append(item)
        events.sort(key=lambda item: item["_dashboard_created_at"])
        return events, "memory"

    def _load_verifications(self, start: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if self.database is None:
            return [], {}
        with self.database.session() as session:
            rows = session.scalars(
                select(AlertVerificationRecord)
                .where(AlertVerificationRecord.created_at >= start)
                .order_by(AlertVerificationRecord.created_at.asc())
            ).all()
            config = session.get(AlertVerificationConfigRecord, "default")
            payload = dict(config.payload or {}) if config else {}
            return [dict(row.payload or {}) for row in rows], payload

    @staticmethod
    def _trend(events: list[dict[str, Any]], start: datetime, end: datetime, range_key: str) -> list[dict[str, Any]]:
        bucket_count = {"today": 12, "7d": 7, "30d": 6}[range_key]
        width = (end - start).total_seconds() / bucket_count
        buckets = [{"label": "", "count": 0, "severe": 0} for _ in range(bucket_count)]
        for index, bucket in enumerate(buckets):
            bucket_start = start + timedelta(seconds=width * index)
            if range_key == "today":
                bucket["label"] = bucket_start.astimezone().strftime("%H:%M")
            else:
                bucket["label"] = bucket_start.astimezone().strftime("%m-%d")
        for event in events:
            value = event.get("_dashboard_created_at")
            if not isinstance(value, datetime):
                continue
            index = int((value - start).total_seconds() / width) if width else 0
            if 0 <= index < bucket_count:
                buckets[index]["count"] += 1
                if _severity_key(event.get("notifySeverity") or event.get("severity")) in {"CRITICAL", "MAJOR", "严重", "重大"}:
                    buckets[index]["severe"] += 1
        return buckets

    def build(self, range_key: str, streams: Mapping[str, Any], system: Mapping[str, Any]) -> dict[str, Any]:
        if range_key not in RANGE_DAYS:
            raise ValueError(f"unsupported dashboard range: {range_key}")
        end = datetime.now(timezone.utc)
        local_end = end.astimezone()
        local_start = local_end.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=RANGE_DAYS[range_key] - 1
        )
        start = local_start.astimezone(timezone.utc)
        trend_end = (local_end.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).astimezone(timezone.utc)
        events, source = self._load_events(start, end)
        verifications, verification_config = self._load_verifications(start)

        dispositions = Counter(str((event.get("disposition") or {}).get("status") or "OPEN").upper() for event in events)
        severity_counts: Counter[str] = Counter()
        severity_handled: Counter[str] = Counter()
        for event in events:
            severity = _severity_key(event.get("notifySeverity") or event.get("severity")) or "MINOR"
            severity_counts[severity] += 1
            status = str((event.get("disposition") or {}).get("status") or "OPEN").upper()
            if status in {"ACKNOWLEDGED", "FALSE_POSITIVE", "CLOSED"}:
                severity_handled[severity] += 1
        handled = sum(dispositions.get(status, 0) for status in ("ACKNOWLEDGED", "FALSE_POSITIVE", "CLOSED"))
        severe = sum(
            _severity_key(event.get("notifySeverity") or event.get("severity")) in {"CRITICAL", "MAJOR", "严重", "重大"}
            for event in events
        )
        response_times = [value for event in events if (value := _response_minutes(event)) is not None]
        category_counts = Counter(_category(event) for event in events)
        category_total = sum(category_counts.values()) or 1

        stream_items = list(streams.values())
        online = sum(bool(getattr(stream, "frames_received", 0) or getattr(stream, "publisher", None) and stream.publisher.metrics().get("publish_state") == "connected") for stream in stream_items)
        errors = sum(bool(getattr(stream, "last_error", None) or getattr(stream, "alert_error", None)) for stream in stream_items)
        waiting = max(0, len(stream_items) - online - errors)

        verification_limit = int(verification_config.get("dailyLimit") or 0)
        if range_key != "today":
            verification_limit *= RANGE_DAYS[range_key]
        conclusions = Counter()
        failures = Counter()
        for result in verifications:
            verdict = str(result.get("verdict") or "").lower()
            if verdict in {"confirmed", "false_positive", "uncertain"}:
                conclusions[verdict] += 1
            status = str(result.get("failureKind") or "").upper()
            if status:
                failures[status] += 1

        return {
            "range": range_key,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "generatedAt": end.isoformat(),
            "dataSource": source,
            "summary": {
                "totalEvents": len(events),
                "severeAlerts": severe,
                "handledEvents": handled,
                "resolutionRate": round(handled / len(events) * 100, 1) if events else 0,
                "averageResponseMinutes": round(sum(response_times) / len(response_times), 1) if response_times else None,
            },
            "dispositions": dict(dispositions),
            "severity": {"total": dict(severity_counts), "handled": dict(severity_handled)},
            "trend": self._trend(events, start, trend_end, range_key),
            "categories": [
                {"label": label, "count": count, "percent": round(count / category_total * 100, 1)}
                for label, count in category_counts.most_common(8)
            ],
            "streams": {"total": len(stream_items), "online": online, "waiting": waiting, "errors": errors},
            "system": dict(system),
            "verification": {
                "used": len(verifications),
                "limit": verification_limit,
                "conclusions": dict(conclusions),
                "failures": dict(failures),
            },
        }
