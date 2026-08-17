"""Deterministic AWARDED execution-window clock and post-award commercial timing.

Separate from ACTIVE procedure timing — models how late we enter an already-won contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Dict, Optional, Tuple, Union

from src.domain.commercial_routing_v3 import CandidateMedal

POST_AWARD_TIMING_VERSION = "v1_execution_window_20260814"

DateLike = Union[date, datetime, str, None]

# Phase thresholds — versioned; do not tune for medal quotas.
PHASE_CLOSING_MAX_REMAINING_RATIO = 0.10
PHASE_LATE_MAX_REMAINING_RATIO = 0.25
PHASE_MID_MAX_REMAINING_RATIO = 0.60
PHASE_CLOSING_MAX_DAYS_SHORT_CONTRACT = 21
PHASE_CLOSING_SHORT_CONTRACT_MAX_DAYS = 90
PHASE_CLOSING_SHORT_RATIO = 0.25
PHASE_CLOSING_ABSOLUTE_DAYS = 14
PHASE_CLOSING_ABSOLUTE_RATIO = 0.20
PHASE_LATE_ABSOLUTE_DAYS = 45
PHASE_LATE_ABSOLUTE_RATIO = 0.35

HARD_CAP_WOOD_MAX_REMAINING_RATIO = 0.10


class ExecutionPhase(StrEnum):
    EARLY_EXECUTION = "EARLY_EXECUTION"
    MID_EXECUTION = "MID_EXECUTION"
    LATE_EXECUTION = "LATE_EXECUTION"
    CLOSING = "CLOSING"
    NOT_AVAILABLE = "NOT_AVAILABLE"


@dataclass(frozen=True)
class ExecutionClock:
    execution_start_at: Optional[str]
    execution_end_at: Optional[str]
    execution_total_days: Optional[float]
    execution_elapsed_days: Optional[float]
    execution_remaining_days: Optional[float]
    execution_elapsed_ratio: Optional[float]
    execution_remaining_ratio: Optional[float]
    execution_phase: ExecutionPhase
    post_award_commercial_timing_value: Optional[float]
    execution_timing_status: str
    post_award_timing_version: str = POST_AWARD_TIMING_VERSION
    provenance: str = "NOT_AVAILABLE"


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


def _first_date(*values: DateLike) -> Tuple[Optional[date], str]:
    for v in values:
        d = _as_date(v)
        if d is not None:
            return d, str(v)[:10]
    return None, ""


def execution_dates_suspect(model_input: Dict[str, Any]) -> bool:
    """True when execution window dates must not improve Candidate timing score."""
    ds = str(model_input.get("delivery_start_at") or model_input.get("execution_start_at") or "")[:10]
    de = str(model_input.get("delivery_end_at") or model_input.get("execution_end_at") or "")[:10]
    if ds and de and ds == de:
        return True
    table = str(model_input.get("source_table") or "")
    if "223" in table and (not ds or not de):
        return True
    return False


def compute_execution_clock(
    *,
    execution_start_at: DateLike = None,
    execution_end_at: DateLike = None,
    delivery_start_at: DateLike = None,
    delivery_end_at: DateLike = None,
    contract_execution_start_at: DateLike = None,
    contract_execution_end_at: DateLike = None,
    execution_remaining_days: Optional[float] = None,
    as_of: Optional[date] = None,
    suppress_suspect: bool = False,
) -> ExecutionClock:
    today = as_of or datetime.now(timezone.utc).date()
    start, start_iso = _first_date(
        execution_start_at,
        delivery_start_at,
        contract_execution_start_at,
    )
    end, end_iso = _first_date(
        execution_end_at,
        delivery_end_at,
        contract_execution_end_at,
    )
    provenance = "NOT_AVAILABLE"
    if start_iso or end_iso:
        provenance = "execution_or_delivery_dates"

    total: Optional[float] = None
    elapsed: Optional[float] = None
    remaining: Optional[float] = None
    elapsed_ratio: Optional[float] = None
    remaining_ratio: Optional[float] = None

    if start is not None and end is not None and end >= start:
        total = float((end - start).days)
        if total <= 0:
            total = 1.0
        remaining = float((end - today).days)
        elapsed = max(0.0, total - remaining)
        elapsed_ratio = _clamp_ratio(elapsed / total)
        remaining_ratio = _clamp_ratio(remaining / total)
    elif execution_remaining_days is not None:
        remaining = float(execution_remaining_days)
        provenance = "execution_remaining_days_only"

    if suppress_suspect:
        return ExecutionClock(
            execution_start_at=start_iso or None,
            execution_end_at=end_iso or None,
            execution_total_days=total,
            execution_elapsed_days=elapsed,
            execution_remaining_days=remaining,
            execution_elapsed_ratio=elapsed_ratio,
            execution_remaining_ratio=remaining_ratio,
            execution_phase=ExecutionPhase.NOT_AVAILABLE,
            post_award_commercial_timing_value=None,
            execution_timing_status="SUPPRESSED_SOURCE_SUSPECT",
            provenance=provenance,
        )

    phase = classify_execution_phase(
        total_days=total,
        remaining_days=remaining,
        remaining_ratio=remaining_ratio,
    )
    timing_value = compute_post_award_commercial_timing_value(
        remaining_days=remaining,
        remaining_ratio=remaining_ratio,
        phase=phase,
    )
    status = "NOT_AVAILABLE"
    if remaining is not None:
        status = "USED"

    return ExecutionClock(
        execution_start_at=start_iso or None,
        execution_end_at=end_iso or None,
        execution_total_days=round(total, 4) if total is not None else None,
        execution_elapsed_days=round(elapsed, 4) if elapsed is not None else None,
        execution_remaining_days=round(remaining, 4) if remaining is not None else None,
        execution_elapsed_ratio=round(elapsed_ratio, 6) if elapsed_ratio is not None else None,
        execution_remaining_ratio=round(remaining_ratio, 6) if remaining_ratio is not None else None,
        execution_phase=phase,
        post_award_commercial_timing_value=timing_value,
        execution_timing_status=status,
        provenance=provenance,
    )


def classify_execution_phase(
    *,
    total_days: Optional[float],
    remaining_days: Optional[float],
    remaining_ratio: Optional[float],
) -> ExecutionPhase:
    if remaining_days is None:
        return ExecutionPhase.NOT_AVAILABLE
    rem = float(remaining_days)
    if rem <= 0:
        return ExecutionPhase.CLOSING
    ratio = remaining_ratio
    total = float(total_days) if total_days is not None else None

    if ratio is not None:
        if ratio <= PHASE_CLOSING_MAX_REMAINING_RATIO:
            return ExecutionPhase.CLOSING
        if rem <= PHASE_CLOSING_MAX_DAYS_SHORT_CONTRACT and ratio <= PHASE_CLOSING_MAX_REMAINING_RATIO * 1.5:
            return ExecutionPhase.CLOSING
        if (
            total is not None
            and total <= PHASE_CLOSING_SHORT_CONTRACT_MAX_DAYS
            and rem <= PHASE_CLOSING_MAX_DAYS_SHORT_CONTRACT
            and ratio <= PHASE_CLOSING_SHORT_RATIO
        ):
            return ExecutionPhase.CLOSING
        if rem <= PHASE_CLOSING_ABSOLUTE_DAYS and ratio <= PHASE_CLOSING_ABSOLUTE_RATIO:
            return ExecutionPhase.CLOSING
        if ratio <= PHASE_LATE_MAX_REMAINING_RATIO:
            return ExecutionPhase.LATE_EXECUTION
        if rem <= PHASE_LATE_ABSOLUTE_DAYS and ratio <= PHASE_LATE_ABSOLUTE_RATIO:
            return ExecutionPhase.LATE_EXECUTION
        if ratio <= PHASE_MID_MAX_REMAINING_RATIO:
            return ExecutionPhase.MID_EXECUTION
        return ExecutionPhase.EARLY_EXECUTION

    # Absolute-only fallback when ratio unknown
    if rem <= PHASE_CLOSING_ABSOLUTE_DAYS:
        return ExecutionPhase.CLOSING
    if rem <= PHASE_LATE_ABSOLUTE_DAYS:
        return ExecutionPhase.LATE_EXECUTION
    if rem <= 90:
        return ExecutionPhase.MID_EXECUTION
    return ExecutionPhase.EARLY_EXECUTION


def _absolute_runway_score(remaining_days: float) -> float:
    rem = float(remaining_days)
    if rem <= 0:
        return 0.0
    if rem >= 180:
        return 1.0
    if rem >= 90:
        return 0.75 + 0.25 * (rem - 90.0) / 90.0
    if rem >= 30:
        return 0.40 + 0.35 * (rem - 30.0) / 60.0
    if rem >= 14:
        return 0.20 + 0.20 * (rem - 14.0) / 16.0
    return max(0.03, rem / 70.0)


def _relative_runway_score(remaining_ratio: float) -> float:
    ratio = float(remaining_ratio)
    if ratio <= 0:
        return 0.0
    if ratio >= 0.70:
        return 1.0
    if ratio >= 0.40:
        return 0.55 + 0.45 * (ratio - 0.40) / 0.30
    if ratio >= 0.15:
        return 0.20 + 0.35 * (ratio - 0.15) / 0.25
    return max(0.02, ratio / 0.15 * 0.20)


def compute_post_award_commercial_timing_value(
    *,
    remaining_days: Optional[float],
    remaining_ratio: Optional[float],
    phase: ExecutionPhase,
) -> Optional[float]:
    if remaining_days is None:
        return None
    rem = float(remaining_days)
    if rem <= 0:
        return 0.0
    abs_score = _absolute_runway_score(rem)
    if remaining_ratio is not None:
        rel_score = _relative_runway_score(float(remaining_ratio))
        combined = 0.35 * abs_score + 0.65 * rel_score
        bottleneck = min(abs_score, rel_score)
        value = 100.0 * combined * (0.45 + 0.55 * bottleneck)
    else:
        value = 100.0 * abs_score * 0.75
    if phase == ExecutionPhase.CLOSING:
        value = min(value, 18.0)
    elif phase == ExecutionPhase.LATE_EXECUTION:
        value = min(value, 42.0)
    return round(max(0.0, min(100.0, value)), 4)


def category_execution_phase_fit(category: str, phase: ExecutionPhase) -> float:
    """Hook for future per-category execution-window calibration. Generic 1.0 in this WIP."""
    _ = category, phase
    return 1.0


def late_entry_hard_cap(clock: ExecutionClock) -> Tuple[Optional[CandidateMedal], Optional[str]]:
    if clock.execution_timing_status == "SUPPRESSED_SOURCE_SUSPECT":
        return None, None
    phase = clock.execution_phase
    ratio = clock.execution_remaining_ratio
    if phase == ExecutionPhase.CLOSING:
        return CandidateMedal.WOOD, "post_award_closing_execution_phase"
    if ratio is not None and ratio <= HARD_CAP_WOOD_MAX_REMAINING_RATIO:
        return CandidateMedal.WOOD, "post_award_execution_remaining_ratio_critical"
    return None, None


def clock_from_model_input(
    model_input: Dict[str, Any],
    *,
    source_data_quality: str = "OK",
    as_of: Optional[date] = None,
) -> ExecutionClock:
    suspect = str(source_data_quality or "").upper() == "SUSPECT"
    exec_suspect = suspect and execution_dates_suspect(model_input)
    return compute_execution_clock(
        execution_start_at=model_input.get("execution_start_at"),
        execution_end_at=model_input.get("execution_end_at"),
        delivery_start_at=model_input.get("delivery_start_at"),
        delivery_end_at=model_input.get("delivery_end_at"),
        contract_execution_start_at=model_input.get("contract_execution_start_at"),
        contract_execution_end_at=model_input.get("contract_execution_end_at"),
        execution_remaining_days=_as_float(model_input.get("execution_remaining_days")),
        as_of=as_of,
        suppress_suspect=exec_suspect,
    )


def clock_to_audit_dict(clock: ExecutionClock) -> Dict[str, Any]:
    return {
        "execution_start_at": clock.execution_start_at,
        "execution_end_at": clock.execution_end_at,
        "execution_total_days": clock.execution_total_days,
        "execution_elapsed_days": clock.execution_elapsed_days,
        "execution_remaining_days": clock.execution_remaining_days,
        "execution_elapsed_ratio": clock.execution_elapsed_ratio,
        "execution_remaining_ratio": clock.execution_remaining_ratio,
        "execution_phase": clock.execution_phase.value,
        "post_award_commercial_timing_value": clock.post_award_commercial_timing_value,
        "execution_timing_status": clock.execution_timing_status,
        "post_award_timing_version": clock.post_award_timing_version,
        "execution_clock_provenance": clock.provenance,
    }


def _clamp_ratio(v: float) -> float:
    return max(0.0, min(1.0, v))


def _as_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
