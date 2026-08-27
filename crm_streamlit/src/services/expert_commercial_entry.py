"""Expert commercial-entry decision (business actionability — not source contour).

Separate from:
  - source_contour COMMERCIAL (procurement law/source family)
  - legacy expert_commercial_verdict ACTIONABLE|NO_COMMERCIAL_ENTRY
  - legacy expert_medal=NCE

Human field: expert_commercial_entry ∈ {COMMERCIAL, NON_COMMERCIAL, UNCERTAIN}
"""
from __future__ import annotations

from typing import Any

COMMERCIAL_ENTRY_FIELD = "expert_commercial_entry"
LEGACY_COMMERCIAL_STATE = "LEGACY_COMMERCIAL_STATE_UNKNOWN"

COMMERCIAL = "COMMERCIAL"
NON_COMMERCIAL = "NON_COMMERCIAL"
UNCERTAIN = "UNCERTAIN"

COMMERCIAL_ENTRY_VALUES = (COMMERCIAL, NON_COMMERCIAL, UNCERTAIN)

COMMERCIAL_ENTRY_LABELS_RU = {
    COMMERCIAL: "Коммерчески подходит",
    NON_COMMERCIAL: "Коммерчески не подходит",
    UNCERTAIN: "Не уверен",
}

# Filter keys
FILTER_COMMERCIAL = COMMERCIAL
FILTER_NON_COMMERCIAL = NON_COMMERCIAL


def commercial_entry_of(payload: dict | None) -> str | None:
    if not payload:
        return None
    value = payload.get(COMMERCIAL_ENTRY_FIELD)
    return value if value in COMMERCIAL_ENTRY_VALUES else None


def commercial_entry_label(value: str | None) -> str | None:
    if not value:
        return None
    return COMMERCIAL_ENTRY_LABELS_RU.get(value, value)


def legacy_commercial_state(payload: dict | None) -> str | None:
    """Read-only migration marker when medal/verdict exist without new entry field."""
    if not payload or commercial_entry_of(payload):
        return None
    if payload.get("expert_medal") or payload.get("expert_commercial_verdict"):
        return LEGACY_COMMERCIAL_STATE
    return None


def derive_legacy_verdict(entry: str | None) -> str | None:
    """Compatibility mapping into historical expert_commercial_verdict."""
    if entry == COMMERCIAL:
        return "ACTIONABLE"
    if entry == NON_COMMERCIAL:
        return "NO_COMMERCIAL_ENTRY"
    return None


def model_commercial_entry_hint(assessment: dict | None) -> str | None:
    """Best-effort read-only mapping — PARTIAL; never auto-copied."""
    if not assessment:
        return None
    nr = assessment.get("normalized_result") or {}
    track = str(nr.get("opportunity_track") or "").upper()
    empty = str(nr.get("empty_hypothesis_status") or "").upper()
    level = str(
        assessment.get("proposed_level")
        or nr.get("candidate_level")
        or nr.get("candidate_medal")
        or ""
    ).upper()
    if empty == "NO_COMMERCIAL_ENTRY" or track == "NO_COMMERCIAL_ENTRY":
        return NON_COMMERCIAL
    if level in {"GOLD", "SILVER", "BRONZE", "WOOD"}:
        return COMMERCIAL
    return None
