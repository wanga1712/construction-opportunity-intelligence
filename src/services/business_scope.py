"""Canonical V3 business-scope contract.

Allowed explicit states: IN_PROFILE, OUT_OF_PROFILE, UNKNOWN.

Missing/null/empty/invalid never become IN_PROFILE.
Python must not invent positive profile membership from absence of data.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

SCOPE_IN_PROFILE = "IN_PROFILE"
SCOPE_OUT_OF_PROFILE = "OUT_OF_PROFILE"
SCOPE_UNKNOWN = "UNKNOWN"

EXPLICIT_SCOPES = frozenset({SCOPE_IN_PROFILE, SCOPE_OUT_OF_PROFILE})
CANONICAL_SCOPES = frozenset({SCOPE_IN_PROFILE, SCOPE_OUT_OF_PROFILE, SCOPE_UNKNOWN})
PYTHON_HARDCODE_PROVENANCE = "PYTHON_HARDCODE"


def canonicalize_business_scope(raw: Any) -> str:
    """Map any raw value to IN_PROFILE | OUT_OF_PROFILE | UNKNOWN."""
    if raw is None:
        return SCOPE_UNKNOWN
    text = str(raw).strip().upper()
    if text in EXPLICIT_SCOPES:
        return text
    return SCOPE_UNKNOWN


def explicit_scope_from_payload(payload: Optional[Mapping[str, Any]]) -> str:
    """Use payload scope only when the key is present. Missing key → UNKNOWN."""
    if not isinstance(payload, dict) or "business_scope_status" not in payload:
        return SCOPE_UNKNOWN
    return canonicalize_business_scope(payload.get("business_scope_status"))


def resolve_pipeline_scope(
    *,
    route_profile: Optional[str] = None,
    model_payload: Optional[Mapping[str, Any]] = None,
) -> str:
    """Runner/adapter authority: never infer IN_PROFILE from categories."""
    if (route_profile or "").upper() == "EXCLUDED":
        return SCOPE_OUT_OF_PROFILE
    return explicit_scope_from_payload(model_payload)


def scope_is_usable_for_publication(raw: Any) -> bool:
    """Torgi publication requires an explicit model/override scope, not UNKNOWN."""
    return canonicalize_business_scope(raw) in EXPLICIT_SCOPES


def replay_scope_with_provenance(
    stored_scope: Any,
    provenance_label: Optional[str],
) -> str:
    """Golden replay: Python-hardcoded stored IN_PROFILE is not model evidence."""
    if (provenance_label or "").upper() == PYTHON_HARDCODE_PROVENANCE:
        return SCOPE_UNKNOWN
    return canonicalize_business_scope(stored_scope)


def effective_relevance_from_scope(scope: str) -> str:
    """Positive business relevance cannot be created from UNKNOWN."""
    canonical = canonicalize_business_scope(scope)
    if canonical in EXPLICIT_SCOPES:
        return canonical
    return SCOPE_UNKNOWN
