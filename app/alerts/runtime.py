"""Runtime bridge from server detections to durable alert events."""
from __future__ import annotations

import hashlib
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

import cv2


class ServerAlertRuntime:
    """Evaluate model camera defaults and persist only confirmed event state."""

    def __init__(self, model_provider: Callable[[str], dict[str, Any]], parameter_store,
                 event_store, delivery_service, evidence_root: Path) -> None:
        self.model_provider = model_provider
        self.parameter_store = parameter_store
        self.event_store = event_store
        self.delivery_service = delivery_service
        self.evidence_root = evidence_root
        self._lock = threading.RLock()
        self._candidates: dict[str, dict[str, int]] = {}
        self._active: dict[str, str] = {}
        self._cooldown_at: dict[str, int] = {}
        self._hydrated_sources: set[str] = set()

    @staticmethod
    def _runtime_key(model_id: str, source_id: str, raw_label: str) -> str:
        identity = f"{model_id}|{source_id}|{raw_label}".encode("utf-8")
        return "runtime-" + hashlib.sha256(identity).hexdigest()[:32]

    @staticmethod
    def _event_id(runtime_key: str, started_at_us: int) -> str:
        digest = hashlib.sha256(f"{runtime_key}\0{started_at_us}".encode("utf-8")).hexdigest()
        return "evt-server-" + digest[:24]

    def _hydrate(self, source_id: str) -> None:
        if source_id in self._hydrated_sources:
            return
        for event in self.event_store.list():
            if event.get("origin") not in {"server", "SERVER_STREAM"} or event.get("sourceId") != source_id:
                continue
            key = event.get("runtimeKey")
            if not key:
                continue
            ended = event.get("endedAtUs") or event.get("state") == "ENDED"
            if ended:
                self._cooldown_at[key] = max(self._cooldown_at.get(key, 0), int(event.get("endedAtUs") or 0))
            elif (event.get("disposition") or {}).get("status", "OPEN") == "OPEN":
                self._active[key] = event["eventId"]
        self._hydrated_sources.add(source_id)

    def _save_evidence(self, event_id: str, frame: Any) -> str | None:
        if frame is None:
            return None
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            return None
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        target = self.evidence_root / f"{event_id}.jpg"
        temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_bytes(encoded.tobytes())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return f"/api/alerts/{event_id}/evidence"

    def evidence_path(self, event_id: str) -> Path | None:
        if not event_id.startswith("evt-server-"):
            return None
        path = self.evidence_root / f"{event_id}.jpg"
        return path if path.is_file() else None

    def process(self, *, source_id: str, captured_at_us: int, result: Any,
                frame: Any = None) -> list[dict[str, Any]]:
        model_id = str(getattr(result, "model_id", "") or "")
        if not model_id:
            return []
        try:
            model = self.model_provider(model_id)
            profile = self.parameter_store.get(model, "server")
        except (KeyError, ValueError):
            return []
        detections = [item.to_alert_detection() for item in getattr(result, "detections", ())]
        emitted: list[dict[str, Any]] = []
        with self._lock:
            self._hydrate(source_id)
            for rule in profile.get("alertRules", []):
                if not rule.get("enabled"):
                    continue
                raw_label = str(rule.get("rawLabel") or "")
                camera = rule.get("camera") or {}
                minimum = float(camera.get("minimumConfidence", 1.0))
                matches = [item for item in detections
                           if item.get("label") == raw_label and float(item.get("confidence", 0)) >= minimum]
                key = self._runtime_key(model_id, source_id, raw_label)
                if not matches:
                    self._candidates.pop(key, None)
                    active_id = self._active.pop(key, None)
                    if active_id:
                        try:
                            current = self.event_store.get(active_id)
                        except KeyError:
                            current = None
                        if current:
                            current.update(state="ENDED", endedAtUs=captured_at_us, lastSeenAtUs=captured_at_us)
                            self.event_store.register(current)
                            self._cooldown_at[key] = captured_at_us
                    continue
                candidate = self._candidates.setdefault(key, {"frames": 0, "startedAtUs": captured_at_us})
                candidate["frames"] += 1
                if key in self._active:
                    continue
                required_frames = max(1, int(camera.get("minimumConsecutiveFrames", 1)))
                required_dwell_us = max(0, int(camera.get("minimumDwellTimeMs", 0))) * 1000
                if candidate["frames"] < required_frames or captured_at_us - candidate["startedAtUs"] < required_dwell_us:
                    continue
                cooldown_us = max(0, int(camera.get("cooldownMs", 0))) * 1000
                last_cooldown = self._cooldown_at.get(key)
                if last_cooldown is not None and captured_at_us - last_cooldown < cooldown_us:
                    # A suppressed episode must not reopen the ended event.
                    self._candidates.pop(key, None)
                    continue
                event_id = self._event_id(key, candidate["startedAtUs"])
                snapshot_uri = self._save_evidence(event_id, frame)
                event = {
                    "eventId": event_id,
                    "origin": "SERVER_STREAM",
                    "streamId": source_id,
                    "runtimeKey": key,
                    "ruleId": str(rule.get("eventCode") or raw_label),
                    "ruleVersion": int(profile.get("revision", 0)),
                    "sourceId": source_id,
                    "subjectKey": f"frame:{source_id}",
                    "label": raw_label,
                    "displayName": rule.get("displayName") or raw_label,
                    "operator": "PRESENCE",
                    "severity": rule.get("severity") or "MAJOR",
                    "notifySeverity": rule.get("severity") or "MAJOR",
                    "startedAtUs": candidate["startedAtUs"],
                    "confirmedAtUs": captured_at_us,
                    "lastSeenAtUs": captured_at_us,
                    "endedAtUs": None,
                    "state": "CONFIRMED",
                    "effectiveThresholds": {
                        "minimumConfidence": minimum,
                        "minimumConsecutiveFrames": required_frames,
                        "minimumDwellTimeMs": int(camera.get("minimumDwellTimeMs", 0)),
                        "cooldownMs": int(camera.get("cooldownMs", 0)),
                    },
                    "detectionResults": matches,
                    "model": {"modelId": model_id, "version": model.get("version")},
                    "evidence": {"snapshotUri": snapshot_uri, "capturedAtUs": captured_at_us},
                    "disposition": {"status": "OPEN", "actor": None, "actedAtUs": None},
                }
                registered = self.event_store.register(event)
                self._active[key] = event_id
                emitted.append(registered)
                try:
                    self.delivery_service.dispatch(registered)
                except ValueError:
                    pass
        return emitted

    def reset_runtime_state(self) -> None:
        with self._lock:
            self._candidates.clear()
            self._active.clear()
            self._cooldown_at.clear()
            self._hydrated_sources.clear()
