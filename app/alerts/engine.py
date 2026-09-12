"""Pure, deterministic evaluator for the v1 alert operators.

The evaluator intentionally keeps state local to one ``run_vector`` call; the
runtime service can use :class:`RuleEvaluator` incrementally later.  All clock
values come from observation envelopes.
"""
from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import json
from typing import Any, Mapping

from .geometry import Box, Roi, RoiGeometryError, box_in_roi, is_positive_crossing, side_sign, step_side
from .observation import ObservationEnvelope, validate_operator_compatibility

OPS = {"PRESENCE", "IN_REGION", "LINE_CROSS", "DWELL", "COUNT", "AREA_RATIO", "RATE", "ABSENCE"}
RESERVED = {"RELATION", "METRIC_THRESHOLD", "COMPOSITE"}
_SEVERITY_ORDER = {"MINOR": 1, "MAJOR": 2, "CRITICAL": 3}


def _roi_map(vector):
    out = {}
    for raw in vector.get("rois", []):
        try: out[raw["roiId"]] = Roi.from_mapping(raw)
        except RoiGeometryError: out[raw["roiId"]] = raw
    return out


def _labels(rule): return set(rule.get("targetLabels") or [])
def _thresholds(rule): return rule.get("thresholds", {})


def _effective_thresholds(rule, source):
    """Resolve source-specific threshold overrides without mutating the rule."""
    base = dict(rule.get("thresholds") or {})
    overrides = (rule.get("scope") or {}).get("thresholdOverrides") or {}
    override = overrides.get(source) or {}
    base.update(override)
    return base


def _event_id(rule_id, source, subject, confirmed_us, severity):
    """Derive a stable opaque event id from immutable snapshot identity."""
    payload = f"{rule_id}\x00{source}\x00{subject}\x00{confirmed_us}\x00{severity}".encode()
    return "evt-" + hashlib.sha256(payload).hexdigest()[:24]


def _det_matches(d, rule):
    return (not _labels(rule) or d.get("label") in _labels(rule)) and float(d.get("confidence", 0)) >= float(_thresholds(rule).get("minConfidence", 0))


def _box(d):
    b = d.get("box")
    return Box.from_mapping(b) if b else None


def _subject(rule, source, d=None, roi_id=None):
    kind = rule.get("subjectKind")
    if kind == "track": return f"track:{d.get('trackId', d.get('track_id'))}"
    if kind == "frame": return f"frame:{source}"
    if kind == "roi": return f"roi:{roi_id or rule.get('roiId')}"
    return f"source:{source}"


def _severity(rule, value):
    bands = rule.get("severityBands") or [{"severity": "MINOR", "atLeast": 0}]
    chosen = bands[0]["severity"]
    for band in bands:
        if value >= band["atLeast"]: chosen = band["severity"]
    return chosen


def _rejection(rule, observations, rois):
    op = str(rule.get("operator", "")).upper()
    if op in RESERVED or op == "METRIC_THRESHOLD":
        return {"accepted": False, "code": "OPERATOR_NOT_IMPLEMENTED", "ruleId": rule.get("ruleId")}
    if rule.get("subjectKind") == "metric":
        return {"accepted": False, "code": "SUBJECT_KIND_UNSUPPORTED", "ruleId": rule.get("ruleId")}
    if rule.get("subjectKind") == "frame" and op in {"DWELL", "LINE_CROSS", "ABSENCE"}:
        return {"accepted": False, "code": "SUBJECT_KIND_UNSUPPORTED", "ruleId": rule.get("ruleId")}
    if op in {"COUNT", "AREA_RATIO", "IN_REGION", "LINE_CROSS"} and rule.get("roiId") and rule["roiId"] not in rois:
        return {"accepted": False, "code": "ROI_GEOMETRY_INVALID", "ruleId": rule.get("ruleId")}
    if op in {"COUNT", "IN_REGION", "LINE_CROSS", "AREA_RATIO", "ABSENCE"} and rule.get("subjectKind") == "roi" and not rule.get("roiId"):
        return {"accepted": False, "code": "ROI_REQUIRED", "ruleId": rule.get("ruleId")}
    if rule.get("roiId") and not isinstance(rois.get(rule["roiId"]), Roi):
        return {"accepted": False, "code": "ROI_GEOMETRY_INVALID", "ruleId": rule.get("ruleId")}
    if op == "DWELL" and not rule.get("targetLabels"):
        return {"accepted": False, "code": "TARGET_LABELS_REQUIRED", "ruleId": rule.get("ruleId")}
    provided = set()
    for obs in observations: provided.update(obs.provides)
    roi = rois.get(rule.get("roiId"))
    if isinstance(roi, Roi):
        if roi.shape.value == "POLYGON": provided.add("POLYGON_ROI")
        if roi.shape.value == "LINE": provided.add("LINE_ROI")
    missing = sorted(set(rule.get("requires", ())) - provided)
    if missing:
        return {"accepted": False, "code": "CAPABILITY_UNSATISFIED", "ruleId": rule.get("ruleId"), "missing": missing}
    return None


def run_vector(vector: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate a conformance vector and return ``{"events", "rejections"}``."""
    rois = _roi_map(vector)
    observations = [ObservationEnvelope.from_mapping(x) for x in vector.get("observations", [])]
    rules = [r for r in vector.get("rules", []) if r.get("enabled", True)]
    rejections = []
    for rule in rules:
        rej = _rejection(rule, observations, rois) if observations else None
        if rej: rejections.append(rej)
    events = []
    for rule in rules:
        if any(r.get("ruleId") == rule.get("ruleId") for r in rejections): continue
        events.extend(_eval_rule(rule, observations, rois))
    return {"events": events, "rejections": rejections}


def _eval_rule(rule, observations, rois):
    op = rule["operator"].upper()
    by_source = defaultdict(list)
    for o in observations: by_source[o.source_id].append(o)
    out = []
    for source, obslist in by_source.items():
        if rule.get("scope", {}).get("sourceIds") and source not in rule["scope"]["sourceIds"]: continue
        effective = _effective_thresholds(rule, source)
        th = effective
        min_frames = int(th.get("minConsecutiveFrames", 1))
        cooldown = int(th.get("cooldownMs", 0)) * 1000
        eval_rule = dict(rule)
        eval_rule["thresholds"] = effective
        state = {}
        emitted = []
        for obs in obslist:
            roi = rois.get(rule.get("roiId"))
            vals = _values(op, eval_rule, obs, roi, state)
            current = {subject for subject, _, _ in vals}
            # Missing tracked subjects break candidates and close confirmed events.
            for key, st in list(state.items()):
                if not isinstance(key, tuple) or key[1] != rule["ruleId"] or key[0] in current: continue
                if key[0].startswith("track:"):
                    vals.append((key[0], None, {}))
            for subject, value, extra in vals:
                key = (subject, rule["ruleId"]); st = state.setdefault(key, {"streak": 0, "started": None, "active": None, "last": {}, "suppressedEpisode": False}); st.setdefault("last", {})
                if op == "RATE":
                    q = st.setdefault("hits", deque()); now = obs.captured_at_us
                    if value is not None: q.append(now)
                    cutoff = now - int(th.get("rateWindowMs", 0)) * 1000
                    while q and q[0] < cutoff: q.popleft()
                    value = len(q)
                qualifies = value is not None and _qualifies(op, value, th)
                if op == "LINE_CROSS": qualifies = bool(extra.get("crossed"))
                if op == "ABSENCE":
                    raw_absent = bool(value)
                    if raw_absent:
                        if st["started"] is None: st["started"] = obs.captured_at_us
                        duration = (obs.captured_at_us - st["started"]) / 1000
                        value = duration
                        qualifies = duration >= float(th.get("minDwellMs", 0))
                    else:
                        qualifies = False
                        if st.get("active"):
                            st["active"]["endedAtUs"] = obs.captured_at_us
                            st["active"].get("evidence", {})["endedAtUs"] = obs.captured_at_us
                            st["active"]["state"] = "ENDED"; st["active"] = None
                if qualifies:
                    st["streak"] += 1
                    if st["started"] is None: st["started"] = obs.captured_at_us
                else:
                    st["streak"] = 0
                    if op != "ABSENCE": st["started"] = None
                    st["suppressedEpisode"] = False
                    if st.get("active"):
                        st["active"]["endedAtUs"] = obs.captured_at_us
                        st["active"].get("evidence", {})["endedAtUs"] = obs.captured_at_us
                        st["active"]["state"] = "COOLDOWN" if cooldown else "ENDED"
                        st["active"] = None
                    continue
                if not qualifies or st["streak"] < min_frames: continue
                if op == "DWELL":
                    value = (obs.captured_at_us - st["started"]) / 1000
                    qualifies = value >= float(th.get("minDwellMs", 0)) and st["streak"] >= min_frames
                    if not qualifies: continue
                sev = _severity(rule, value)
                if op == "RATE" and value < th.get("minRateHits", 1): continue
                if st.get("active") and sev == st["active"].get("severity") and op != "LINE_CROSS":
                    esc = rule.get("escalation")
                    if esc and st["active"].get("escalatedAtUs") is None and obs.captured_at_us - st["active"]["confirmedAtUs"] >= int(esc["escalateAfterMs"]) * 1000:
                        st["active"]["notifySeverity"] = esc["toSeverity"]
                        st["active"]["escalatedAtUs"] = obs.captured_at_us
                    continue
                previous = st["last"].get(sev)
                # A higher fact severity always bypasses cooldown.  Lower or
                # equal severities use their own four-dimensional cooldown key.
                highest = max((_SEVERITY_ORDER.get(s, 0) for s in st["last"]), default=0)
                is_upgrade = _SEVERITY_ORDER.get(sev, 0) > highest
                if previous and cooldown and not is_upgrade and obs.captured_at_us - previous["confirmedAtUs"] < cooldown:
                    previous["suppressedCount"] += 1
                    previous["state"] = "COOLDOWN"
                    # Suppressed repeats never create a new event, regardless
                    # of whether another severity is currently active.
                    continue
                prior_severities = st.get("last", {})
                latest_prior = max(prior_severities.values(), key=lambda e: e.get("confirmedAtUs", 0), default=None)
                event_started = obs.captured_at_us if op == "RATE" or (latest_prior and latest_prior.get("severity") != sev) else st["started"]
                event = {
                    "eventId": _event_id(rule["ruleId"], source, subject, obs.captured_at_us, sev),
                    "ruleId": rule["ruleId"], "ruleVersion": rule.get("ruleVersion", 1),
                    "sourceId": source, "subjectKey": subject, "operator": op,
                    "severity": sev, "notifySeverity": sev, "escalatedAtUs": None,
                    "startedAtUs": event_started, "confirmedAtUs": obs.captured_at_us,
                    "endedAtUs": None, "measuredValue": value, "state": "CONFIRMED",
                    "suppressedCount": 0, "effectiveThresholds": dict(effective),
                    "labels": sorted(_labels(rule)),
                    "evidence": {"snapshotUri": "", "startedAtUs": event_started, "endedAtUs": None, "clipUri": None},
                    "disposition": {"status": "OPEN", "actor": None, "actedAtUs": None},
                }
                if isinstance(rule.get("model"), Mapping):
                    event["model"] = dict(rule["model"])
                if extra.get("areaSource"): event["areaSource"] = extra["areaSource"]
                if op == "LINE_CROSS": event["startedAtUs"] = obs.captured_at_us
                if st.get("active") and sev != st["active"].get("severity"): st["active"]["state"] = "COOLDOWN" if cooldown else "ENDED"
                st["active"] = event; st["last"][sev] = event; st["suppressedEpisode"] = False; emitted.append(event)
                if op == "LINE_CROSS": st["active"] = None
        out.extend(emitted)
    return out


def _values(op, rule, obs, roi, state):
    labels = _labels(rule); out = []
    dets = [d for d in obs.detections if _det_matches(d, rule)]
    if op in {"PRESENCE", "IN_REGION", "DWELL", "LINE_CROSS", "RATE"}:
        groups = defaultdict(list)
        for d in dets:
            tid = d.get("trackId", d.get("track_id"))
            if rule.get("subjectKind") == "track" and tid is not None: groups[f"track:{tid}"].append(d)
            elif rule.get("subjectKind") == "frame": groups[f"frame:{obs.source_id}"].append(d)
        if rule.get("subjectKind") == "frame" and op == "PRESENCE":
            for c in obs.classifications:
                if (not labels or c.label in labels) and c.confidence >= float(_thresholds(rule).get("minConfidence", 0)): groups[f"frame:{obs.source_id}"].append({"confidence": c.confidence})
        for subject, ds in groups.items():
            if op == "IN_REGION" and roi: ds = [d for d in ds if _box(d) and box_in_roi(roi, _box(d))]
            if op == "LINE_CROSS" and roi:
                d = ds[-1] if ds else None; prev = state.get((subject, rule["ruleId"]), {}).get("side")
                crossed = False; side = prev
                if d and _box(d):
                    side, direction = step_side(roi, prev if prev is not None else 0, _box(d).center); crossed = is_positive_crossing(roi, direction)
                state.setdefault((subject, rule["ruleId"]), {})["side"] = side
                out.append((subject, 1 if crossed else None, {"crossed": crossed})); continue
            if op == "RATE": out.append((subject, len(ds) if ds else None, {}))
            elif op == "DWELL": out.append((subject, max((d.get("confidence", 0) for d in ds), default=None), {}))
            else: out.append((subject, max((d.get("confidence", 0) for d in ds), default=None), {}))
        return out
    if op in {"COUNT", "AREA_RATIO", "ABSENCE"}:
        subject = _subject(rule, obs.source_id, roi_id=rule.get("roiId"))
        if op == "COUNT":
            ds = [d for d in dets if _box(d) and (not roi or box_in_roi(roi, _box(d)))]; return [(subject, len(ds), {})]
        if op == "ABSENCE":
            ds = [d for d in dets if _box(d) and (not roi or box_in_roi(roi, _box(d)))]; return [(subject, not ds, {})]
        masks = [m for m in obs.masks if (not labels or m.label in labels) and m.confidence >= float(_thresholds(rule).get("minConfidence", 0))]
        if masks: return [(subject, sum(m.area_ratio for m in masks), {"areaSource": "MASK"})]
        boxes = [_box(d) for d in dets if _box(d)]
        if roi and boxes:
            from .geometry import union_overlap_area, roi_area
            return [(subject, union_overlap_area(roi, boxes) / max(roi_area(roi), 1e-9), {"areaSource": "BOX_FALLBACK"})]
        return [(subject, sum(b.area for b in boxes), {"areaSource": "BOX_FALLBACK"})]
    return []


def _qualifies(op, value, th):
    if op == "ABSENCE": return bool(value)
    if op == "COUNT": return value >= th.get("minCount", 1)
    if op == "AREA_RATIO": return value >= th.get("minAreaRatio", 0)
    if op == "DWELL": return True
    if op == "RATE": return value >= th.get("minRateHits", 1)
    return value is not None
