"""Model removal coordinator: PG intent -> registry commit -> PG projection."""
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from .database import (DEFAULT_PROJECT_ID, AccountRecord, ResourceLifecycleOperationRecord)
from .project_business import lock_project, audit_change
from .resource_lifecycle import reject, operation_identity, add_event, guard_model_write


class ModelRemoval:
    def __init__(self, database, catalog, assignments, scenes, stream_store, runtime_streams):
        self.database, self.catalog = database, catalog
        self.assignments, self.scenes = assignments, scenes
        self.stream_store, self.runtime_streams = stream_store, runtime_streams
        self.stream_store.lifecycle_guard = self._guard_stream
        if self.persistent:
            self.catalog.lifecycle_intents = self._pending_intents

    def _pending_intents(self):
        with self.database.session() as session:
            return [{"stage": row.stage, "intent": deepcopy(row.payload)} for row in
                    session.scalars(select(ResourceLifecycleOperationRecord).where(
                        ResourceLifecycleOperationRecord.scope_key.like("model:%"),
                        ResourceLifecycleOperationRecord.stage.in_(["prepared", "registry_committed", "projected"])))]

    def _guard_stream(self, session, model_id, version):
        if model_id is None:
            return
        item = self.catalog._find_entry(self.catalog._load(), model_id, version)
        if item is None:
            reject("model_not_found", "model release not found", 404)
        guard_model_write(session, self.catalog, model_id, item["version"])
        if self.catalog._status(item) != "PUBLISHED":
            reject("model_not_published", "stream reference requires a published release")

    @property
    def persistent(self):
        return self.database is not None and self.database.enabled

    def _session(self):
        return self.database.session() if self.persistent else nullcontext(None)

    @staticmethod
    def _authority(session, principal):
        if session is not None:
            account = session.scalar(select(AccountRecord).where(
                AccountRecord.account_id == principal.account_id).with_for_update())
            if account is None or not account.enabled or account.platform_role != "PLATFORM_ADMIN":
                reject("capability_required", "model management authority was revoked", 403)
        else:
            from .project_management import _memory_account
            account = _memory_account(principal.account_id)
            if account is None or not account.enabled or account.platform_role != "PLATFORM_ADMIN":
                reject("capability_required", "model management authority was revoked", 403)

    def _release(self, model_id, version):
        registry = self.catalog._load()
        matches = self.catalog._entries_for_model(registry, model_id)
        if version is None and len(matches) > 1:
            reject("version_required", "model has multiple releases; specify model version")
        item = self.catalog._find_entry(registry, model_id, version)
        if item is None:
            reject("model_not_found", "model release not found", 404)
        return registry, item

    def _impact(self, model_id, version):
        registry, item = self._release(model_id, version)
        version = str(item["version"])
        assignments = self.assignments.references(model_id, version)
        refs = self.scenes.references(model_id, version, include_inactive=True)
        scene_keys = {(row["projectId"], row["sceneId"]) for row in refs}
        plans = 0
        for project_id, scene_id in scene_keys:
            scene = self.scenes.get(project_id, scene_id)
            member_ids = {member["memberId"] for member in scene["models"]
                          if member["modelId"] == model_id and member["version"] == version}
            plans += sum(bool(member_ids.intersection(plan["memberIds"])) for plan in scene.get("plans", []))
        # Keep the existing conservative family-level stream protection.
        bound = {f"{row.project_id}/{row.stream_id}" for row in self.stream_store.list_all()
                 if row.model_id == model_id}
        bound.update(f"{pid}/{sid}" for (pid, sid), stream in self.runtime_streams.items()
                     if stream.model_catalog_id == model_id)
        counts = {"assignments": len(assignments), "scenes": len(scene_keys), "plans": plans,
                  "streams": len(bound),
                  "activeSlots": int(self.catalog.release_key(item) == self.catalog._resolve_active_reference(registry))}
        return {"messageType": "removal_impact",
                "operationScope": {"kind": "model_version", "modelId": model_id, "version": version},
                "expectedRevision": int(item.get("lifecycleRevision", 1)),
                "dependentCounts": counts, "knownDevices": 0, "unknownDeviceCount": 0,
                "safeToRemove": not any(counts.values())}

    def impact(self, model_id, version, principal):
        # Shared lock order: scene -> assignment -> parameters -> catalog -> default PG row.
        with self.scenes._lock, self.assignments._lock, self.assignments.parameters._lock, self.catalog.mutation_guard(), self.stream_store._lock:
            with self._session() as session:
                if session is not None:
                    lock_project(session, DEFAULT_PROJECT_ID, enforce_lifecycle=False)
                self._authority(session, principal)
                result = self._impact(model_id, version)
                if version is None:
                    result["operationScope"] = {"kind": "model_family", "modelId": model_id}
                return result

    def execute(self, model_id, version, expected, key, principal, request_id=None, action="remove", reason=None):
        if self.persistent:
            self.assignments.parameters._import_legacy_once()
        with self.scenes._lock, self.assignments._lock, self.assignments.parameters._lock, self.catalog.mutation_guard(), self.stream_store._lock:
            # Family endpoint remains explicit-one-version only; replay uses saved scope.
            scope = f"model:{model_id}@{version or '*'}"
            request_key, request_digest = operation_identity(principal.account_id, scope + ":" + action, key, [expected, reason])
            with self._session() as session:
                if session is not None:
                    lock_project(session, DEFAULT_PROJECT_ID, enforce_lifecycle=False)
                self._authority(session, principal)
                operation = session.scalar(select(ResourceLifecycleOperationRecord).where(
                    ResourceLifecycleOperationRecord.request_key == request_key)) if session is not None else None
                saved = self.catalog._load().get("lifecycleRequests", {}).get(request_key)
                if operation is not None:
                    if operation.request_digest != request_digest:
                        reject("idempotency_conflict", "idempotency key payload differs")
                    intent = deepcopy(operation.payload)
                    if operation.stage == "confirmed":
                        if saved is not None and saved.get("stage") != "confirmed":
                            registry = self.catalog._load()
                            registry["lifecycleRequests"][request_key].update(stage="confirmed", result=deepcopy(operation.result))
                            self.catalog._save(registry)
                        return deepcopy(operation.result)
                elif saved is not None:
                    if saved["digest"] != request_digest:
                        reject("idempotency_conflict", "idempotency key payload differs")
                    intent = deepcopy(saved["intent"])
                    if not self.persistent and saved["stage"] == "confirmed":
                        return deepcopy(saved["result"])
                else:
                    impact = self._impact(model_id, version)
                    if expected != impact["expectedRevision"]:
                        reject("revision_conflict", "model lifecycle revision was changed")
                    if action == "remove" and not impact["safeToRemove"]:
                        reject("model_in_use", "remove assignments and retire dependent scenes/plans/streams first")
                    if action != "remove" and impact["dependentCounts"]["assignments"]:
                        reject("model_in_use", "release is assigned to an active project")
                    exact_version = impact["operationScope"]["version"]
                    if action != "remove" and self.catalog.get(model_id, exact_version)["status"] == action:
                        reject("model_status_conflict", "release already has the requested status")
                    if action == "DEPRECATED" and self.catalog.get(model_id, exact_version)["status"] == "REVOKED":
                        reject("model_status_conflict", "revoked release cannot be deprecated")
                    intent = {"operationId": str(uuid4()), "modelId": model_id, "version": exact_version,
                              "expectedRevision": expected, "actorId": principal.account_id,
                              "action": action, "reason": reason, "requestId": request_id,
                              "scope": f"model:{model_id}@{exact_version}"}
                    if session is not None:
                        other = session.scalar(select(ResourceLifecycleOperationRecord).where(
                            ResourceLifecycleOperationRecord.scope_key == intent["scope"],
                            ResourceLifecycleOperationRecord.stage.in_(["prepared", "registry_committed", "projected"])))
                        if other is not None:
                            reject("model_removal_in_progress", "another lifecycle operation is pending")
                        session.add(ResourceLifecycleOperationRecord(operation_id=intent["operationId"],
                            request_key=request_key, scope_key=intent["scope"], actor_id=principal.account_id,
                            request_digest=request_digest, stage="prepared", payload=intent))
            # Prepared PG transaction committed. New dependency writes now fail closed.
            with self.catalog.mutation_guard(intent["operationId"]):
                return self._finish(intent, request_key, request_digest, principal)

    def _finish(self, intent, request_key, request_digest, principal):
        registry = self.catalog._load()
        requests = registry.setdefault("lifecycleRequests", {})
        saved = requests.get(request_key)
        if saved is None:
            requests[request_key] = {"digest": request_digest, "scope": intent["scope"],
                                     "stage": "prepared", "intent": intent}
            self.catalog._save(registry)
        operation_id, model_id, version = intent["operationId"], intent["modelId"], intent["version"]
        if intent["action"] == "remove":
            tombstone = next((row for row in registry.get("modelHistory", [])
                              if row.get("operationId") == operation_id and row.get("status") == "UNINSTALLED"), None)
            result = self.catalog.resume_cleanup(operation_id) if tombstone else self.catalog.uninstall(
                model_id, version, operation_id=operation_id)
        elif saved and saved.get("result"):
            result = deepcopy(saved["result"])
        else:
            result = self.catalog.set_release_status(model_id, version, intent["action"], intent["reason"],
                                                     operation_id=operation_id)
        result.update(operationId=operation_id)
        if intent["action"] == "remove":
            committed = next(row for row in self.catalog._load()["modelHistory"]
                             if row.get("operationId") == operation_id and row.get("status") == "UNINSTALLED")
            result["revision"] = committed["lifecycleRevision"]
        registry = self.catalog._load()
        registry["lifecycleRequests"][request_key].update(stage="registry_committed", result=result)
        self.catalog._save(registry)
        with self._session() as session:
            if session is not None:
                lock_project(session, DEFAULT_PROJECT_ID, enforce_lifecycle=False)
                row = session.scalar(select(ResourceLifecycleOperationRecord).where(
                    ResourceLifecycleOperationRecord.request_key == request_key).with_for_update())
                if row is None:
                    raise RuntimeError("durable operation missing; refusing false projection")
                if row.stage not in ("projected", "confirmed"):
                    audit_change(session, principal, intent["requestId"], "model." + intent["action"].lower(),
                                 "model_release", f"{model_id}@{version}",
                                 {"revision": intent["expectedRevision"]},
                                 {"revision": result["revision"], "operationId": operation_id})
                    add_event(session, intent["scope"], result["revision"],
                        {"reasonCode": {"remove": "release_removed", "REVOKED": "release_revoked",
                                        "DEPRECATED": "distribution_stopped"}[intent["action"]],
                         "modelId": model_id, "version": version}, operation_id)
                row.result = deepcopy(result)
                row.stage = "projected" if result.get("cleanupFailures") else "confirmed"
            elif not saved or saved.get("stage") != "confirmed":
                audit_change(None, principal, intent["requestId"], "model." + intent["action"].lower(),
                    "model_release", f"{model_id}@{version}", None, {"revision": result["revision"]})
        registry = self.catalog._load()
        registry["lifecycleRequests"][request_key].update(
            stage="projected" if result.get("cleanupFailures") else "confirmed", result=result)
        self.catalog._save(registry)
        return result

    def recover(self):
        """Explicit startup recovery, only already-persisted operator intents."""
        if not self.persistent:
            return
        with self.scenes._lock, self.assignments._lock, self.assignments.parameters._lock, self.catalog.mutation_guard(), self.stream_store._lock:
            # Read stages only after acquiring the same cross-process catalog lock as execute.
            # A worker waiting here must not replay a stale pre-lock pending snapshot.
            with self._session() as session:
                rows = session.scalars(select(ResourceLifecycleOperationRecord).where(
                    ResourceLifecycleOperationRecord.scope_key.like("model:%"))).all()
                confirmed = [(row.operation_id, row.request_key, deepcopy(row.result))
                             for row in rows if row.stage == "confirmed"]
                pending = [(deepcopy(row.payload), row.request_key, row.request_digest)
                           for row in rows if row.stage in ("prepared", "registry_committed", "projected")]
            registry = self.catalog._load()
            for operation_id, key, result in confirmed:
                saved = registry.get("lifecycleRequests", {}).get(key)
                if saved is not None and saved.get("stage") not in ("confirmed", "aborted"):
                    with self.catalog.mutation_guard(operation_id):
                        saved.update(stage="confirmed", result=result)
                        self.catalog._save(registry)
            for intent, key, fingerprint in pending:
                # Identity is audit attribution of a previously authorized durable intent, not a fresh grant.
                principal = SimpleNamespace(account_id=intent["actorId"], platform_role="PLATFORM_ADMIN")
                with self.catalog.mutation_guard(intent["operationId"]):
                    self._finish(intent, key, fingerprint, principal)
