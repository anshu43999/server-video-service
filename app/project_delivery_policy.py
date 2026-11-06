"""Project delivery choices; provider credentials and adapters remain platform-owned."""
from copy import deepcopy
from threading import RLock

from .database import ProjectBusinessConfigRecord, ProjectRecord
from .project_business import audit_change, lock_project

CHANNELS = ("management", "app", "email", "sms", "enterprise_im")
SEVERITY_RANK = {"MINOR": 0, "MAJOR": 1, "CRITICAL": 2}


class DeliveryPolicyConflict(ValueError):
    pass


class ProjectDeliveryPolicyStore:
    def __init__(self, database_manager=None):
        self.database = database_manager
        self._memory = {}
        self._lock = RLock()

    @staticmethod
    def default(project_id):
        return {"projectId": project_id, "revision": 0, "source": "default",
                "enabled": True, "channels": list(CHANNELS), "minimumSeverity": "MINOR"}

    def get(self, project_id):
        with self._lock:
            if self.database is not None:
                with self.database.session() as session:
                    row = session.get(ProjectBusinessConfigRecord, (project_id, "delivery"))
                    return {**deepcopy(row.payload), "projectId": project_id, "revision": row.revision} if row else self.default(project_id)
            return deepcopy(self._memory.get(project_id, self.default(project_id)))

    def save(self, project_id, values, expected_revision, *, context=None, request_id=None, reset=False):
        selected = values.get("channels", [])
        if not isinstance(selected, list) or len(selected) != len(set(selected)) or set(selected) - set(CHANNELS):
            raise ValueError("channels must be unique supported channel names")
        if values.get("minimumSeverity") not in SEVERITY_RANK:
            raise ValueError("minimumSeverity must be MINOR, MAJOR or CRITICAL")
        with self._lock:
            def update(session):
                if session is not None:
                    lock_project(session, project_id)
                    row = session.get(ProjectBusinessConfigRecord, (project_id, "delivery"))
                    before = deepcopy(row.payload) if row else self.default(project_id)
                else:
                    row = None
                    before = self._memory.get(project_id, self.default(project_id))
                if expected_revision != before["revision"]:
                    raise DeliveryPolicyConflict("delivery policy was changed by another operator")
                after = {"projectId": project_id, "revision": before["revision"] + 1,
                         "source": "default" if reset else "custom", "enabled": bool(values["enabled"]),
                         "channels": list(selected), "minimumSeverity": values["minimumSeverity"]}
                if session is not None:
                    if row is None:
                        session.add(ProjectBusinessConfigRecord(project_id=project_id, config_key="delivery",
                                                                revision=after["revision"], payload=after))
                    else:
                        row.revision, row.payload = after["revision"], deepcopy(after)
                else:
                    self._memory[project_id] = after
                audit_change(session, context, request_id, "delivery_policy.reset" if reset else "delivery_policy.update",
                             "delivery_policy", "delivery", before, after)
                return deepcopy(after)
            if self.database is not None:
                with self.database.session() as session:
                    return update(session)
            return update(None)

    def selected_channels(self, project_id, event, requested=None):
        if self.database is not None:
            with self.database.session() as session:
                project = session.get(ProjectRecord, project_id)
                state = project.lifecycle_state if project else None
        else:
            from .project_auth import memory_project_lifecycle
            state = memory_project_lifecycle(project_id)
        if state is not None and state != "ACTIVE":
            return ()
        policy = self.get(project_id)
        severity = str(event.get("notifySeverity") or event.get("severity") or "MINOR").upper()
        severity = {"NORMAL": "MINOR", "IMPORTANT": "MAJOR", "URGENT": "CRITICAL"}.get(severity, severity)
        if not policy["enabled"] or SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK[policy["minimumSeverity"]]:
            return ()
        allowed = set(policy["channels"])
        return tuple(name for name in (requested if requested is not None else policy["channels"]) if name in allowed)
