"""Runtime bridge from server detections to durable alert events."""
from __future__ import annotations

import hashlib
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import cv2

from ..database import DEFAULT_PROJECT_ID


SERVER_EVENT_ID = re.compile(r"^evt-server-[a-f0-9]{24}$")


class ServerAlertRuntime:
    """Evaluate model camera defaults and persist only confirmed event state."""

    def __init__(self, model_provider: Callable[[str], dict[str, Any]], parameter_store,
                 event_store, delivery_service, evidence_root: Path, evidence_store=None,
                 profile_provider=None) -> None:
        self.model_provider = model_provider
        self.parameter_store = parameter_store
        self.event_store = event_store
        self.delivery_service = delivery_service
        self.evidence_root = evidence_root
        self.evidence_store = evidence_store
        self.profile_provider = profile_provider
        self._lock = threading.RLock()
        self._candidates: dict[str, dict[str, int]] = {}
        self._active: dict[str, str] = {}
        self._cooldown_at: dict[str, int] = {}
        self._hydrated_sources: set[str] = set()

    @staticmethod
    def _tiered_storage_enabled(store: Any) -> bool:
        return bool(store is not None and store.enabled
                    and callable(getattr(store, "store_tiered_bytes", None))
                    and callable(getattr(store, "remove_tiered", None)))

    @staticmethod
    def _runtime_key(project_id: str, model_id: str, source_id: str, raw_label: str) -> str:
        identity = f"{project_id}|{model_id}|{source_id}|{raw_label}".encode("utf-8")
        return "runtime-" + hashlib.sha256(identity).hexdigest()[:32]

    @staticmethod
    def _event_id(runtime_key: str, started_at_us: int) -> str:
        digest = hashlib.sha256(f"{runtime_key}\0{started_at_us}".encode("utf-8")).hexdigest()
        return "evt-server-" + digest[:24]

    def _hydrate(self, project_id: str, source_id: str) -> None:
        hydrated_key = f"{project_id}\0{source_id}"
        if hydrated_key in self._hydrated_sources:
            return
        for event in self.event_store.list(project_id=project_id):
            if event.get("origin") not in {"server", "SERVER_STREAM"} or event.get("sourceId") != source_id:
                continue
            key = event.get("runtimeKey")
            if not key:
                continue
            ended = event.get("endedAtUs") or event.get("state") == "ENDED"
            if ended:
                self._cooldown_at[key] = max(self._cooldown_at.get(key, 0), int(event.get("endedAtUs") or 0))
            else:
                # Human acknowledgement does not end the detected episode.
                # Restarting while it is still present must not create a new alert.
                self._active[key] = event["eventId"]
        self._hydrated_sources.add(hydrated_key)

    def _save_evidence(self, event_id: str, frame: Any,
                       project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
        if frame is None:
            return {}
        if self.evidence_store is not None and self.evidence_store.enabled:
            if not self._tiered_storage_enabled(self.evidence_store):
                raise OSError("tiered alert evidence storage is required")
            original = self._encode_jpeg(frame, max_edge=None, max_bytes=5 * 1024 * 1024)
            thumbnail = self._encode_jpeg(frame, max_edge=320, max_bytes=128 * 1024)
            uploaded_at = datetime.now(timezone.utc).isoformat()
            references: list[dict[str, Any]] = []
            try:
                for evidence_type, content in (("thumbnail", thumbnail), ("original", original)):
                    digest = hashlib.sha256(content).hexdigest()
                    object_storage = self.evidence_store.store_tiered_bytes(
                        project_id, event_id, evidence_type, 1, content, "image/jpeg", digest
                    )
                    references.append({
                        "type": evidence_type,
                        "contentVersion": 1,
                        "sha256": digest,
                        "contentType": "image/jpeg",
                        "byteLength": len(content),
                        "objectStorage": object_storage,
                        "uploadedAt": uploaded_at,
                        "retentionState": "ACTIVE",
                        "uri": (f"/aiyoloapi/projects/{project_id}/alerts/{event_id}/"
                                f"evidence/{evidence_type}/1"),
                    })
            except Exception:
                # A SERVER_STREAM fact is never persisted with half of its two-level evidence.
                for reference in references:
                    try:
                        self.evidence_store.remove_tiered(reference["objectStorage"])
                    except Exception:
                        pass
                raise
            return {
                "snapshotUri": f"/aiyoloapi/projects/{project_id}/alerts/{event_id}/evidence",
                "thumbnail": {"1": references[0]},
                "original": {"1": references[1]},
            }
        content = self._encode_jpeg(frame, max_edge=None, max_bytes=5 * 1024 * 1024)
        project_partition = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
        project_root = self.evidence_root / "projects" / project_partition
        project_root.mkdir(parents=True, exist_ok=True)
        target = project_root / f"{event_id}.jpg"
        temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "snapshotUri": f"/aiyoloapi/projects/{project_id}/alerts/{event_id}/evidence"
        }

    @staticmethod
    def _encode_jpeg(frame: Any, *, max_edge: int | None, max_bytes: int) -> bytes:
        """Encode one immutable evidence frame within the tier's byte contract."""
        current = frame
        edge = max(frame.shape[:2])
        if max_edge is not None and edge > max_edge:
            scale = max_edge / edge
            current = cv2.resize(frame, (max(1, round(frame.shape[1] * scale)),
                                         max(1, round(frame.shape[0] * scale))),
                                 interpolation=cv2.INTER_AREA)
        for _ in range(8):
            for quality in (88, 80, 70, 60, 50, 40, 30):
                ok, encoded = cv2.imencode(".jpg", current, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
                if ok and len(encoded) <= max_bytes:
                    return encoded.tobytes()
            if min(current.shape[:2]) <= 64:
                break
            current = cv2.resize(current, (max(1, round(current.shape[1] * .8)),
                                           max(1, round(current.shape[0] * .8))),
                                 interpolation=cv2.INTER_AREA)
        raise OSError("alert evidence image exceeds its tier limit")

    def evidence_path(self, event_id: str,
                      project_id: str = DEFAULT_PROJECT_ID) -> Path | None:
        if not SERVER_EVENT_ID.fullmatch(event_id):
            return None
        project_partition = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
        path = self.evidence_root / "projects" / project_partition / f"{event_id}.jpg"
        return path if path.is_file() else None

    def process(self, *, source_id: str, captured_at_us: int, result: Any,
                frame: Any = None, project_id: str = DEFAULT_PROJECT_ID,
                evidence_baked_in: bool = False) -> list[dict[str, Any]]:
        model_id = str(getattr(result, "model_id", "") or "")
        if not model_id:
            return []
        try:
            if self.profile_provider is None:
                model = self.model_provider(model_id)
                profile = self.parameter_store.get(model, "server", project_id=project_id)
            else:
                profile = self.profile_provider(project_id, source_id, model_id)
                if profile is None:
                    return []
                model = self.model_provider(model_id, profile["modelVersion"])
        except (KeyError, ValueError):
            return []
        detections = [item.to_alert_detection() for item in getattr(result, "detections", ())]
        emitted: list[dict[str, Any]] = []
        with self._lock:
            self._hydrate(project_id, source_id)
            for rule in profile.get("alertRules", []):
                if not rule.get("enabled"):
                    continue
                raw_label = str(rule.get("rawLabel") or "")
                camera = rule.get("camera") or {}
                minimum = float(camera.get("minimumConfidence", 1.0))
                matches = [item for item in detections
                           if item.get("label") == raw_label and float(item.get("confidence", 0)) >= minimum]
                key = self._runtime_key(project_id, model_id, source_id, raw_label)
                if not matches:
                    self._candidates.pop(key, None)
                    active_id = self._active.get(key)
                    if active_id:
                        try:
                            current = self.event_store.get(active_id, project_id)
                        except KeyError:
                            current = None
                        if current:
                            current.update(state="ENDED", endedAtUs=captured_at_us, lastSeenAtUs=captured_at_us)
                            self.event_store.register(current, project_id=project_id)
                            self._cooldown_at[key] = captured_at_us
                        # Release only after the durable transition succeeds.
                        self._active.pop(key, None)
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
                evidence = self._save_evidence(event_id, frame, project_id)
                event = {
                    "eventId": event_id,
                    "projectId": project_id,
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
                    "evidence": {**evidence, "capturedAtUs": captured_at_us,
                                 "displayOverlay": {"version": 1, "capturedAtUs": captured_at_us,
                                                    "bakedIn": evidence_baked_in,
                                                    "detections": matches}},
                    "disposition": {"status": "OPEN", "actor": None, "actedAtUs": None},
                }
                registered = self.event_store.register(event, project_id=project_id)
                self._active[key] = event_id
                emitted.append(registered)
                try:
                    self.delivery_service.dispatch(registered, project_id=project_id)
                except TypeError:
                    # Focused runtime tests and third-party adapters may still
                    # implement the pre-project dispatch protocol. The event
                    # itself retains projectId for those adapters.
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
