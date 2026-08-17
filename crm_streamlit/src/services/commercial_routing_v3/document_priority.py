"""Document / research queue priority for V3 Wave-1.

Procurement-scoped jobs; opportunity associations retained in payload.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

RESEARCH_PRIORITY_FORMULA_VERSION = "V2"
DOCUMENT_PRIORITY_FORMULA = (
    "V2: dispatchable_lane_rank ASC, "
    "candidate_medal_rank ASC, "
    "candidate_score DESC, "
    "research_action_rank ASC, "
    "opportunity_track_rank ASC, "
    "deadline_pressure DESC, "
    "deadline_urgency ASC, "
    "category_fair_share_round ASC, "
    "source_newness_rank ASC, "
    "queue_age_days ASC, "
    "document_link_available DESC, "
    "procurement_id ASC"
)
RESEARCH_PRIORITY_INPUTS = (
    "research_lane, candidate_medal, candidate_score, deadline_pressure, "
    "normalized_lifecycle, opportunity_track, category_fair_share, "
    "source_newness, queue_age, document_link_availability"
)

CATEGORY_FAIR_SHARE_POLICY = (
    "equal_weight_round_robin_by_primary_commercial_category; "
    "no legacy user-specific OKPD weights; "
    "default global category weight = 1"
)

# Dispatchable lanes first
LANE_DISPATCH_RANK = {
    "ACTIVE_RESEARCH": 0,
    "crm_active_hot": 0,
    "open_active": 1,
    "FOLLOW_UP_AWARDED": 2,
    "awarded_follow_up": 2,
    "DISCOVERY_REVIEW": 3,
    "discovery_review": 3,
    "HOLD_WAITING": 8,
    "hold": 8,
    "CLOSED": 9,
    "closed_no_research": 9,
    "SUPPRESSED": 10,
}

MEDAL_RANK = {"GOLD": 0, "SILVER": 1, "BRONZE": 2, "WOOD": 3, "REVIEW": 4}
ACTION_RANK = {
    "DEEP_RESEARCH": 0,
    "PRIORITY_DOCS": 1,
    "LIGHT_RESEARCH": 2,
    "DISCOVER_COMMERCIAL_CATEGORY": 3,
    "METADATA_ONLY": 8,
    "SKIP": 9,
}
TRACK_RANK = {
    "DIRECT_SUPPLY": 0,
    "EMBEDDED_MATERIAL": 1,
    "DESIGN_REQUIREMENT": 2,
    "DESIGN_INFLUENCE": 3,
}


def normalize_queue_lane(research_lane: Optional[str], queue_state: Optional[str]) -> str:
    lane = (research_lane or "").lower()
    state = (queue_state or "").upper()
    if state == "HOLD" or lane == "hold":
        return "HOLD_WAITING"
    if state == "CLOSED_NO_RESEARCH" or lane == "closed_no_research":
        return "CLOSED"
    if lane in ("crm_active_hot", "open_active"):
        return "ACTIVE_RESEARCH"
    if lane == "awarded_follow_up":
        return "FOLLOW_UP_AWARDED"
    if lane == "discovery_review":
        return "DISCOVERY_REVIEW"
    if state == "ELIGIBLE":
        return "ACTIVE_RESEARCH"
    return "SUPPRESSED"


def compute_document_priority_score(item: Dict[str, Any]) -> int:
    """Lower is better. Encodes formula into a single comparable integer."""
    lane = normalize_queue_lane(item.get("research_lane") or item.get("queue_lane"), item.get("queue_state"))
    medal = str(item.get("candidate_medal") or item.get("candidate_level") or "WOOD").upper()
    action = str(item.get("research_action") or "SKIP").upper()
    track = str(item.get("opportunity_track") or "").upper()
    fair = int(item.get("category_fair_share_round") or 0)
    urg = int(item.get("deadline_urgency_days") or 9999)
    age = int(item.get("source_age_days") or 9999)
    pid = int(item.get("procurement_id") or 0)
    # pack loosely (not bit-perfect; used with sort_key below)
    return (
        LANE_DISPATCH_RANK.get(lane, 7) * 10_000_000
        + MEDAL_RANK.get(medal, 5) * 1_000_000
        + ACTION_RANK.get(action, 5) * 100_000
        + TRACK_RANK.get(track, 5) * 10_000
        + min(urg, 9999) * 10
        + fair
    )


def document_sort_key(item: Dict[str, Any]):
    lane = normalize_queue_lane(item.get("research_lane") or item.get("queue_lane"), item.get("queue_state"))
    medal = str(item.get("candidate_medal") or item.get("candidate_level") or "WOOD").upper()
    action = str(item.get("research_action") or "SKIP").upper()
    track = str(item.get("opportunity_track") or "").upper()
    # Higher candidate_score / deadline_pressure first → negate for ASC sort
    score = float(item.get("candidate_score") or 0.0)
    pressure = float(item.get("deadline_pressure") or 0.0)
    links = 1 if int(item.get("link_count") or 0) > 0 else 0
    newness = {"FORWARD_NEW": 0, "BACKWARD_RECOVERED": 1, "RGK_RECOVERED": 2}.get(
        str(item.get("source_origin") or "").upper(), 3
    )
    return (
        LANE_DISPATCH_RANK.get(lane, 7),
        MEDAL_RANK.get(medal, 5),
        -score,
        ACTION_RANK.get(action, 5),
        TRACK_RANK.get(track, 5),
        -pressure,
        int(item.get("deadline_urgency_days") or 9999),
        int(item.get("category_fair_share_round") or 0),
        newness,
        int(item.get("source_age_days") or item.get("queue_age_days") or 9999),
        -links,
        int(item.get("procurement_id") or 0),
    )


def apply_category_fair_share(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from collections import defaultdict, deque

    by_cat: Dict[str, deque] = defaultdict(deque)
    for it in sorted(items, key=document_sort_key):
        cat = str(it.get("primary_category") or it.get("category_code") or "_NONE_")
        by_cat[cat].append(it)
    cats = sorted(by_cat.keys())
    out: List[Dict[str, Any]] = []
    round_no = 0
    while any(by_cat[c] for c in cats):
        for cat in cats:
            if not by_cat[cat]:
                continue
            row = dict(by_cat[cat].popleft())
            row["category_fair_share_round"] = round_no
            row["document_priority"] = len(out) + 1
            row["document_priority_score"] = compute_document_priority_score(row)
            row["queue_lane_normalized"] = normalize_queue_lane(
                row.get("research_lane") or row.get("queue_lane"), row.get("queue_state")
            )
            out.append(row)
        round_no += 1
    return out
