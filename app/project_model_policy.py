"""Shared eligibility rules for project model use and formal publication."""
from __future__ import annotations


def project_target_usable(model: dict, target: str) -> bool:
    """Whether a ready model target may be authorized inside a project.

    Models are eligible only after the target is formally published and ready.
    """
    if target not in model.get("supportedTargets", []):
        return False
    ready = bool(model.get("targetReadiness", {}).get(target, {}).get("ready"))
    if not ready:
        return False
    return bool(
        model.get("status") == "PUBLISHED"
        and model.get("releaseEligible")
        and model.get("targetReleaseEligible", {}).get(target)
    )


def project_model_usable(model: dict) -> bool:
    return any(project_target_usable(model, target)
               for target in model.get("supportedTargets", []))
