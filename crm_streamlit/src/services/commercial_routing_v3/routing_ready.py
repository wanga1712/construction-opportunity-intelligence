"""ROUTING_READY contract for production AI admission."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from src.services.commercial_routing_v3.source_lifecycle import (
    normalize_source_lifecycle_event,
)

ACTIVE_CAPACITY_PCT = 70
AWARDED_CAPACITY_PCT = 30
WAITING_CAPACITY_PCT = 0
ROUTING_CAPACITY_POLICY = "70_ACTIVE_30_AWARDED_0_WAITING"


def evaluate_routing_ready(card: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic admission. Incomplete rows must not reach Qwen."""
    reasons: List[str] = []
    lc = str(card.get("normalized_lifecycle") or "")
    okpd = card.get("okpd_code") or (card.get("okpd") or {}).get("okpd_code")
    region = card.get("primary_commercial_region") or card.get("delivery_region")
    url = card.get("source_card_url") or card.get("tender_link")
    title = (card.get("title") or card.get("auction_name") or "").strip()
    start = card.get("procurement_start_at") or card.get("source_start_date")
    end = card.get("procurement_end_at") or card.get("source_end_date")
    remaining = card.get("remaining_days")
    if card.get("tender_clock"):
        remaining = card["tender_clock"].get("remaining_days", remaining)

    if not card.get("canonical_identity"):
        reasons.append("IDENTITY_MISMATCH")
    if not title:
        reasons.append("SOURCE_NULL:title")
    if not okpd:
        reasons.append("PROJECTION_MISSING:okpd" if card.get("source_okpd_id") else "SOURCE_NULL:okpd")
    if not region:
        reasons.append("PROJECTION_MISSING:region" if card.get("source_region_id") else "SOURCE_NULL:region")
    if not url:
        reasons.append("SOURCE_NULL:source_url")

    if lc == "WAITING_SOURCE_OUTCOME":
        reasons.append("WAITING_NOT_ROUTABLE")
    elif lc == "OPEN":
        if not start:
            reasons.append("SOURCE_NULL:start_date")
        if not end:
            reasons.append("SOURCE_NULL:end_date")
        if card.get("invalid_zero_duration"):
            reasons.append("INVALID_ZERO_DURATION")
        if remaining is not None and float(remaining) < 0:
            reasons.append("OPEN_NEGATIVE_REMAINING")
        # deadline must still be active (DATE_ONLY: today <= end_date)
        try:
            if end and date.fromisoformat(str(end)[:10]) < date.today():
                reasons.append("DEADLINE_PASSED_NOT_ACTIVE")
        except Exception:
            reasons.append("NORMALIZATION_FAILED:end_date")
    elif lc == "AWARDED":
        # winner/price preferred but not always mandatory if source NULL
        pass
    else:
        reasons.append("NORMALIZATION_FAILED:lifecycle")

    ready = len(reasons) == 0
    return {
        "ROUTING_READY": ready,
        "routing_ready": ready,
        "routing_ready_reasons": reasons,
        "routing_lane": (
            "ACTIVE"
            if ready and lc == "OPEN"
            else ("AWARDED" if ready and lc == "AWARDED" else "NOT_READY")
        ),
    }


def allocate_production_routing_batch(
    candidates: List[Dict[str, Any]],
    *,
    total: int = 100,
) -> List[Dict[str, Any]]:
    """Production capacity: 70% ACTIVE / 30% AWARDED / 0% WAITING.

    WAITING and REVIEW never borrow. Idle borrow only between ACTIVE and AWARDED.
    Within lane: new → changed → catch-up (see routing_backlog.work_tier).
    """
    from src.services.commercial_routing_v3.routing_backlog import sort_drain_priority

    active = sort_drain_priority(
        [c for c in candidates if c.get("routing_lane") == "ACTIVE_OPEN"]
    )
    awarded = sort_drain_priority(
        [c for c in candidates if c.get("routing_lane") == "AWARDED_ADMITTED"]
    )

    active_target = int(round(total * ACTIVE_CAPACITY_PCT / 100.0))
    awarded_target = total - active_target
    active_take = active[:active_target]
    awarded_take = awarded[:awarded_target]

    if len(active_take) < active_target:
        need = active_target - len(active_take)
        awarded_take.extend(
            [c for c in awarded if c not in awarded_take][:need]
        )
    if len(awarded_take) < awarded_target:
        need = awarded_target - len(awarded_take)
        active_take.extend([c for c in active if c not in active_take][:need])

    selected = active_take + awarded_take
    return selected[:total]


def allocate_canary_slots(
    active_cards: List[Dict[str, Any]],
    awarded_cards: List[Dict[str, Any]],
    *,
    total: int = 100,
) -> Dict[str, Any]:
    """70/30/0 with idle borrow between ACTIVE and AWARDED only."""
    active_target = int(round(total * ACTIVE_CAPACITY_PCT / 100.0))
    awarded_target = total - active_target
    waiting_taken = 0

    active_ready = [c for c in active_cards if c.get("ROUTING_READY") or c.get("routing_ready")]
    awarded_ready = [c for c in awarded_cards if c.get("ROUTING_READY") or c.get("routing_ready")]

    # FORWARD_NEW first within ACTIVE
    def _active_key(c):
        origin = str(c.get("source_origin") or "")
        fwd = 0 if origin == "FORWARD_NEW" else 1
        rem = c.get("remaining_days")
        try:
            rem_v = float(rem) if rem is not None else 9999.0
        except Exception:
            rem_v = 9999.0
        return (fwd, rem_v, int(c.get("procurement_id") or 0))

    active_ready.sort(key=_active_key)
    awarded_ready.sort(
        key=lambda c: (
            0 if c.get("execution_active") else 1,
            0 if c.get("winner_name") else 1,
            -float(c.get("final_contract_price") or c.get("initial_price") or 0),
            int(c.get("procurement_id") or 0),
        )
    )

    active_take = active_ready[:active_target]
    awarded_take = awarded_ready[:awarded_target]

    # idle borrow
    if len(active_take) < active_target:
        need = active_target - len(active_take)
        extra = [c for c in awarded_ready if c not in awarded_take][:need]
        awarded_take.extend(extra)
    if len(awarded_take) < awarded_target:
        need = awarded_target - len(awarded_take)
        extra = [c for c in active_ready if c not in active_take][:need]
        active_take.extend(extra)

    selected = active_take + awarded_take
    # trim to total preserving mix preference
    selected = selected[:total]
    return {
        "selected": selected,
        "ACTIVE_CAPACITY_PCT": ACTIVE_CAPACITY_PCT,
        "AWARDED_CAPACITY_PCT": AWARDED_CAPACITY_PCT,
        "WAITING_CAPACITY_PCT": WAITING_CAPACITY_PCT,
        "CANARY_V3_ACTIVE": sum(1 for c in selected if c.get("normalized_lifecycle") == "OPEN"),
        "CANARY_V3_AWARDED": sum(1 for c in selected if c.get("normalized_lifecycle") == "AWARDED"),
        "CANARY_V3_WAITING": waiting_taken,
        "CANARY_V3_FORWARD_NEW_ACTIVE": sum(
            1
            for c in selected
            if c.get("normalized_lifecycle") == "OPEN" and c.get("source_origin") == "FORWARD_NEW"
        ),
        "CANARY_V3_ACTIVE_CATCHUP": sum(
            1
            for c in selected
            if c.get("normalized_lifecycle") == "OPEN" and c.get("source_origin") != "FORWARD_NEW"
        ),
    }
