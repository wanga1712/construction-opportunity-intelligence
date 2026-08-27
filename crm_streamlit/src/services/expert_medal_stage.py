"""Expert medal stage for IN_CATEGORY + COMMERCIAL annotations.

Human authority: expert_medal ∈ {GOLD, SILVER, BRONZE, WOOD}.

NCE is NOT a human medal — it means No Commercial Entry and is only derived
for legacy payload compatibility when expert_commercial_entry=NON_COMMERCIAL.
"""
from __future__ import annotations

from typing import Any

MEDAL_FIELD = "expert_medal"

GOLD = "GOLD"
SILVER = "SILVER"
BRONZE = "BRONZE"
WOOD = "WOOD"
# Legacy compatibility only — never presented as human medal authority.
NCE = "NCE"

MEDAL_VALUES = (GOLD, SILVER, BRONZE, WOOD)

# Semantics aligned with existing guided_annotation.MEDAL_HELP / product intent.
MEDAL_LABELS_RU = {
    GOLD: "🥇 GOLD",
    SILVER: "🥈 SILVER",
    BRONZE: "🥉 BRONZE",
    WOOD: "🪵 WOOD",
}

MEDAL_HELP_RU = {
    GOLD: "Высокий коммерческий потенциал / точно стоит отрабатывать",
    SILVER: "Наш объект, коммерчески интересен",
    BRONZE: "Потенциально интересен, но есть ограничения",
    WOOD: "В категории и коммерчески подходит, но слабый / низкий приоритет",
}

MEDAL_SEMANTICS = {
    GOLD: "strongest fit / highest commercial priority",
    SILVER: "strong fit / commercially interesting",
    BRONZE: "useful but weaker / constrained",
    WOOD: "in-category commercial but low-value / low-priority",
}


def medal_of(payload: dict | None) -> str | None:
    """Human medal authority — GOLD–WOOD only (NCE excluded)."""
    if not payload:
        return None
    value = payload.get(MEDAL_FIELD)
    return value if value in MEDAL_VALUES else None


def medal_label(value: str | None) -> str | None:
    if not value:
        return None
    return MEDAL_LABELS_RU.get(value, value)


def model_medal_hint(assessment: dict | None) -> str | None:
    """Read-only model medal hint — PARTIAL mapping from proposed_level."""
    if not assessment:
        return None
    nr = assessment.get("normalized_result") or {}
    level = str(
        assessment.get("proposed_level")
        or nr.get("candidate_level")
        or nr.get("candidate_medal")
        or ""
    ).upper()
    return level if level in MEDAL_VALUES else None


def derive_legacy_nce_medal(*, commercial_entry: str | None) -> str | None:
    """Internal legacy compatibility only — not human medal authority."""
    if commercial_entry == "NON_COMMERCIAL":
        return NCE
    return None
