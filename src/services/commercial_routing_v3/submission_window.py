"""Single pre-model authority for an actionable OPEN submission window."""
from __future__ import annotations
from datetime import date, datetime, timezone
from typing import Any

MIN_REMAINING_SUBMISSION_DAYS = 2
TOO_SHORT_REASON = "SUBMISSION_WINDOW_TOO_SHORT"


def remaining_submission_days(deadline: Any, *, now: datetime | None = None,
                              today: date | None = None) -> float | None:
    if deadline is None: return None
    now = now or datetime.now(timezone.utc); today = today or now.date()
    if isinstance(deadline, datetime):
        value = deadline if deadline.tzinfo else deadline.replace(tzinfo=timezone.utc)
        return (value - now).total_seconds() / 86400.0
    if isinstance(deadline, date): return float((deadline - today).days)
    text = str(deadline).strip()
    try:
        if "T" in text or " " in text:
            return remaining_submission_days(datetime.fromisoformat(text.replace("Z", "+00:00")), now=now, today=today)
        return float((date.fromisoformat(text[:10]) - today).days)
    except ValueError: return None


def is_actionable_submission_window(deadline: Any, *, now: datetime | None = None,
                                    today: date | None = None) -> bool:
    remaining = remaining_submission_days(deadline, now=now, today=today)
    return remaining is not None and remaining >= MIN_REMAINING_SUBMISSION_DAYS


def actionable_submission_sql(alias: str = "cp", column: str = "end_date") -> str:
    return f"{alias}.{column} >= CURRENT_DATE + INTERVAL '{MIN_REMAINING_SUBMISSION_DAYS} days'"
