"""Deterministic document-claim freshness tiers."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

TIER_FRESH = 0
TIER_CHANGED = 1
TIER_BACKLOG = 2


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def compute_work_tier(proc: dict, *, today: Optional[date] = None) -> int:
    """TIER 0 fresh/open, TIER 1 changed/awarded-live, TIER 2 backlog."""
    today = today or date.today()
    start = _as_date(proc.get("start_date"))
    end = _as_date(proc.get("end_date"))
    stage = str(proc.get("crm_stage") or "").lower()
    award_status = str(proc.get("award_status") or "").lower()
    submission_open = stage == "torgi" and award_status == "submission_open"
    if submission_open and end is not None and end >= today + timedelta(days=2):
        if start is None or start >= today - timedelta(days=7):
            return TIER_FRESH
        return TIER_CHANGED
    if stage in {"awarded", "commission"} and end is not None and end >= today:
        return TIER_CHANGED
    return TIER_BACKLOG
