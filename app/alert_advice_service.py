"""Replaceable retrieval/generation boundary for user-triggered alert advice."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .alert_advice_knowledge import AlertAdviceKnowledgeStore, normalize_match_key


SIMULATED_RETRIEVER = "SIMULATED_KNOWLEDGE_BASE"
SIMULATED_GENERATOR = "SIMULATED_LLM"
SOURCE_NOTICE = "本结果来自模拟知识资料与模拟生成器，仅供演示和人工处置参考。"
MATCH_EXPLANATION = "按告警类型和识别类别精确匹配的模拟参考内容。"


class AdviceStageFailure(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = True):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class RetrievalFailure(AdviceStageFailure):
    pass


class GenerationFailure(AdviceStageFailure):
    pass


@dataclass(frozen=True)
class RetrievedKnowledge:
    entry_id: str
    revision: int
    match_key: tuple[str, str]
    advice_template: dict
    references: tuple[dict, ...]
    risk_description: str
    applicability: str
    origin: str = "PROJECT"
    system_version: int | None = None


class AlertAdviceRetriever(Protocol):
    provider: str

    def retrieve(self, project_id: str, event_snapshot: Mapping[str, Any],
                 match_key: tuple[str, str]) -> RetrievedKnowledge | None: ...


class AlertAdviceGenerator(Protocol):
    provider: str

    def generate(self, event_snapshot: Mapping[str, Any], knowledge: RetrievedKnowledge) -> dict: ...


def event_match_key(event_snapshot: Mapping[str, Any]) -> tuple[str, str] | None:
    """Resolve only frozen stable fields; display/model names never participate."""
    alert_type = event_snapshot.get("alertTypeId")
    if not isinstance(alert_type, str) or not alert_type.strip():
        alert_type = event_snapshot.get("ruleId")
    category = event_snapshot.get("recognitionCategoryId")
    if not isinstance(category, str) or not category.strip():
        category = event_snapshot.get("label")
    if not isinstance(alert_type, str) or not isinstance(category, str):
        return None
    try:
        return normalize_match_key(alert_type, category)
    except ValueError:
        return None


def sanitized_event_snapshot(event_snapshot: Mapping[str, Any]) -> dict:
    """Copy a small fact allowlist; media, paths and credentials cannot cross the boundary."""
    allowed = (
        "eventId", "alertTypeId", "recognitionCategoryId", "ruleId", "label",
        "severity", "occurredAt", "sourceId", "streamId",
    )
    return {key: deepcopy(event_snapshot.get(key)) for key in allowed if event_snapshot.get(key) is not None}


class MockKnowledgeRetriever:
    provider = SIMULATED_RETRIEVER

    def __init__(self, store: AlertAdviceKnowledgeStore, *, failure: RetrievalFailure | None = None):
        self.store = store
        self.failure = failure

    def retrieve(self, project_id, event_snapshot, match_key):
        if self.failure is not None:
            raise self.failure
        item = self.store.find_active_exact(project_id, *match_key)
        if item is None:
            return None
        actual = item["matchKey"]
        return RetrievedKnowledge(
            entry_id=item["entryId"], revision=item["revision"],
            match_key=(actual["alertTypeId"], actual["recognitionCategoryId"]),
            advice_template=deepcopy(item["adviceTemplate"]),
            references=tuple(deepcopy(item["references"])),
            risk_description=item["riskDescription"], applicability=item["applicability"],
            origin=item.get("origin", "PROJECT"), system_version=item.get("systemVersion"),
        )


class MockAdviceGenerator:
    provider = SIMULATED_GENERATOR

    def __init__(self, *, failure: GenerationFailure | None = None):
        self.failure = failure

    def generate(self, event_snapshot, knowledge):
        if self.failure is not None:
            raise self.failure
        return deepcopy(knowledge.advice_template)


class AlertAdviceService:
    def __init__(self, retriever: AlertAdviceRetriever, generator: AlertAdviceGenerator):
        self.retriever = retriever
        self.generator = generator

    def _base(self, *, status, reason_code, match_key, advice=None, references=(),
              knowledge=None, error=None):
        return {
            "status": status,
            "reasonCode": reason_code,
            "matchKey": None if match_key is None else {
                "alertTypeId": match_key[0], "recognitionCategoryId": match_key[1],
            },
            "advice": deepcopy(advice),
            "references": [deepcopy(item) for item in references],
            "knowledgeEntryId": knowledge.entry_id if knowledge else None,
            "knowledgeRevision": knowledge.revision if knowledge else None,
            "knowledgeOrigin": knowledge.origin if knowledge else None,
            "systemKnowledgeVersion": knowledge.system_version if knowledge else None,
            "matchExplanation": MATCH_EXPLANATION if knowledge else None,
            "retrievalProvider": self.retriever.provider,
            "generationProvider": self.generator.provider,
            "sourceNotice": SOURCE_NOTICE,
            "error": error,
        }

    def generate(self, project_id: str, event_snapshot: Mapping[str, Any]) -> dict:
        match_key = event_match_key(event_snapshot)
        if match_key is None:
            return self._base(status="NO_MATCH", reason_code="EVENT_MATCH_KEY_UNAVAILABLE", match_key=None)
        safe_event = sanitized_event_snapshot(event_snapshot)
        try:
            knowledge = self.retriever.retrieve(project_id, safe_event, match_key)
        except Exception as exc:
            failure = exc if isinstance(exc, RetrievalFailure) else RetrievalFailure("RETRIEVER_UNAVAILABLE")
            return self._base(
                status="FAILED_RETRIEVAL", reason_code=failure.code, match_key=match_key,
                error={"stage": "RETRIEVING", "code": failure.code, "retryable": failure.retryable},
            )
        if knowledge is None:
            return self._base(status="NO_MATCH", reason_code="KNOWLEDGE_NOT_MATCHED", match_key=match_key)
        if normalize_match_key(*knowledge.match_key) != match_key:
            code = "RETRIEVAL_KEY_MISMATCH"
            return self._base(
                status="FAILED_RETRIEVAL", reason_code=code, match_key=match_key,
                error={"stage": "RETRIEVING", "code": code, "retryable": False},
            )
        if not knowledge.advice_template.get("steps"):
            return self._base(
                status="PARTIAL", reason_code="KNOWLEDGE_HAS_NO_ADVICE_STEPS", match_key=match_key,
                references=knowledge.references, knowledge=knowledge,
            )
        try:
            advice = self.generator.generate(safe_event, knowledge)
        except Exception as exc:
            failure = exc if isinstance(exc, GenerationFailure) else GenerationFailure("GENERATOR_UNAVAILABLE")
            has_references = bool(knowledge.references)
            return self._base(
                status="PARTIAL" if has_references else "FAILED_GENERATION",
                reason_code="GENERATION_FAILED_REFERENCES_AVAILABLE" if has_references else failure.code,
                match_key=match_key, references=knowledge.references, knowledge=knowledge,
                error={"stage": "GENERATING", "code": failure.code, "retryable": failure.retryable},
            )
        return self._base(
            status="GENERATED", reason_code=None, match_key=match_key, advice=advice,
            references=knowledge.references, knowledge=knowledge,
        )
