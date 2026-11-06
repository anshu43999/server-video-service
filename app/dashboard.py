"""Build real management-dashboard statistics from persisted business data."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Iterable

from sqlalchemy import select

from .alerts.disposition import AlertDispositionStore
from .database import (
    AlertEventRecord,
    AlertVerificationConfigRecord,
    AlertVerificationRecord,
    DEFAULT_PROJECT_ID,
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
    value = str(value or "").strip().upper()
    return {"NORMAL": "MINOR", "IMPORTANT": "MAJOR", "URGENT": "CRITICAL"}.get(value, value)


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

    def __init__(self, database: DatabaseManager | None, event_store: AlertDispositionStore, verification_store=None) -> None:
        self.database = database
        self.event_store = event_store
        self.verification_store = verification_store

    def _load_events(self, start: datetime, end: datetime, project_id: str) -> tuple[Iterable[dict[str, Any]], str]:
        if self.database is not None:
            def rows():
                with self.database.session() as session:
                    keys = ('displayName','label','ruleId','origin','notifySeverity','severity','confirmedAtUs','startedAtUs','disposition')
                    query = select(*(AlertEventRecord.payload[k].label(k) for k in keys), AlertEventRecord.event_id,
                                   AlertEventRecord.disposition_status, AlertEventRecord.created_at).where(
                        AlertEventRecord.project_id == project_id,
                        AlertEventRecord.created_at >= start, AlertEventRecord.created_at <= end
                    ).execution_options(yield_per=500)
                    for row in session.execute(query):
                        item = {k: row._mapping[k] for k in keys if row._mapping[k] is not None}
                        item.setdefault("eventId", row.event_id)
                        item.setdefault("disposition", {"status": row.disposition_status})
                        created_at = row.created_at
                        if created_at.tzinfo is None:
                            created_at = created_at.replace(tzinfo=timezone.utc)
                        item["_dashboard_created_at"] = created_at
                        yield item
            return rows(), self.database.backend

        now = datetime.now(timezone.utc)
        events = []
        for event in self.event_store.list(project_id=project_id):
            event_time = _event_time(event)
            if event_time is not None and start <= event_time <= min(now, end):
                item = dict(event)
                item["_dashboard_created_at"] = event_time
                events.append(item)
        events.sort(key=lambda item: item["_dashboard_created_at"])
        return events, "memory"

    def _load_verifications(self, start: datetime, project_id: str) -> tuple[Iterable[dict[str, Any]], dict[str, Any]]:
        if self.database is None:
            if self.verification_store is None:
                return [], {}
            return self.verification_store.statistics(project_id, int(start.timestamp() * 1_000_000))
        with self.database.session() as session:
            config = session.get(AlertVerificationConfigRecord, (project_id, "default"))
            payload = dict(config.payload or {}) if config else {}
        def rows():
            with self.database.session() as session:
                query = select(AlertVerificationRecord.payload).where(
                    AlertVerificationRecord.project_id == project_id,
                    AlertVerificationRecord.updated_at >= start
                ).execution_options(yield_per=500)
                for row in session.execute(query):
                    yield dict(row[0])
        return rows(), payload

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

    def build(self, range_key: str, streams: Mapping[str, Any], system: Mapping[str, Any],
              project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
        if range_key not in RANGE_DAYS:
            raise ValueError(f"unsupported dashboard range: {range_key}")
        end = datetime.now(timezone.utc)
        local_end = end.astimezone()
        local_start = local_end.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=RANGE_DAYS[range_key] - 1
        )
        start = local_start.astimezone(timezone.utc)
        trend_end = (local_end.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).astimezone(timezone.utc)
        events, source = self._load_events(start, end, project_id)
        verifications, verification_config = self._load_verifications(start, project_id)

        dispositions, severity_counts, severity_handled, category_counts = Counter(), Counter(), Counter(), Counter()
        source_groups: dict[str, Counter] = {}
        total, severe, response_count, response_sum = 0, 0, 0, 0.0
        trend = self._trend([], start, trend_end, range_key)
        width = (trend_end - start).total_seconds() / len(trend)
        for event in events:
            total += 1
            status = str((event.get("disposition") or {}).get("status") or "OPEN").upper()
            dispositions[status] += 1
            origin = str(event.get("origin") or "UNKNOWN").upper()
            group = source_groups.setdefault(origin, Counter())
            group["total"] += 1
            group["open" if status == "OPEN" else "handled"] += 1
            severity = _severity_key(event.get("notifySeverity") or event.get("severity")) or "MINOR"
            severity_counts[severity] += 1
            if status in {"ACKNOWLEDGED", "FALSE_POSITIVE", "CLOSED"}:
                severity_handled[severity] += 1
            is_severe = severity in {"CRITICAL", "MAJOR", "严重", "重大"}
            severe += int(is_severe)
            response = _response_minutes(event)
            if response is not None:
                response_count += 1
                response_sum += response
            category_counts[_category(event)] += 1
            index = int((event["_dashboard_created_at"] - start).total_seconds() / width) if width else 0
            if 0 <= index < len(trend):
                trend[index]["count"] += 1
                trend[index]["severe"] += int(is_severe)
        handled = sum(dispositions.get(status, 0) for status in ("ACKNOWLEDGED", "FALSE_POSITIVE", "CLOSED"))
        category_total = total or 1

        stream_items = [stream for stream in streams.values()
                        if getattr(stream, "project_id", DEFAULT_PROJECT_ID) == project_id]
        online = sum(bool(getattr(stream, "frames_received", 0)) for stream in stream_items)
        errors = sum(bool(getattr(stream, "last_error", None) or getattr(stream, "alert_error", None)) for stream in stream_items)
        waiting = max(0, len(stream_items) - online - errors)

        verification_limit = int(verification_config.get("dailyLimit") or 0)
        if range_key != "today":
            verification_limit *= RANGE_DAYS[range_key]
        conclusions = Counter()
        failures = Counter()
        verification_count = 0
        for result in verifications:
            # New rows count dispatches and unresolved reservations, never
            # rejected requests. Legacy rows retain their historical meaning.
            if 'attempts' in result:
                verification_count += sum(
                    int(attempt.get('requestedAtUs') or 0) >= int(start.timestamp() * 1_000_000)
                    for attempt in result['attempts']
                )
            else:
                verification_count += 1
            verdict = str(result.get("verdict") or "").lower()
            if verdict in {"confirmed", "false_positive", "uncertain"}:
                conclusions[verdict] += 1
            status = str(result.get("failureKind") or "").upper()
            if status:
                failures[status] += 1

        return {
            "projectId": project_id,
            "range": range_key,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "generatedAt": end.isoformat(),
            "dataSource": source,
            "summary": {
                "totalEvents": total,
                "severeAlerts": severe,
                "handledEvents": handled,
                "resolutionRate": round(handled / total * 100, 1) if total else 0,
                "averageResponseMinutes": round(response_sum / response_count, 1) if response_count else None,
            },
            "dispositions": dict(dispositions),
            "sources": {
                origin: {
                    "totalEvents": counts["total"],
                    "openEvents": counts["open"],
                    "handledEvents": counts["handled"],
                    "resolutionRate": round(counts["handled"] / counts["total"] * 100, 1) if counts["total"] else 0,
                }
                for origin, counts in sorted(source_groups.items())
            },
            "severity": {"total": dict(severity_counts), "handled": dict(severity_handled)},
            "trend": trend,
            "categories": [
                {"label": label, "count": count, "percent": round(count / category_total * 100, 1)}
                for label, count in category_counts.most_common(8)
            ],
            "streams": {"total": len(stream_items), "online": online, "waiting": waiting, "errors": errors},
            "system": dict(system),
            "verification": {
                "used": verification_count,
                "limit": verification_limit,
                "conclusions": dict(conclusions),
                "failures": dict(failures),
            },
        }
