from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select

from .database import DatabaseManager, StreamConfigRecord


class StreamConfigConflict(Exception):
    pass


class StreamConfigNotFound(Exception):
    pass


def redact_source_url(source: str | int | None) -> str | None:
    """Return a useful source identity without credentials or query secrets."""
    if source is None:
        return None
    value = str(source)
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "<redacted-source>" if "@" in value else value
    if parsed.scheme.lower() not in {"rtsp", "rtsps"}:
        return value
    try:
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return "<redacted-rtsp-source>"
    if not hostname:
        return "<redacted-rtsp-source>"
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = f"{hostname}:{port}" if port else hostname
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def infer_source_type(source: str | int | None) -> str:
    if source is None:
        return "websocket"
    if isinstance(source, int) or (isinstance(source, str) and source.isdigit()):
        return "camera"
    scheme = urlsplit(str(source)).scheme.lower()
    if scheme in {"rtsp", "rtsps"}:
        return "rtsp"
    if scheme in {"http", "https"}:
        return "http"
    return "file"


@dataclass(frozen=True)
class StreamConfiguration:
    stream_id: str
    display_name: str
    source_type: str
    source_url: str | None
    model_id: str | None
    yolo_enabled: bool
    confidence: float
    max_fps: float
    overlay_enabled: bool
    enabled: bool = True
    revision: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def public(self) -> dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "display_name": self.display_name,
            "source_type": self.source_type,
            "source_url": redact_source_url(self.source_url),
            "model_id": self.model_id,
            "yolo_enabled": self.yolo_enabled,
            "confidence": self.confidence,
            "max_fps": self.max_fps,
            "overlay_enabled": self.overlay_enabled,
            "enabled": self.enabled,
            "revision": self.revision,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def runtime_source(self) -> str | int | None:
        if self.source_url is None:
            return None
        if self.source_type == "camera" and self.source_url.isdigit():
            return int(self.source_url)
        return self.source_url


class StreamConfigStore:
    """Persistent control-plane configuration with an explicit memory fallback."""

    def __init__(self, database_manager: DatabaseManager | None = None) -> None:
        self._database = database_manager
        self._memory: dict[str, StreamConfiguration] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _from_record(row: StreamConfigRecord) -> StreamConfiguration:
        return StreamConfiguration(
            stream_id=row.stream_id,
            display_name=row.display_name,
            source_type=row.source_type,
            source_url=row.source_url,
            model_id=row.model_id,
            yolo_enabled=row.yolo_enabled,
            confidence=row.confidence,
            max_fps=row.max_fps,
            overlay_enabled=row.overlay_enabled,
            enabled=row.enabled,
            revision=row.revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def create(self, config: StreamConfiguration) -> StreamConfiguration:
        if self._database is not None:
            with self._database.session() as session:
                if session.get(StreamConfigRecord, config.stream_id) is not None:
                    raise StreamConfigConflict(config.stream_id)
                row = StreamConfigRecord(
                    stream_id=config.stream_id,
                    display_name=config.display_name,
                    source_type=config.source_type,
                    source_url=config.source_url,
                    model_id=config.model_id,
                    yolo_enabled=config.yolo_enabled,
                    confidence=config.confidence,
                    max_fps=config.max_fps,
                    overlay_enabled=config.overlay_enabled,
                    enabled=config.enabled,
                    revision=1,
                )
                session.add(row)
                session.flush()
                session.refresh(row)
                return self._from_record(row)
        with self._lock:
            if config.stream_id in self._memory:
                raise StreamConfigConflict(config.stream_id)
            now = datetime.now(timezone.utc)
            stored = replace(config, revision=1, created_at=now, updated_at=now)
            self._memory[config.stream_id] = stored
            return stored

    def get(self, stream_id: str) -> StreamConfiguration | None:
        if self._database is not None:
            with self._database.session() as session:
                row = session.get(StreamConfigRecord, stream_id)
                return self._from_record(row) if row else None
        with self._lock:
            return self._memory.get(stream_id)

    def list(self) -> list[StreamConfiguration]:
        if self._database is not None:
            with self._database.session() as session:
                rows = session.scalars(select(StreamConfigRecord).order_by(StreamConfigRecord.stream_id)).all()
                return [self._from_record(row) for row in rows]
        with self._lock:
            return [self._memory[key] for key in sorted(self._memory)]

    def update(self, stream_id: str, **changes: Any) -> StreamConfiguration:
        allowed = {
            "display_name", "source_type", "source_url", "model_id", "yolo_enabled",
            "confidence", "max_fps", "overlay_enabled", "enabled",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported stream configuration fields: {', '.join(sorted(unknown))}")
        if self._database is not None:
            with self._database.session() as session:
                row = session.scalar(
                    select(StreamConfigRecord)
                    .where(StreamConfigRecord.stream_id == stream_id)
                    .with_for_update()
                )
                if row is None:
                    raise StreamConfigNotFound(stream_id)
                for name, value in changes.items():
                    setattr(row, name, value)
                row.revision += 1
                row.updated_at = datetime.now(timezone.utc)
                session.flush()
                session.refresh(row)
                return self._from_record(row)
        with self._lock:
            current = self._memory.get(stream_id)
            if current is None:
                raise StreamConfigNotFound(stream_id)
            stored = replace(
                current,
                **changes,
                revision=current.revision + 1,
                updated_at=datetime.now(timezone.utc),
            )
            self._memory[stream_id] = stored
            return stored

    def delete(self, stream_id: str) -> bool:
        if self._database is not None:
            with self._database.session() as session:
                row = session.get(StreamConfigRecord, stream_id)
                if row is None:
                    return False
                session.delete(row)
                return True
        with self._lock:
            return self._memory.pop(stream_id, None) is not None
