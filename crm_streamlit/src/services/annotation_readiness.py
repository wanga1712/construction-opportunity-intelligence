"""Phase C semantics for expert annotation completeness and future eligibility."""
from __future__ import annotations

from typing import Any


REVIEW_SCOPES = ("CATEGORY_ONLY", "OBJECT_ONLY", "FULL_CARD")
COMPLETENESS_STATES = ("PARTIAL", "COMPLETE")
EVIDENCE_STATES = ("SUFFICIENT", "NEEDS_DOCUMENT_RESEARCH")


def training_eligibility_reasons(
    payload: dict[str, Any],
    assessment: dict[str, Any] | None,
) -> list[str]:
    """Return deterministic reasons why a current annotation is not exportable."""
    reasons: list[str] = []
    scope = payload.get("annotation_review_scope")
    if scope not in (*REVIEW_SCOPES, "OUT_OF_PROFILE"):
        reasons.append("REVIEW_SCOPE_UNKNOWN")
    if payload.get("annotation_completeness") != "COMPLETE":
        reasons.append("ANNOTATION_INCOMPLETE")
    if payload.get("evidence_state") == "NEEDS_DOCUMENT_RESEARCH":
        reasons.append("INSUFFICIENT_EVIDENCE")
    if not payload.get("model_assessment_id"):
        reasons.append("MODEL_ASSESSMENT_UNLINKED")
    if not assessment:
        reasons.append("MODEL_RESULT_UNAVAILABLE")
    elif not (assessment.get("normalized_result") or assessment.get("validated_model_result")):
        reasons.append("MODEL_RESULT_UNAVAILABLE")

    if scope in ("CATEGORY_ONLY", "FULL_CARD"):
        reviewed = list(payload.get("reviewed_model_categories") or [])
        model_rows = list(payload.get("model_category_review_state") or [])
        if not model_rows and not payload.get("expert_category_absence_confirmed"):
            reasons.append("CATEGORY_REVIEW_STATE_MISSING")
        elif any(not row.get("reviewed") for row in model_rows):
            reasons.append("MODEL_CATEGORIES_NOT_FULLY_REVIEWED")
        if model_rows and not reviewed:
            reasons.append("CATEGORY_DECISIONS_MISSING")

    if scope in ("OBJECT_ONLY", "FULL_CARD") and not any(
        payload.get(key)
        for key in ("expert_object_type", "expert_object_subtype", "expert_work_stage")
    ):
        reasons.append("OBJECT_REVIEW_EMPTY")
    return list(dict.fromkeys(reasons))


def is_training_eligible(payload: dict[str, Any], assessment: dict[str, Any] | None) -> bool:
    return not training_eligibility_reasons(payload, assessment)
