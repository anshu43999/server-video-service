"""Durable, bounded verification attempts; no automatic provider replay."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import time
from uuid import UUID, uuid4
from urllib.parse import quote

from ..database import AlertEventRecord, AlertVerificationRecord, DEFAULT_PROJECT_ID
from ..project_business import lock_project
from .disposition import public_alert_event
from .verification_provider import VerificationProviderError


class VerificationRequestConflict(ValueError):
    pass


class VerificationAttempts:
    MAX_ATTEMPTS = 3
    # Adapter timeout is bounded at 120s. Never replay after lease expiration.
    ATTEMPT_LEASE_US = 180_000_000
    RETRYABLE_FAILURES = frozenset({"RATE_LIMITED", "PROVIDER_UNAVAILABLE"})
    UNKNOWN_FAILURES = frozenset({"NETWORK", "TIMEOUT_UNKNOWN", "MALFORMED_RESPONSE", "OUTCOME_UNKNOWN"})

    @staticmethod
    def _public_result(payload):
        result = deepcopy(dict(payload))
        result.pop("operations", None)
        result.pop("requestDigest", None)
        if (result.get("status") == "PENDING"
                and time.time_ns() // 1000 >= int(result.get("leaseExpiresAtUs", 2**63 - 1))):
            result.update(status="UNKNOWN", failureKind="OUTCOME_UNKNOWN", retryable=False,
                          recoveryAction="RECONCILE_PROVIDER_DO_NOT_REPLAY",
                          reason="调用结果未知；保留配额，需核对供应商记录，禁止自动重放")
            for attempt in result.get("attempts", []):
                if attempt.get("attemptId") == result.get("attemptId"):
                    attempt.update(status="UNKNOWN", failureKind="OUTCOME_UNKNOWN")
        return result

    def _expire_payload(self, payload):
        result = self._public_result(payload)
        if payload.get("status") != "PENDING" or result.get("status") != "UNKNOWN":
            return deepcopy(dict(payload))
        result["requestDigest"] = payload.get("requestDigest")
        result["operations"] = deepcopy(payload.get("operations", []))
        for index, operation in enumerate(result["operations"]):
            if operation.get("operationId") == result.get("operationId"):
                result["operations"][index] = {**self._public_result(result),
                                                    "requestDigest": operation.get("requestDigest")}
        return result

    def _prepare_attempt(self, existing, event_id, actor, image_ref, image_data,
                         project_id, operation_id, retry_of, request_payload):
        identity = request_payload if request_payload is not None else {"image": image_ref, "retryOfAttemptId": retry_of}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        operations = deepcopy((existing or {}).get("operations", []))
        if existing:
            if operation_id is None:
                return self._public_result(existing), False
            for operation in operations:
                if operation.get("operationId") == operation_id:
                    if operation.get("requestDigest") != digest:
                        raise VerificationRequestConflict("idempotency_conflict")
                    return self._public_result(operation), False
            if not retry_of or retry_of != existing.get("attemptId"):
                raise VerificationRequestConflict("retry_conflict")
            if existing.get("status") != "FAILED" or not existing.get("retryable"):
                raise VerificationRequestConflict("retry_not_allowed")
        elif retry_of:
            raise VerificationRequestConflict("retry_conflict")
        attempts = deepcopy((existing or {}).get("attempts", []))
        if len(attempts) >= self.MAX_ATTEMPTS:
            raise VerificationRequestConflict("retry_limit_exceeded")
        now = time.time_ns() // 1000
        base = {"eventId": event_id, "projectId": project_id, "status": "PENDING",
                "verdict": None, "reason": "已持久预留复核额度", "modelId": self.model_id,
                "promptVersion": "verify-v1", "latencyMs": 0, "requestedAtUs": now,
                "completedAtUs": None, "source": "MANUAL_PC", "actor": actor,
                "image": (f"/aiyoloapi/projects/{quote(project_id, safe='')}/alerts/{quote(event_id, safe='')}/evidence" if image_ref else None),
                "operationId": operation_id or "legacy-initial", "requestDigest": digest,
                "retryOfAttemptId": retry_of, "attemptId": None, "attemptCount": len(attempts),
                "failureKind": None, "retryable": False, "quotaState": "NOT_RESERVED",
                "providerBilling": "NOT_SENT", "attempts": attempts, "operations": operations}
        if not self.enabled:
            failure = ("DISABLED", "智能复核未开启")
        elif not self.image_egress_authorized:
            failure = ("NOT_AUTHORIZED", "未授权图像出站，未发送任何图片")
        elif not image_ref:
            failure = ("MISSING_IMAGE", "告警缺少可用证据图片")
        elif self._calls_today >= self.daily_limit:
            failure = ("QUOTA_EXHAUSTED", "今日复核额度已用尽")
        elif not self.provider_configured or self._provider is None or not self.model_id:
            failure = ("NOT_CONFIGURED", "未配置可用的复核供应商或模型")
        elif not image_data:
            failure = ("MISSING_IMAGE", "告警证据图片不可读取")
        else:
            failure = None
        if failure:
            base.update(status="FAILED", failureKind=failure[0], reason=failure[1], completedAtUs=now)
        else:
            self._calls_today += 1
            attempt_id = str(uuid4())
            base.update(attemptId=attempt_id, attemptCount=len(attempts) + 1, quotaState="RESERVED",
                        providerBilling="UNVERIFIED", leaseExpiresAtUs=now + self.ATTEMPT_LEASE_US)
            attempts.append({key: deepcopy(base[key]) for key in (
                "attemptId", "operationId", "status", "failureKind", "requestedAtUs",
                "completedAtUs", "quotaState", "providerBilling", "actor", "modelId", "promptVersion")})
        base["operations"].append({**self._public_result(base), "requestDigest": digest})
        return base, failure is None

    def _reserve_attempt(self, event_id, actor, image_ref, image_data, project_id, operation_id, retry_of, request_payload):
        with self._lock:
            self._switch_project(project_id)
            if self._database is None:
                self._rollover()
                base, invoke = self._prepare_attempt(self._results.get((project_id, event_id)),
                    event_id, actor, image_ref, image_data, project_id, operation_id, retry_of, request_payload)
                if "operations" in base:
                    self._results[(project_id, event_id)] = deepcopy(base)
                self._project_states[project_id] = self._state_payload()
                return base, invoke, self._provider
            previous = self._state_payload()
            try:
                with self._database.session() as session:
                    lock_project(session, project_id)
                    if session.get(AlertEventRecord, (project_id, event_id)) is None:
                        raise ValueError("event_not_found")
                    else:
                        self._load_config(session, project_id)
                        self._rollover()
                        row = session.get(AlertVerificationRecord, (project_id, event_id))
                        base, invoke = self._prepare_attempt(dict(row.payload) if row else None,
                            event_id, actor, image_ref, image_data, project_id, operation_id, retry_of, request_payload)
                        if "operations" in base:
                            if row is None:
                                session.add(AlertVerificationRecord(project_id=project_id, event_id=event_id,
                                                                    status=base["status"], payload=base))
                            else:
                                row.status, row.payload = base["status"], deepcopy(base)
                            self._save_config(session, project_id)
                self._project_states[project_id] = self._state_payload()
                return base, invoke, self._provider
            except Exception:
                self._restore_state(previous)
                raise

    def _settle_attempt(self, base, outcome):
        def settle(payload):
            result = deepcopy(payload)
            if result.get("attemptId") != base["attemptId"]:
                raise VerificationRequestConflict("attempt_superseded")
            result.update(outcome)
            if result["attemptCount"] >= self.MAX_ATTEMPTS:
                result["retryable"] = False
                result["retryExhausted"] = True
            result["completedAtUs"] = time.time_ns() // 1000
            result["latencyMs"] = max(0, (result["completedAtUs"] - result["requestedAtUs"]) // 1000)
            # Internal quota measures actual dispatches, not provider invoice amounts.
            result["quotaState"] = "RESERVED" if result["status"] == "UNKNOWN" else "CONSUMED"
            for attempt in result["attempts"]:
                if attempt["attemptId"] == result["attemptId"]:
                    attempt.update({key: deepcopy(result[key]) for key in (
                        "status", "failureKind", "completedAtUs", "quotaState")})
            for index, operation in enumerate(result["operations"]):
                if operation.get("operationId") == result["operationId"]:
                    result["operations"][index] = {**self._public_result(result),
                                                        "requestDigest": operation["requestDigest"]}
            return result
        with self._lock:
            key = (base["projectId"], base["eventId"])
            if self._database is None:
                result = settle(self._results[key])
                self._results[key] = result
            else:
                with self._database.session() as session:
                    lock_project(session, key[0], enforce_lifecycle=False)
                    row = session.get(AlertVerificationRecord, key)
                    result = settle(dict(row.payload))
                    row.status, row.payload = result["status"], result
            return self._public_result(result)

    def request(self, event, *, actor, image_ref=None, image_data=None, project_id=DEFAULT_PROJECT_ID,
                operation_id=None, retry_of_attempt_id=None, request_payload=None):
        event_id = str(event.get("eventId") or event.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("eventId is required")
        if (event.get("projectId") or event.get("project_id") or project_id) != project_id:
            raise ValueError("event projectId does not match the authenticated project")
        for value in (operation_id, retry_of_attempt_id):
            if value is not None:
                if str(UUID(value)) != value:
                    raise ValueError("idempotency identity must be a canonical UUID")
        if retry_of_attempt_id and not operation_id:
            raise ValueError("explicit retry requires operationId")
        base, invoke, provider = self._reserve_attempt(
            event_id, actor, image_ref, image_data, project_id, operation_id, retry_of_attempt_id, request_payload)
        if not invoke:
            return self._public_result(base)
        try:
            response = provider.review(event=public_alert_event(event), image_data=image_data,
                                       model_id=base["modelId"], prompt_version=base["promptVersion"],
                                       attempt_id=base["attemptId"])
            verdict = response.verdict if response.verdict in {"CONFIRMED", "SUSPECTED_FALSE_POSITIVE", "INCONCLUSIVE"} else "INCONCLUSIVE"
            outcome = dict(status=verdict, verdict=verdict, reason=response.reason, source=response.source,
                           failureKind=None, retryable=False)
        except VerificationProviderError as exc:
            unknown = exc.kind in self.UNKNOWN_FAILURES
            outcome = dict(status="UNKNOWN" if unknown else "FAILED",
                           reason="供应商结果未知，禁止自动重放" if unknown else "服务端复核供应商请求失败",
                           failureKind=exc.kind, retryable=exc.kind in self.RETRYABLE_FAILURES)
            if unknown:
                outcome["recoveryAction"] = "RECONCILE_PROVIDER_DO_NOT_REPLAY"
        except Exception:
            outcome = dict(status="UNKNOWN", reason="供应商结果未知，禁止自动重放",
                           failureKind="OUTCOME_UNKNOWN", retryable=False,
                           recoveryAction="RECONCILE_PROVIDER_DO_NOT_REPLAY")
        return self._settle_attempt(base, outcome)
