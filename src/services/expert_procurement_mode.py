"""Expert procurement-mode vocabulary for staged annotation (human authority).

Separate from legacy ProcurementForm / OpportunityTrack enums used by the model
routing stack. Human field: expert_procurement_mode.
"""
from __future__ import annotations

from typing import Any

PROCUREMENT_MODE_FIELD = "expert_procurement_mode"

PROJECT = "PROJECT"
WORKS = "WORKS"
PROJECT_AND_WORKS = "PROJECT_AND_WORKS"
DIRECT_SUPPLY = "DIRECT_SUPPLY"
UNCERTAIN = "UNCERTAIN"
# SERVICES is intentionally omitted from the primary vocabulary until a real
# control corpus + business decision requires it (see SERVICES_MODE_REQUIRED).
SERVICES = "SERVICES"

PROCUREMENT_MODE_VALUES = (
    PROJECT,
    WORKS,
    PROJECT_AND_WORKS,
    DIRECT_SUPPLY,
    UNCERTAIN,
)

PROCUREMENT_MODE_LABELS_RU = {
    PROJECT: "Проектирование",
    WORKS: "Работы",
    PROJECT_AND_WORKS: "Проектирование + работы",
    DIRECT_SUPPLY: "Прямая поставка",
    UNCERTAIN: "Не уверен",
    SERVICES: "Услуги",
}

# Primary selector options shown to operators (no SERVICES by default).
PROCUREMENT_MODE_OPTIONS = list(PROCUREMENT_MODE_VALUES)


def procurement_mode_of(payload: dict | None) -> str | None:
    if not payload:
        return None
    value = payload.get(PROCUREMENT_MODE_FIELD)
    if value in PROCUREMENT_MODE_VALUES or value == SERVICES:
        return str(value)
    return None


def procurement_mode_label(value: str | None) -> str | None:
    if not value:
        return None
    return PROCUREMENT_MODE_LABELS_RU.get(value, value)


def enable_services_mode(*, enabled: bool) -> tuple[str, ...]:
    """Return vocabulary for UI/tests when SERVICES is explicitly required."""
    if enabled:
        return PROCUREMENT_MODE_VALUES[:-1] + (SERVICES, UNCERTAIN)
    return PROCUREMENT_MODE_VALUES


def model_procurement_mode_hint(assessment: dict | None) -> str | None:
    """Read-only best-effort hint from model assessment — never auto-copied."""
    if not assessment:
        return None
    nr = assessment.get("normalized_result") or {}
    form = str(
        nr.get("procurement_form")
        or assessment.get("proposed_procurement_type")
        or ""
    ).upper()
    if not form:
        return None
    if form in {"DIRECT_GOODS_PURCHASE", "DIRECT_SUPPLY", "SUPPLY"}:
        return DIRECT_SUPPLY
    if form in {"DESIGN_ONLY", "SURVEY_AND_DESIGN", "DESIGN"}:
        return PROJECT
    if form in {"DESIGN_AND_BUILD", "DESIGN_EXPERTISE_AND_BUILD"}:
        return PROJECT_AND_WORKS
    if form in {"CONSTRUCTION_WORKS", "WORKS_OTHER", "REPAIR", "CAPITAL_REPAIR"}:
        return WORKS
    if form in {"SERVICES_OTHER", "SERVICE"}:
        return None  # do not invent SERVICES into human draft
    return None
