"""Effective Medal Service: Dynamic Time Decay for Commercial Opportunity Ratings.

Applies commercial time decay based on days remaining until submission deadline,
while ensuring source medals (preliminary_medal, expert_medal, candidate_medal)
remain 100% immutable.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import logging
from typing import Any, Dict, Optional, Tuple

from src.services.medal_semantics_v2 import is_model_authority_current

logger = logging.getLogger(__name__)

MEDAL_SEQUENCE = ("GOLD", "SILVER", "BRONZE", "WOOD")
MEDAL_INDEX = {m: i for i, m in enumerate(MEDAL_SEQUENCE)}

EFFECTIVE_MEDAL_RANKS = {
    "GOLD": 1,
    "SILVER": 2,
    "BRONZE": 3,
    "WOOD": 4,
    "UNASSESSED": 5,
    "CLOSED": 6,
}


def calculate_days_to_deadline(
    end_date_val: Any,
    now: Optional[datetime] = None,
) -> Optional[float]:
    """Calculate exact float days remaining until end_date in UTC."""
    if end_date_val is None:
        return None
    now = now or datetime.now(timezone.utc)
    if isinstance(end_date_val, datetime):
        dt = end_date_val if end_date_val.tzinfo else end_date_val.replace(tzinfo=timezone.utc)
        return (dt - now).total_seconds() / 86400.0
    if isinstance(end_date_val, date):
        today = now.date()
        return float((end_date_val - today).days)
    text = str(end_date_val).strip()
    try:
        if "T" in text or " " in text:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            return (dt - now).total_seconds() / 86400.0
        return float((date.fromisoformat(text[:10]) - now.date()).days)
    except Exception:
        return None


def calculate_decay_steps(days_to_deadline: Optional[float]) -> int:
    """Calculate number of medal step downgrades based on remaining days.

    Decay schedule:
      days > 14:       decay_steps = 0
      8 <= days <= 14: decay_steps = 1
      4 <= days <= 7:  decay_steps = 2
      2 <= days <= 3:  decay_steps = 3
      0 <= days < 2:   force WOOD (decay_steps = 4)
      days < 0:        CLOSED (decay_steps = 99)
    """
    if days_to_deadline is None:
        return 0
    if days_to_deadline > 14.0:
        return 0
    if days_to_deadline > 7.0:
        return 1
    if days_to_deadline > 3.0:
        return 2
    if days_to_deadline >= 2.0:
        return 3
    if days_to_deadline >= 0.0:
        return 4  # forces wood
    return 99  # closed


def compute_effective_medal(
    base_medal: str,
    days_to_deadline: Optional[float],
) -> Tuple[str, int, int]:
    """Compute effective medal, rank, and decay steps from base medal and deadline.

    Returns:
        (effective_medal, effective_medal_rank, decay_steps)
    """
    base_upper = (base_medal or "UNASSESSED").upper().strip()

    if days_to_deadline is not None and days_to_deadline < 0:
        return ("CLOSED", EFFECTIVE_MEDAL_RANKS["CLOSED"], 99)

    if base_upper not in MEDAL_INDEX:
        # UNASSESSED or unrecognized stays UNASSESSED
        return ("UNASSESSED", EFFECTIVE_MEDAL_RANKS["UNASSESSED"], 0)

    # If within 0..2 days, force WOOD
    if days_to_deadline is not None and 0 <= days_to_deadline < 2:
        return ("WOOD", EFFECTIVE_MEDAL_RANKS["WOOD"], 4)

    decay_steps = calculate_decay_steps(days_to_deadline)
    current_idx = MEDAL_INDEX[base_upper]
    new_idx = min(len(MEDAL_SEQUENCE) - 1, current_idx + decay_steps)
    effective = MEDAL_SEQUENCE[new_idx]
    return (effective, EFFECTIVE_MEDAL_RANKS[effective], decay_steps)


# Model authority gate (MEDAL SEMANTICS V2).
# A MODEL medal is business authority only when it comes from a successful
# current-semantics run. Legacy (run-less), stale, other-prompt and
# non-v2 results keep their rows in the DB but must never drive BASE_MEDAL,
# EFFECTIVE_MEDAL or any manager-facing medal.

_MODEL_RUN_META_KEYS = (
    "inference_run_id",
    "run_kind",
    "run_status",
    "prompt_version",
    "model_name",
    "model_version",
    "medal_semantics_version",
    "semantics_version",
    "is_stale",
    "model_medal_authority",
)

_MODEL_AUTHORITY_CURRENT = ("CURRENT", "SECOND_PASS_MODEL", "MODEL", "V2")


def resolve_model_medal_authority(card: Dict[str, Any]) -> str:
    """Classify a card's MODEL medal as CURRENT / LEGACY / ABSENT."""
    if not card.get("model_medal"):
        return "ABSENT"
    explicit = card.get("model_medal_authority")
    if explicit is not None:
        val = str(explicit).upper().strip()
        return "CURRENT" if val in _MODEL_AUTHORITY_CURRENT else "LEGACY"
    if not any(k in card for k in _MODEL_RUN_META_KEYS):
        # No run metadata at all (non-DB callers, minimal projections):
        # preserve the historical behaviour.
        return "CURRENT"
    ok = is_model_authority_current(
        inference_run_id=card.get("inference_run_id"),
        run_kind=card.get("run_kind"),
        run_status=card.get("run_status"),
        prompt_version=card.get("prompt_version"),
        model_name=card.get("model_name") or card.get("model_version"),
        semantics_version=card.get(
            "medal_semantics_version", card.get("semantics_version")
        ),
        is_stale=card.get("is_stale"),
    )
    return "CURRENT" if ok else "LEGACY"


def resolve_card_effective_medals(
    card: Dict[str, Any],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute and attach effective medal fields according to Authority Hierarchy:
    EXPERT > CURRENT SEMANTICS-V2 MODEL > PRELIMINARY > UNASSESSED
    without mutating source medals.

    MEDAL SEMANTICS V2: a legacy (run-less), stale or old-prompt MODEL medal
    is recorded as authority LEGACY and skipped, so such a card falls back to
    a category-backed PRELIMINARY medal instead of an obsolete verdict.
    """
    is_conf = bool(card.get("is_confirmed"))
    exp_medal = card.get("expert_medal")
    model_medal = card.get("model_medal")
    prelim_medal = card.get("preliminary_medal") or "UNASSESSED"

    model_authority = resolve_model_medal_authority(card)
    card["model_medal_authority"] = model_authority

    if is_conf and exp_medal and str(exp_medal).upper() in MEDAL_INDEX:
        base_medal = str(exp_medal).upper()
        base_authority = "EXPERT"
    elif (
        model_authority == "CURRENT"
        and model_medal
        and str(model_medal).upper() in MEDAL_INDEX
    ):
        base_medal = str(model_medal).upper()
        base_authority = "SECOND_PASS_MODEL"
    elif prelim_medal and str(prelim_medal).upper() in MEDAL_INDEX:
        base_medal = str(prelim_medal).upper()
        base_authority = "PRELIMINARY"
    else:
        base_medal = "UNASSESSED"
        base_authority = "UNASSESSED"

    days = calculate_days_to_deadline(card.get("end_date"), now=now)
    eff_medal, eff_rank, decay = compute_effective_medal(base_medal, days)

    card["base_medal"] = base_medal
    card["base_medal_authority"] = base_authority
    card["effective_medal"] = eff_medal
    card["effective_medal_rank"] = eff_rank
    card["deadline_decay_steps"] = decay
    card["days_to_deadline"] = days
    return card

