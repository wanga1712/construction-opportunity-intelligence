"""Procurement routing priority with category fair-share as a tie policy."""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.services.commercial_routing_v3.okpd_priors import match_okpd_priors
from src.services.commercial_routing_v3.procurement_queue_priority import (
    freshness_ordinal,
)
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
    "lane_rank ASC, queue_medal DESC, source_start_date DESC, "
    "commercial_priority DESC, category_fair_share_round ASC, "
    "attempt_count ASC, procurement_id ASC"
)
ROUTING_TIE_BREAKER = "procurement_id ASC"
PRODUCTION_ROUTING_BATCH_LIMIT = 100  # crm_ai_assessment_runner --limit default


def _signal_priority_rank(item: Dict[str, Any]) -> int:
    """Initial signal changes ordering, never research reachability."""
    priority = str(item.get("research_priority") or "").strip().upper()
    reason = str(item.get("initial_pass_reason") or "").strip().upper()
    if priority == "LOW" or reason == "INITIAL_NO_PRIORITY_SIGNAL":
        return 1
    return 0


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
        f"medal={item.get('queue_medal')};"
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
    by_lane: Dict[int, Dict[Tuple[int, str], deque]] = defaultdict(
        lambda: defaultdict(deque)
    )
    for c in candidates:
        lane = c.get("routing_lane") or ""
        lane_rank = LANE_PRIORITY.get(lane, 9)
        cat = primary_prior_category(c.get("okpd_code"), priors)
        c = dict(c)
        c["primary_category"] = cat
        c["lane_rank"] = lane_rank
        c["signal_priority_rank"] = _signal_priority_rank(c)
        c["has_prior"] = 0 if cat == "_NO_PRIOR_" else 1
        by_lane[lane_rank][(c["signal_priority_rank"], cat)].append(c)

    ordered: List[Dict[str, Any]] = []
    for lane_rank in sorted(by_lane.keys()):
        signal_ranks = sorted({
            signal_rank
            for signal_rank, _cat in by_lane[lane_rank]
        })
        for signal_rank in signal_ranks:
            buckets = {
                cat: queue
                for (rank, cat), queue in by_lane[lane_rank].items()
                if rank == signal_rank
            }
            # Equal weight within one priority band: deterministic category
            # round-robin. Higher initial-signal band is exhausted first.
            cats = sorted(buckets)
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
    return ordered


def sort_lane_buckets(candidates: List[Dict[str, Any]], priors: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pre-sort each category bucket by deadline then id before fair-share."""
    enriched = []
    for c in candidates:
        e = dict(c)
        e["primary_category"] = c.get("queue_primary_category") or primary_prior_category(
            c.get("okpd_code"), priors
        )
        e["lane_rank"] = LANE_PRIORITY.get(c.get("routing_lane") or "", 9)
        e["signal_priority_rank"] = _signal_priority_rank(c)
        e["has_prior"] = 0 if e["primary_category"] == "_NO_PRIOR_" else 1
        enriched.append(e)

    enriched.sort(
        key=lambda x: (
            x["lane_rank"],
            x["signal_priority_rank"],
            x["primary_category"],
            -int(x.get("queue_medal_rank") or 0),
            -freshness_ordinal(x.get("start_date")),
            -int(x.get("queue_commercial_priority_score") or 0),
            0 if x.get("end_date") else 1,
            str(x.get("end_date") or "9999-12-31"),
            int(x.get("ai_routing_attempt_count") or 0),
            int(x["id"]),
        )
    )
    # rebuild with fair-share using already sorted order
    by_lane: Dict[int, Dict[Tuple[int, str], deque]] = defaultdict(
        lambda: defaultdict(deque)
    )
    for e in enriched:
        by_lane[e["lane_rank"]][
            (e["signal_priority_rank"], e["primary_category"])
        ].append(e)

    ordered: List[Dict[str, Any]] = []
    for lane_rank in sorted(by_lane.keys()):
        signal_ranks = sorted({
            signal_rank
            for signal_rank, _cat in by_lane[lane_rank]
        })
        for signal_rank in signal_ranks:
            buckets = {
                cat: queue
                for (rank, cat), queue in by_lane[lane_rank].items()
                if rank == signal_rank
            }
            # Prefer commercial-prior categories before _NO_PRIOR_ within the
            # same signal band.
            cats = sorted([c for c in buckets if c != "_NO_PRIOR_"]) + (
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
