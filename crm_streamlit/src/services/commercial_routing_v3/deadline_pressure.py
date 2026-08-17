"""Deterministic tender clock + deadline pressure (pre-LLM).

DEADLINE_PRESSURE_VERSION = V1
Formula:
  absolute_horizon_hours = 168 (configurable)
  absolute_pressure = clamp(1 - remaining_hours / absolute_horizon_hours, 0, 1)
  relative_pressure = elapsed_ratio  # clamped [0,1] for active presentation
  deadline_pressure = 100 * (0.50 * absolute_pressure + 0.50 * relative_pressure)

tender_clock_start_at:
  submission_start_at if present else published_at else NULL
  (never first_seen_at)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional, Union

DEADLINE_PRESSURE_VERSION = "V1"
DEADLINE_PRESSURE_FORMULA = (
    "deadline_pressure = 100 * (0.50 * clamp(1 - remaining_hours/absolute_horizon_hours, 0, 1)"
    " + 0.50 * elapsed_ratio); "
    "tender_clock_start = submission_start_at OR published_at; "
    "absolute_horizon_hours default 168"
)
DEFAULT_ABSOLUTE_HORIZON_HOURS = 168.0

DateLike = Union[date, datetime, str, None]


def _as_datetime(value: DateLike) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    try:
        if "T" in s or " " in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            d = date.fromisoformat(s[:10])
            dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class TenderClock:
    published_at: Optional[str]
    submission_start_at: Optional[str]
    submission_deadline_at: Optional[str]
    tender_clock_start_at: Optional[str]
    total_duration_seconds: Optional[float]
    elapsed_seconds: Optional[float]
    remaining_seconds: Optional[float]
    total_duration_hours: Optional[float]
    remaining_hours: Optional[float]
    remaining_days: Optional[float]
    elapsed_ratio: Optional[float]
    remaining_ratio: Optional[float]
    absolute_pressure: Optional[float]
    relative_pressure: Optional[float]
    deadline_pressure: Optional[float]
    absolute_horizon_hours: float
    deadline_pressure_version: str
    is_expired: bool
    as_of: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_tender_clock(
    *,
    published_at: DateLike = None,
    submission_start_at: DateLike = None,
    submission_deadline_at: DateLike = None,
    as_of: Optional[datetime] = None,
    absolute_horizon_hours: float = DEFAULT_ABSOLUTE_HORIZON_HOURS,
    active_urgency: bool = True,
    date_precision: str = "DATE_ONLY",
) -> TenderClock:
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    pub = _as_datetime(published_at)
    start = _as_datetime(submission_start_at) or pub
    deadline = _as_datetime(submission_deadline_at)

    # DATE_ONLY: treat deadline as end-of-day UTC; do not treat midnight as exact cut-off
    if date_precision == "DATE_ONLY" and deadline is not None:
        deadline = deadline.replace(hour=23, minute=59, second=59, microsecond=0)

    total_sec = elapsed_sec = remaining_sec = None
    elapsed_ratio = remaining_ratio = None
    abs_p = rel_p = pressure = None
    expired = False

    if start is not None and deadline is not None:
        total_sec = (deadline - start).total_seconds()
        if total_sec < 0:
            total_sec = 0.0
        elapsed_sec = (now - start).total_seconds()
        remaining_sec = (deadline - now).total_seconds()
        # For DATE_ONLY, expired only after calendar end_date
        if date_precision == "DATE_ONLY" and submission_deadline_at is not None:
            try:
                end_d = _as_datetime(submission_deadline_at).date()
                expired = now.date() > end_d
                if not expired and remaining_sec < 0:
                    remaining_sec = 0.0
            except Exception:
                expired = remaining_sec < 0
        else:
            expired = remaining_sec < 0
        if total_sec > 0:
            elapsed_ratio = _clamp(elapsed_sec / total_sec)
            remaining_ratio = _clamp(1.0 - elapsed_ratio)
        else:
            elapsed_ratio = 1.0 if expired else 0.0
            remaining_ratio = 0.0 if expired else 1.0

        if active_urgency and not expired:
            rem_h = remaining_sec / 3600.0
            abs_p = _clamp(1.0 - (rem_h / float(absolute_horizon_hours)))
            rel_p = float(elapsed_ratio or 0.0)
            pressure = 100.0 * (0.50 * abs_p + 0.50 * rel_p)
        else:
            abs_p = None
            rel_p = float(elapsed_ratio) if elapsed_ratio is not None else None
            pressure = None

    def _iso(dt: Optional[datetime]) -> Optional[str]:
        return dt.isoformat() if dt else None

    rem_h = (remaining_sec / 3600.0) if remaining_sec is not None else None
    return TenderClock(
        published_at=_iso(pub),
        submission_start_at=_iso(_as_datetime(submission_start_at)),
        submission_deadline_at=_iso(deadline),
        tender_clock_start_at=_iso(start),
        total_duration_seconds=total_sec,
        elapsed_seconds=elapsed_sec,
        remaining_seconds=remaining_sec,
        total_duration_hours=(total_sec / 3600.0) if total_sec is not None else None,
        remaining_hours=rem_h,
        remaining_days=(rem_h / 24.0) if rem_h is not None else None,
        elapsed_ratio=elapsed_ratio,
        remaining_ratio=remaining_ratio,
        absolute_pressure=abs_p,
        relative_pressure=rel_p,
        deadline_pressure=round(pressure, 4) if pressure is not None else None,
        absolute_horizon_hours=float(absolute_horizon_hours),
        deadline_pressure_version=DEADLINE_PRESSURE_VERSION,
        is_expired=expired,
        as_of=now.isoformat(),
    )
