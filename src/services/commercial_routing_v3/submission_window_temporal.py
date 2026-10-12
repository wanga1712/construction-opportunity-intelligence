"""Canonical OPEN submission-window temporal policy for manager-facing UI.

Single source of truth for the medal temporal thresholds:

    0-40%  window consumed -> FRESH       (no medal cap)
    40-60%                 -> SILVER_CAP
    60-80%                 -> BRONZE_CAP
    80-100%                -> WOOD_CAP
    >=100%                 -> EXPIRED

The consumed ratio / remaining seconds are taken from the existing canonical
tender clock (``deadline_pressure.compute_tender_clock``); this module only
layers the cap thresholds, the temporal bucket and the "next degrade" answers
on top of it. It never re-implements the clock and never mutates medals.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Optional, Tuple

from src.services.commercial_routing_v3.deadline_pressure import compute_tender_clock
from src.services.effective_medal_service import (
    calculate_days_to_deadline,
    calculate_decay_steps,
)

FRESH = "FRESH"
SILVER_CAP = "SILVER_CAP"
BRONZE_CAP = "BRONZE_CAP"
WOOD_CAP = "WOOD_CAP"
EXPIRED = "EXPIRED"
TEMPORAL_UNKNOWN = "TEMPORAL_UNKNOWN"

STATE_ACTIVE = "ACTIVE"
STATE_EXPIRED = "EXPIRED"
STATE_UNKNOWN = "UNKNOWN"

# Ascending cap steps: (consumed-ratio at/above which the cap applies, capped medal).
# ONE canonical set of numbers -- the UI must never hardcode these.
CAP_STEPS: Tuple[Tuple[float, str], ...] = (
    (0.40, "SILVER"),
    (0.60, "BRONZE"),
    (0.80, "WOOD"),
)
WOOD_RATIO = CAP_STEPS[-1][0]

MEDAL_RANK = {"GOLD": 3, "SILVER": 2, "BRONZE": 1, "WOOD": 0}
_BUCKET_BY_CAP = {"SILVER": SILVER_CAP, "BRONZE": BRONZE_CAP, "WOOD": WOOD_CAP}

# Deadline-only fallback (window start absent). Day boundaries intentionally mirror
# the canonical medal decay schedule in effective_medal_service.calculate_decay_steps
# (>14d step0, >7d step1, >3d step2, <=3d wood); a test locks them to that function.
DEADLINE_ONLY_DAY_THRESHOLDS = ((14.0, "SILVER"), (7.0, "BRONZE"), (3.0, "WOOD"))
_STEP_BUCKET = {0: FRESH, 1: SILVER_CAP, 2: BRONZE_CAP, 3: WOOD_CAP, 4: WOOD_CAP}
WINDOW_BASIS_RATIO = "WINDOW_RATIO"
WINDOW_BASIS_DEADLINE_ONLY = "DEADLINE_ONLY"


def bucket_for_consumed_ratio(ratio: Optional[float]) -> str:
    if ratio is None:
        return TEMPORAL_UNKNOWN
    if ratio >= 1.0:
        return EXPIRED
    bucket = FRESH
    for engage_ratio, cap in CAP_STEPS:
        if ratio >= engage_ratio:
            bucket = _BUCKET_BY_CAP[cap]
    return bucket


def medal_cap_for_bucket(bucket: str) -> Optional[str]:
    for _engage, cap in CAP_STEPS:
        if _BUCKET_BY_CAP[cap] == bucket:
            return cap
    return None


def next_degrade(baseline_medal: Optional[str], ratio: Optional[float]) -> Optional[Tuple[str, float]]:
    """Next temporal threshold that actually downgrades *this* procurement.

    Computed against the temporal bucket, not the displayed medal colour, so a
    BRONZE baseline is never told "until SILVER". Returns ``(medal, ratio)`` or
    ``None`` when no further temporal downgrade exists (WOOD baseline / expired).
    """
    base = str(baseline_medal or "").upper()
    if base not in MEDAL_RANK or ratio is None or ratio >= 1.0:
        return None
    base_rank = MEDAL_RANK[base]
    for engage_ratio, cap in CAP_STEPS:
        if engage_ratio <= ratio:
            continue
        if MEDAL_RANK[cap] < base_rank:
            return cap, engage_ratio
    return None


def _parse(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        if "T" in text or " " in text:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        d = date.fromisoformat(text[:10])
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    except ValueError:
        return None


def compute_submission_window(
    *,
    submission_start_at: Any,
    submission_deadline_at: Any,
    baseline_medal: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Return the manager-facing temporal view for one submission window."""
    start = _parse(submission_start_at)
    deadline = _parse(submission_deadline_at)
    base: Dict[str, Any] = {
        "temporal_state": STATE_UNKNOWN,
        "window_basis": WINDOW_BASIS_RATIO,
        "submission_start_at": start.isoformat() if start else None,
        "submission_deadline_at": deadline.isoformat() if deadline else None,
        "window_consumed_ratio": None,
        "remaining_seconds": None,
        "seconds_to_deadline": None,
        "temporal_bucket": TEMPORAL_UNKNOWN,
        "current_medal_cap": None,
        "next_degrade_medal": None,
        "next_degrade_ratio": None,
        "seconds_to_next_degrade": None,
        "seconds_to_wood": None,
    }
    # Deadline known but start absent -> deadline-only classification (no ratio).
    if start is None and deadline is not None:
        return _deadline_only_view(deadline, baseline_medal, now)
    # Missing/ill-defined window -> no assumptions, no green bar.
    if start is None or deadline is None or deadline <= start:
        return base

    clock = compute_tender_clock(
        submission_start_at=submission_start_at,
        submission_deadline_at=submission_deadline_at,
        as_of=now,
        date_precision="DATE_ONLY",
    )
    ratio = clock.elapsed_ratio
    if ratio is None:
        return base

    expired = bool(clock.is_expired) or ratio >= 1.0
    bucket = EXPIRED if expired else bucket_for_consumed_ratio(ratio)
    total_sec = float(clock.total_duration_seconds or 0.0)
    elapsed_sec = float(clock.elapsed_seconds or 0.0)
    remaining_sec = 0.0 if expired else max(0.0, float(clock.remaining_seconds or 0.0))

    seconds_to_wood = max(0.0, WOOD_RATIO * total_sec - elapsed_sec)
    next_step = None if expired else next_degrade(baseline_medal, ratio)
    next_medal = None
    next_ratio = None
    seconds_to_next = None
    if next_step is not None:
        next_medal, next_ratio = next_step
        seconds_to_next = max(0.0, next_ratio * total_sec - elapsed_sec)

    out = dict(base)
    out.update(
        temporal_state=STATE_EXPIRED if expired else STATE_ACTIVE,
        submission_start_at=clock.submission_start_at,
        submission_deadline_at=clock.submission_deadline_at,
        window_consumed_ratio=ratio,
        remaining_seconds=remaining_sec,
        seconds_to_deadline=remaining_sec,
        temporal_bucket=bucket,
        current_medal_cap=medal_cap_for_bucket(bucket),
        next_degrade_medal=next_medal,
        next_degrade_ratio=next_ratio,
        seconds_to_next_degrade=seconds_to_next,
        seconds_to_wood=seconds_to_wood,
    )
    return out


def _deadline_only_view(
    deadline: datetime, baseline_medal: Optional[str], now: Optional[datetime]
) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    remaining = (deadline - now).total_seconds()
    out: Dict[str, Any] = {
        "temporal_state": STATE_ACTIVE,
        "window_basis": WINDOW_BASIS_DEADLINE_ONLY,
        "submission_start_at": None,
        "submission_deadline_at": deadline.isoformat(),
        "window_consumed_ratio": None,
        "remaining_seconds": max(0.0, remaining),
        "seconds_to_deadline": max(0.0, remaining),
        "temporal_bucket": TEMPORAL_UNKNOWN,
        "current_medal_cap": None,
        "next_degrade_medal": None,
        "next_degrade_ratio": None,
        "seconds_to_next_degrade": None,
        "seconds_to_wood": None,
    }
    days = calculate_days_to_deadline(deadline, now=now)
    if days is None:
        return out
    if days < 0:
        out["temporal_state"] = STATE_EXPIRED
        out["temporal_bucket"] = EXPIRED
        out["remaining_seconds"] = 0.0
        out["seconds_to_deadline"] = 0.0
        return out

    out["temporal_bucket"] = _STEP_BUCKET.get(calculate_decay_steps(days), TEMPORAL_UNKNOWN)
    base = str(baseline_medal or "").upper()
    base_rank = MEDAL_RANK.get(base)
    for threshold_days, cap in DEADLINE_ONLY_DAY_THRESHOLDS:
        seconds_to_threshold = remaining - threshold_days * 86400.0
        if cap == "WOOD":
            out["seconds_to_wood"] = max(0.0, seconds_to_threshold)
        if base_rank is None or seconds_to_threshold <= 0:
            continue
        if MEDAL_RANK[cap] < base_rank and out["next_degrade_medal"] is None:
            out["next_degrade_medal"] = cap
            out["seconds_to_next_degrade"] = seconds_to_threshold
    return out


def format_seconds(seconds: Optional[float]) -> str:
    """Compact Russian duration: 2д 7ч / 5ч 20м / 18м."""
    if seconds is None:
        return "—"
    total = int(max(0.0, seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}д {hours}ч"
    if hours:
        return f"{hours}ч {minutes}м"
    return f"{minutes}м"
