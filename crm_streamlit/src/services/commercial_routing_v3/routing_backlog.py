"""Routing backlog classification for production drain scheduling.

Uses the same selectable candidates as crm_ai_assessment_runner.fetch_candidates
+ capacity lanes. No commercial semantic changes.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from src.services.commercial_routing_v3.routing_eligibility import (
    LANE_ACTIVE_OPEN,
    LANE_AWARDED_ADMITTED,
)

CHANGED_REASONS = frozenset({"FINGERPRINT_CHANGED", "REASSESSMENT_REQUESTED"})
NEW_REASONS = frozenset({"PENDING"})
# Retries / reclaim / force-like reasons treated as catch-up within eligible set
CATCHUP_PREFIXES = ("RETRY_", "STALE_", "FORCE_")


def work_tier(item: Dict[str, Any]) -> int:
    """0=FORWARD_NEW/new, 1=changed, 2=catch-up. Lower is higher priority."""
    origin = str(item.get("source_origin") or "")
    if origin == "FORWARD_NEW":
        return 0
    reason = str(item.get("eligibility_reason") or "")
    status = str(item.get("ai_assessment_status") or "").upper()
    if reason in NEW_REASONS and status in ("UNASSESSED", "QUEUED", ""):
        return 0
    if reason in CHANGED_REASONS:
        return 1
    if status in ("FAILED", "STALE") or reason.startswith(CATCHUP_PREFIXES):
        return 2
    return 2


def classify_eligible_backlog(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Break down production-selectable candidates (WAITING already excluded)."""
    active = [c for c in candidates if c.get("routing_lane") == LANE_ACTIVE_OPEN]
    awarded = [c for c in candidates if c.get("routing_lane") == LANE_AWARDED_ADMITTED]
    # REVIEW_DISCOVERY is not part of 70/30 capacity; count separately if present
    other = [
        c
        for c in candidates
        if c.get("routing_lane") not in (LANE_ACTIVE_OPEN, LANE_AWARDED_ADMITTED)
    ]

    def _bucket(rows: List[Dict[str, Any]]) -> Dict[str, int]:
        unas = changed = catchup = 0
        for c in rows:
            tier = work_tier(c)
            if tier == 0:
                unas += 1
            elif tier == 1:
                changed += 1
            else:
                catchup += 1
        return {
            "UNASSESSED": unas,
            "CHANGED": changed,
            "CATCHUP": catchup,
            "TOTAL": len(rows),
        }

    a = _bucket(active)
    w = _bucket(awarded)
    return {
        "ELIGIBLE_ACTIVE_UNASSESSED": a["UNASSESSED"],
        "ELIGIBLE_ACTIVE_CHANGED": a["CHANGED"],
        "ELIGIBLE_ACTIVE_CATCHUP": a["CATCHUP"],
        "ELIGIBLE_AWARDED_UNASSESSED": w["UNASSESSED"],
        "ELIGIBLE_AWARDED_CHANGED": w["CHANGED"],
        "ELIGIBLE_AWARDED_CATCHUP": w["CATCHUP"],
        "ACTIVE_BACKLOG": a["TOTAL"],
        "AWARDED_BACKLOG": w["TOTAL"],
        "OTHER_SELECTABLE_LANES": len(other),
        "TOTAL_ROUTING_ELIGIBLE_BACKLOG": a["TOTAL"] + w["TOTAL"],
        "reason_counts": dict(Counter(c.get("eligibility_reason") for c in candidates)),
        "lane_counts": dict(Counter(c.get("routing_lane") for c in candidates)),
    }


def sort_drain_priority(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Stable priority: new → changed → catch-up, then end_date, id."""
    return sorted(
        candidates,
        key=lambda c: (
            work_tier(c),
            0 if c.get("end_date") else 1,
            str(c.get("end_date") or "9999-12-31"),
            int(c.get("id") or c.get("procurement_id") or 0),
        ),
    )
