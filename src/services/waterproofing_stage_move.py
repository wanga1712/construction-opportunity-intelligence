"""Validated stage transitions for the waterproofing kanban."""
from __future__ import annotations

from typing import Any

from src.services.waterproofing_contour import (
    latest_contour_state,
    merge_contour_state,
)
from src.services.waterproofing_crm import next_touch_default
from src.services.waterproofing_deals import latest_deal_state, merge_deal_state
from src.services.waterproofing_funnel import (
    ACCOUNT_STAGES,
    DEAL_STAGES,
    FUNNEL_ACCOUNT,
    FUNNEL_DEAL,
    STAGE_DEFAULT_ACTIONS,
    coerce_stage,
)

STALE_STAGE_MOVE = "STALE_STAGE_MOVE"
NOOP = "NOOP"
INVALID_FUNNEL = "INVALID_FUNNEL"
INVALID_STAGE = "INVALID_STAGE"

_STAGE_IDS = {
    FUNNEL_ACCOUNT: frozenset(stage.id for stage in ACCOUNT_STAGES),
    FUNNEL_DEAL: frozenset(stage.id for stage in DEAL_STAGES),
}


def _result(
    *,
    card_key: str,
    funnel: str,
    from_stage: str,
    to_stage: str,
    moved: bool,
    reason: str | None = None,
    actual_stage: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "moved": moved,
        "card_key": card_key,
        "funnel": funnel,
        "from_stage": from_stage,
        "to_stage": to_stage,
    }
    if reason:
        result["reason"] = reason
    if actual_stage:
        result["actual_stage"] = actual_stage
    return result


def move_card_stage(
    *,
    card_key: str,
    funnel: str,
    from_stage: str,
    to_stage: str,
) -> dict[str, Any]:
    """Move one card between stages through its existing persistence journal."""
    card_key = str(card_key or "").strip()
    funnel = str(funnel or "").strip()
    from_stage = str(from_stage or "").strip()
    to_stage = str(to_stage or "").strip()

    if not card_key:
        return _result(
            card_key=card_key,
            funnel=funnel,
            from_stage=from_stage,
            to_stage=to_stage,
            moved=False,
            reason=INVALID_STAGE,
        )
    if funnel not in _STAGE_IDS:
        return _result(
            card_key=card_key,
            funnel=funnel,
            from_stage=from_stage,
            to_stage=to_stage,
            moved=False,
            reason=INVALID_FUNNEL,
        )

    allowed = _STAGE_IDS[funnel]
    if from_stage not in allowed or to_stage not in allowed:
        return _result(
            card_key=card_key,
            funnel=funnel,
            from_stage=from_stage,
            to_stage=to_stage,
            moved=False,
            reason=INVALID_STAGE,
        )

    if funnel == FUNNEL_ACCOUNT:
        state = latest_contour_state(card_key)
        actual_stage = coerce_stage(state.get("stage"), FUNNEL_ACCOUNT)
    else:
        state = latest_deal_state(card_key)
        actual_stage = coerce_stage(state.get("stage"), FUNNEL_DEAL)

    if actual_stage != from_stage:
        return _result(
            card_key=card_key,
            funnel=funnel,
            from_stage=from_stage,
            to_stage=to_stage,
            moved=False,
            reason=STALE_STAGE_MOVE,
            actual_stage=actual_stage,
        )
    if from_stage == to_stage:
        return _result(
            card_key=card_key,
            funnel=funnel,
            from_stage=from_stage,
            to_stage=to_stage,
            moved=False,
            reason=NOOP,
            actual_stage=actual_stage,
        )

    patch = {
        "stage": to_stage,
        "next_action": STAGE_DEFAULT_ACTIONS.get(to_stage, ""),
        "next_action_date": next_touch_default(to_stage),
    }
    if funnel == FUNNEL_ACCOUNT:
        merge_contour_state(card_key, patch)
    else:
        merge_deal_state(card_key, patch)
    return _result(
        card_key=card_key,
        funnel=funnel,
        from_stage=from_stage,
        to_stage=to_stage,
        moved=True,
        actual_stage=actual_stage,
    )


__all__ = [
    "INVALID_FUNNEL",
    "INVALID_STAGE",
    "NOOP",
    "STALE_STAGE_MOVE",
    "move_card_stage",
]
