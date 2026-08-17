"""Wave-1 routing backlog priority + category fair-share.

Deterministic production ordering. Medal is NOT used (pre-Qwen).
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.services.commercial_routing_v3.okpd_priors import match_okpd_priors
from src.services.commercial_routing_v3.routing_eligibility import (
    LANE_ACTIVE_OPEN,
    LANE_AWARDED_ADMITTED,
    LANE_REVIEW_DISCOVERY,
    LANE_WAITING_HOLD,
)

# Lane operational preference: ACTIVE before HOLD/AWARDED/REVIEW
LANE_PRIORITY = {
    LANE_ACTIVE_OPEN: 0,
    LANE_WAITING_HOLD: 1,
    LANE_AWARDED_ADMITTED: 2,
    LANE_REVIEW_DISCOVERY: 3,
}

ROUTING_PRIORITY_FORMULA = (
    "lane_rank ASC, category_fair_share_round ASC, "
    "has_prior DESC, end_date ASC NULLS LAST, "
    "attempt_count ASC, procurement_id ASC"
)
ROUTING_TIE_BREAKER = "procurement_id ASC"
PRODUCTION_ROUTING_BATCH_LIMIT = 100  # crm_ai_assessment_runner --limit default


def primary_prior_category(okpd_code: Optional[str], priors: Sequence[Dict[str, Any]]) -> str:
    matched = match_okpd_priors(okpd_code, list(priors)) if okpd_code else []
    cats = sorted(
        {
            str(p.get("commercial_category_code"))
            for p in matched
            if p.get("commercial_category_code")
        }
    )
    return cats[0] if cats else "_NO_PRIOR_"


def build_priority_reason(item: Dict[str, Any]) -> str:
    return (
        f"lane={item.get('routing_lane')};"
        f"cat={item.get('primary_category')};"
        f"fair_round={item.get('fair_share_round')};"
        f"end={item.get('end_date')};"
        f"attempts={item.get('ai_routing_attempt_count', 0)}"
    )


def order_routing_backlog(
    candidates: List[Dict[str, Any]],
    *,
    priors: Sequence[Dict[str, Any]],
    as_of: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Apply lane preference + equal-weight category fair-share within lanes.

    ONE item per procurement (caller must already dedupe).
    """
    by_lane: Dict[int, Dict[str, deque]] = defaultdict(lambda: defaultdict(deque))
    for c in candidates:
        lane = c.get("routing_lane") or ""
        lane_rank = LANE_PRIORITY.get(lane, 9)
        cat = primary_prior_category(c.get("okpd_code"), priors)
        c = dict(c)
        c["primary_category"] = cat
        c["lane_rank"] = lane_rank
        c["has_prior"] = 0 if cat == "_NO_PRIOR_" else 1
        by_lane[lane_rank][cat].append(c)

    ordered: List[Dict[str, Any]] = []
    for lane_rank in sorted(by_lane.keys()):
        buckets = by_lane[lane_rank]
        # equal weight: sort category keys for determinism, then round-robin
        cats = sorted(buckets.keys())
        round_no = 0
        while any(buckets[cat] for cat in cats):
            for cat in cats:
                if not buckets[cat]:
                    continue
                item = buckets[cat].popleft()
                item["fair_share_round"] = round_no
                item["routing_priority"] = len(ordered) + 1
                item["priority_reason"] = build_priority_reason(item)
                ordered.append(item)
            round_no += 1
            # secondary sort stability within same fair round already FIFO from end_date
            # but initial deque order must be deterministic
    # Ensure within each category deque was end_date ordered
    return ordered


def sort_lane_buckets(candidates: List[Dict[str, Any]], priors: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pre-sort each category bucket by deadline then id before fair-share."""
    enriched = []
    for c in candidates:
        e = dict(c)
        e["primary_category"] = primary_prior_category(c.get("okpd_code"), priors)
        e["lane_rank"] = LANE_PRIORITY.get(c.get("routing_lane") or "", 9)
        e["has_prior"] = 0 if e["primary_category"] == "_NO_PRIOR_" else 1
        enriched.append(e)

    enriched.sort(
        key=lambda x: (
            x["lane_rank"],
            x["primary_category"],
            0 if x.get("end_date") else 1,
            str(x.get("end_date") or "9999-12-31"),
            int(x.get("ai_routing_attempt_count") or 0),
            int(x["id"]),
        )
    )
    # rebuild with fair-share using already sorted order
    by_lane: Dict[int, Dict[str, deque]] = defaultdict(lambda: defaultdict(deque))
    for e in enriched:
        by_lane[e["lane_rank"]][e["primary_category"]].append(e)

    ordered: List[Dict[str, Any]] = []
    for lane_rank in sorted(by_lane.keys()):
        buckets = by_lane[lane_rank]
        # Prefer commercial-prior categories before _NO_PRIOR_ (still deterministic).
        cats = sorted([c for c in buckets.keys() if c != "_NO_PRIOR_"]) + (
            ["_NO_PRIOR_"] if "_NO_PRIOR_" in buckets else []
        )
        round_no = 0
        while any(buckets[c] for c in cats):
            for cat in cats:
                if not buckets[cat]:
                    continue
                item = buckets[cat].popleft()
                item["fair_share_round"] = round_no
                item["routing_priority"] = len(ordered) + 1
                item["priority_reason"] = build_priority_reason(item)
                ordered.append(item)
            round_no += 1
    return ordered
