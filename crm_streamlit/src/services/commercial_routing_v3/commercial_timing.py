"""Commercial timing value — practical sales window, NOT deadline urgency.

COMMERCIAL_TIMING_VERSION = V1

deadline_pressure = urgency (near deadline → high).
commercial_timing_value = practical remaining commercial window
  (recent start + useful remaining → high; ending today / expired → low).

Gold / commercial score must NOT rise merely because deadline is almost expired.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Optional, Union

COMMERCIAL_TIMING_VERSION = "V1"
COMMERCIAL_TIMING_FORMULA = (
    "ACTIVE: 100*(0.50*freshness(age/45)+0.50*window(remaining_days)) "
    "* old_tiny_penalty; "
    "window(rem<=0)=0, rem<=1(today)=0.05, rem 1..7 ramp, rem 7..30=1, then soft decay; "
    "AWARDED: 100*(0.45*award_freshness(age/60)+0.55*exec_window); "
    "DATE_ONLY ends use end-of-day"
)

DateLike = Union[date, datetime, str, None]


def _as_date(value: DateLike) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _age_days(start: Optional[date], as_of: date) -> Optional[float]:
    if start is None:
        return None
    return float((as_of - start).days)


def _remaining_days_date_only(end: Optional[date], as_of: date) -> Optional[float]:
    """Calendar remaining; end date still valid through that calendar day."""
    if end is None:
        return None
    # remaining_days ~ (end - today) in calendar days; 0 means ends today (still not past)
    return float((end - as_of).days)


def _useful_window_score(remaining_days: Optional[float]) -> float:
    if remaining_days is None:
        return 0.0
    rem = float(remaining_days)
    if rem < 0:
        return 0.0
    if rem <= 0:
        # ends today — valid DATE_ONLY day, but low commercial timing
        return 0.05
    if rem < 1:
        return 0.05
    if rem < 7:
        return 0.05 + 0.95 * (rem - 1.0) / 6.0
    if rem <= 30:
        return 1.0
    return max(0.3, 1.0 - (rem - 30.0) / 60.0)


def compute_active_commercial_timing(
    *,
    procurement_start_at: DateLike,
    procurement_end_at: DateLike,
    remaining_days: Optional[float] = None,
    source_created_at: DateLike = None,
    published_at: DateLike = None,
    published_at_provenance: Optional[str] = None,
    as_of: Optional[date] = None,
) -> Dict[str, Any]:
    """ACTIVE timing from semantically valid procedure dates only.

    Never treats fabricated published_at as freshness input.
    Future procedure start → AMBIGUOUS; do not award max freshness.
    """
    today = as_of or datetime.now(timezone.utc).date()
    start = _as_date(procurement_start_at)
    end = _as_date(procurement_end_at)
    created = _as_date(source_created_at)
    published = _as_date(published_at)
    pub_ok = bool(
        published
        and published_at_provenance
        and "SOURCE_NOT_AVAILABLE" not in str(published_at_provenance)
        and "start_date" not in str(published_at_provenance).lower()
    )

    rem = remaining_days
    if rem is None:
        rem = _remaining_days_date_only(end, today)

    timing_confidence = "HIGH"
    timing_start_provenance = "PROCUREMENT_START_AT"
    age_basis: Optional[date] = None

    if pub_ok:
        age_basis = published
        timing_start_provenance = "PUBLISHED_AT"
    elif start is not None and start <= today:
        age_basis = start
        timing_start_provenance = "PROCUREMENT_START_AT"
    elif start is not None and start > today:
        # Future procedure start is ambiguous for "how recently started".
        timing_confidence = "AMBIGUOUS_FUTURE_PROCEDURE_START"
        timing_start_provenance = "FUTURE_PROCUREMENT_START_NOT_USED_FOR_FRESHNESS"
        if created is not None:
            age_basis = created
            timing_start_provenance = "SOURCE_CREATED_AT_INGESTION_ONLY"
            timing_confidence = "REDUCED_INGESTION_PROXY"
        else:
            age_basis = None
            timing_confidence = "LOW_NO_VALID_FRESHNESS_ANCHOR"
    elif created is not None:
        age_basis = created
        timing_start_provenance = "SOURCE_CREATED_AT_INGESTION_ONLY"
        timing_confidence = "REDUCED_INGESTION_PROXY"
    else:
        timing_confidence = "LOW_NO_VALID_FRESHNESS_ANCHOR"

    age = _age_days(age_basis, today)
    if age is not None and age < 0:
        age = 0.0

    freshness = 0.0 if age is None else _clamp(1.0 - float(age) / 45.0)
    # Cap freshness when anchor is ambiguous / ingestion-only / future start.
    if timing_confidence.startswith("AMBIGUOUS") or timing_confidence.startswith("LOW"):
        freshness = min(freshness, 0.25)
    elif timing_confidence.startswith("REDUCED"):
        freshness = min(freshness, 0.45)

    window = _useful_window_score(rem)
    penalty = 1.0
    if rem is not None and float(rem) < 0:
        penalty = 0.0
    elif age is not None and rem is not None and age >= 14 and rem <= 3:
        penalty = 0.2

    value = round(100.0 * (0.50 * freshness + 0.50 * window) * penalty, 4)
    return {
        "procurement_age_days": None if age is None else round(float(age), 4),
        "remaining_days": None if rem is None else round(float(rem), 4),
        "commercial_timing_value": value,
        "commercial_timing_version": COMMERCIAL_TIMING_VERSION,
        "commercial_timing_formula": COMMERCIAL_TIMING_FORMULA,
        "commercial_timing_confidence": timing_confidence,
        "commercial_timing_start_provenance": timing_start_provenance,
        "commercial_timing_components": {
            "freshness": round(freshness, 4),
            "window": round(window, 4),
            "old_tiny_penalty": penalty,
            "lifecycle": "OPEN",
            "published_at_used": pub_ok,
        },
    }


def compute_awarded_commercial_timing(
    *,
    award_at: DateLike,
    delivery_start_at: DateLike = None,
    delivery_end_at: DateLike = None,
    as_of: Optional[date] = None,
) -> Dict[str, Any]:
    today = as_of or datetime.now(timezone.utc).date()
    award = _as_date(award_at)
    start = _as_date(delivery_start_at)
    end = _as_date(delivery_end_at)
    award_age = _age_days(award, today)
    exec_rem = _remaining_days_date_only(end, today)

    award_fresh = 0.0 if award_age is None else _clamp(1.0 - float(award_age) / 60.0)
    exec_window = _useful_window_score(exec_rem)

    # upcoming or recently started execution gets a small boost to window
    start_bonus = 1.0
    if start is not None:
        days_to_start = (start - today).days
        if 0 <= days_to_start <= 14:
            start_bonus = 1.05  # about to start
        elif -14 <= days_to_start < 0:
            start_bonus = 1.05  # recently started
        elif days_to_start < -60 and exec_rem is not None and exec_rem <= 14:
            start_bonus = 0.5  # long-running, nearly done

    penalty = 1.0
    if award_age is not None and award_age >= 90:
        penalty *= 0.5
    if exec_rem is not None and exec_rem < 0:
        penalty = 0.0
    elif exec_rem is not None and exec_rem <= 0:
        penalty *= 0.15  # ends today

    value = round(
        100.0 * (0.45 * award_fresh + 0.55 * exec_window) * start_bonus * penalty,
        4,
    )
    value = _clamp(value, 0.0, 100.0)
    return {
        "award_age_days": None if award_age is None else round(float(award_age), 4),
        "execution_remaining_days": None if exec_rem is None else round(float(exec_rem), 4),
        "commercial_timing_value": round(value, 4),
        "commercial_timing_version": COMMERCIAL_TIMING_VERSION,
        "commercial_timing_formula": COMMERCIAL_TIMING_FORMULA,
        "commercial_timing_components": {
            "award_freshness": round(award_fresh, 4),
            "exec_window": round(exec_window, 4),
            "start_bonus": start_bonus,
            "penalty": penalty,
            "lifecycle": "AWARDED",
        },
    }


def attach_commercial_timing(card: Dict[str, Any], *, as_of: Optional[date] = None) -> Dict[str, Any]:
    """Mutate/return card with timing fields. deadline_pressure left untouched."""
    lc = str(card.get("normalized_lifecycle") or "").upper()
    if lc == "OPEN":
        timing = compute_active_commercial_timing(
            procurement_start_at=card.get("procurement_start_at")
            or card.get("submission_start_at")
            or card.get("source_start_date"),
            procurement_end_at=card.get("procurement_end_at")
            or card.get("submission_deadline_at")
            or card.get("source_end_date"),
            remaining_days=card.get("remaining_days"),
            source_created_at=card.get("source_created_at"),
            published_at=card.get("published_at"),
            published_at_provenance=card.get("published_at_provenance"),
            as_of=as_of,
        )
        card.update(timing)
        card.setdefault("award_age_days", None)
        card.setdefault("execution_remaining_days", None)
    elif lc == "AWARDED":
        timing = compute_awarded_commercial_timing(
            award_at=card.get("award_at") or card.get("contract_signed_at"),
            delivery_start_at=card.get("delivery_start_at")
            or card.get("contract_execution_start_at"),
            delivery_end_at=card.get("delivery_end_at")
            or card.get("contract_execution_end_at"),
            as_of=as_of,
        )
        card.update(timing)
        card.setdefault("procurement_age_days", None)
    else:
        card["commercial_timing_value"] = 0.0
        card["commercial_timing_version"] = COMMERCIAL_TIMING_VERSION
        card["commercial_timing_formula"] = COMMERCIAL_TIMING_FORMULA
    return card
