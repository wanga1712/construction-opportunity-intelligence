"""Dependency-light queue admission policy shared by producers and workers."""

from __future__ import annotations

from typing import Any, Mapping

ADMISSION_ELIGIBLE = "ELIGIBLE"
ADMISSION_EXCLUDED = "EXCLUDED"
ADMISSION_HOLD = "HOLD"
ADMISSION_POLICY_VERSION = "BUSINESS_RESEARCH_ADMISSION_V2"


def authority_allows_queue(authority: Mapping[str, Any] | None) -> bool:
    """Only an explicit persisted ELIGIBLE authority row may enter the queue."""
    return bool(authority and authority.get("admission_state") == ADMISSION_ELIGIBLE)


def queue_context_allows_claim(category_context: Mapping[str, Any] | None) -> bool:
    """Fail closed for legacy rows and contexts without a persisted admission."""
    if not category_context:
        return False
    admission = category_context.get("admission")
    if isinstance(admission, Mapping):
        return admission.get("admission_state") == ADMISSION_ELIGIBLE
    return category_context.get("admission_state") == ADMISSION_ELIGIBLE


def admission_claim_sql(alias: str = "q") -> str:
    """SQL predicate for the document DB's denormalized authority context."""
    return (
        f" AND COALESCE({alias}.category_context->>'admission_state', "
        f"{alias}.category_context->'admission'->>'admission_state') = 'ELIGIBLE'"
        f" AND COALESCE({alias}.category_context->>'admission_policy_version', "
        f"{alias}.category_context->'admission'->>'policy_version') = '"
        f"{ADMISSION_POLICY_VERSION}'"
        f" AND COALESCE({alias}.category_context->>'admission_evaluated_at', "
        f"{alias}.category_context->'admission'->>'admission_evaluated_at') IS NOT NULL"
    )
