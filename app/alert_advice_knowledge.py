"""Knowledge validation and read-only access to published system materials."""
from __future__ import annotations

ACTIVE = "ACTIVE"
INACTIVE = "INACTIVE"
MOCK_SOURCE = "MOCK_KNOWLEDGE_BASE"


class KnowledgeError(ValueError):
    code = "KNOWLEDGE_ENTRY_INVALID"


class KnowledgeConflict(KnowledgeError):
    code = "REVISION_CONFLICT"


class KnowledgeNotFound(KnowledgeError):
    code = "KNOWLEDGE_ENTRY_NOT_FOUND"


class KnowledgeMatchConflict(KnowledgeError):
    code = "ACTIVE_MATCH_KEY_CONFLICT"


def normalize_match_value(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeError(f"{field} must not be blank")
    normalized = value.strip().upper()
    if len(normalized) > 128:
        raise KnowledgeError(f"{field} exceeds 128 characters")
    return normalized


def normalize_match_key(alert_type_id: str, recognition_category_id: str) -> tuple[str, str]:
    return (
        normalize_match_value(alert_type_id, "alertTypeId"),
        normalize_match_value(recognition_category_id, "recognitionCategoryId"),
    )


def _text(value, field, maximum):
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeError(f"{field} must not be blank")
    text = value.strip()
    if len(text) > maximum:
        raise KnowledgeError(f"{field} exceeds {maximum} characters")
    return text


def validate_payload(value: dict) -> dict:
    if not isinstance(value, dict):
        raise KnowledgeError("knowledge payload must be an object")
    allowed = {"title", "riskDescription", "adviceTemplate", "references", "applicability", "sourceType"}
    if set(value) - allowed:
        raise KnowledgeError("knowledge payload contains unsupported fields")
    advice = value.get("adviceTemplate")
    if not isinstance(advice, dict) or set(advice) - {"title", "steps", "cautions"}:
        raise KnowledgeError("adviceTemplate is invalid")
    steps = advice.get("steps")
    cautions = advice.get("cautions", [])
    if not isinstance(steps, list) or not isinstance(cautions, list):
        raise KnowledgeError("advice steps and cautions must be arrays")
    normalized_steps = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or set(step) != {"stepId", "order", "title", "instruction"}:
            raise KnowledgeError("advice step fields are invalid")
        if not isinstance(step["order"], int) or isinstance(step["order"], bool) or step["order"] != index:
            raise KnowledgeError("advice step order must be contiguous from one")
        normalized_steps.append({
            "stepId": _text(step["stepId"], "stepId", 128), "order": index,
            "title": _text(step["title"], "step title", 200),
            "instruction": _text(step["instruction"], "step instruction", 2000),
        })
    if not all(isinstance(item, str) and item.strip() and len(item.strip()) <= 1000 for item in cautions):
        raise KnowledgeError("cautions contain invalid values")
    references = value.get("references")
    if not isinstance(references, list) or not references:
        raise KnowledgeError("at least one policy reference is required")
    normalized_references = []
    required = {"referenceId", "documentTitle", "documentVersion", "excerpt", "sourceName", "sourceType"}
    optional = {"documentNumber", "chapter", "clauseId", "effectiveDate"}
    for reference in references:
        if not isinstance(reference, dict) or not required.issubset(reference) or set(reference) - required - optional:
            raise KnowledgeError("policy reference fields are invalid")
        if reference["sourceType"] != MOCK_SOURCE:
            raise KnowledgeError("M41 knowledge references must be simulated")
        item = {
            "referenceId": _text(reference["referenceId"], "referenceId", 128),
            "documentTitle": _text(reference["documentTitle"], "documentTitle", 300),
            "documentVersion": _text(reference["documentVersion"], "documentVersion", 128),
            "excerpt": _text(reference["excerpt"], "excerpt", 5000),
            "sourceName": _text(reference["sourceName"], "sourceName", 300),
            "sourceType": MOCK_SOURCE,
        }
        for field, maximum in (("documentNumber", 128), ("chapter", 300), ("clauseId", 128), ("effectiveDate", 32)):
            raw = reference.get(field)
            item[field] = None if raw is None else _text(raw, field, maximum)
        normalized_references.append(item)
    return {
        "title": _text(value.get("title"), "title", 300),
        "riskDescription": _text(value.get("riskDescription"), "riskDescription", 2000),
        "adviceTemplate": {
            "title": _text(advice.get("title"), "advice title", 300),
            "steps": normalized_steps,
            "cautions": [item.strip() for item in cautions],
        },
        "references": normalized_references,
        "applicability": _text(value.get("applicability"), "applicability", 2000),
        "sourceType": MOCK_SOURCE,
    }


class AlertAdviceKnowledgeStore:
    """Project-authorized reader. Ownership and writes belong to the system catalog."""

    def __init__(self, *, system):
        if system is None:
            raise ValueError("published system knowledge is required")
        self.system = system

    def list(self, project_id):
        return sorted(self.system.published(project_id)["entries"], key=lambda item: item["entryId"])

    def get(self, project_id, entry_id):
        for item in self.list(project_id):
            if item["entryId"] == entry_id:
                return item
        raise KnowledgeNotFound("published system knowledge entry was not found")

    def find_active_exact(self, project_id, alert_type_id, recognition_category_id):
        alert_type_id, recognition_category_id = normalize_match_key(alert_type_id, recognition_category_id)
        for item in self.list(project_id):
            if item["status"] == ACTIVE and item["matchKey"] == {
                "alertTypeId": alert_type_id, "recognitionCategoryId": recognition_category_id,
            }:
                return item
        return None

    def revisions(self, project_id, entry_id):
        entry = self.get(project_id, entry_id)
        return [{"revision": entry["revision"], "action": "PUBLISHED", "actor": entry["updatedBy"],
                 "snapshot": entry, "createdAt": entry["updatedAt"], "systemVersion": entry["systemVersion"]}]
