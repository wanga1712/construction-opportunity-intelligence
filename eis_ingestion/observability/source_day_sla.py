"""SOURCE_DAY_24H_SLA checkpoint reader. No production DB. No secrets."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def processed_dates(path: Path) -> set[str]:
    data = load_json(path)
    if data is None:
        return set()
    if isinstance(data, dict):
        return set(data.keys())
    if isinstance(data, list):
        return {str(x) for x in data}
    return set()


def region_counts(path: Path) -> dict[str, int]:
    data = load_json(path)
    if not isinstance(data, dict):
        return {}
    out: dict[str, int] = {}
    for date_str, val in data.items():
        if isinstance(val, dict):
            regs = val.get("processed_regions", [])
            out[date_str] = len(regs) if isinstance(regs, list) else -1
        elif isinstance(val, list):
            out[date_str] = len(val)
        else:
            out[date_str] = -1
    return out


@dataclass(frozen=True)
class SourceDayStatus:
    date: str
    in_processed_dates: bool
    region_progress_count: int | None
    complete: bool
    reason: str


def source_day_status(
    date: str,
    processed_dates_file: Path,
    region_progress_file: Path,
) -> SourceDayStatus:
    """A source day is COMPLETE only after process_requests returns without
    exception and region_progress for that date is cleared.

    save_processed_date() exists in main.py but has no callers. Presence in
    processed_dates.json is therefore NOT the live completion signal.
    config.ini [eis] date is the cursor (written before work starts), not completion.
    """
    done = date in processed_dates(processed_dates_file)
    counts = region_counts(region_progress_file)
    n = counts.get(date)
    if n is None and not done:
        # No leftover region_progress and not in the unused processed_dates file:
        # cannot prove completion from checkpoints alone.
        return SourceDayStatus(
            date=date,
            in_processed_dates=False,
            region_progress_count=None,
            complete=False,
            reason="NO_CHECKPOINT_FOR_DATE",
        )
    if n is not None:
        return SourceDayStatus(
            date=date,
            in_processed_dates=done,
            region_progress_count=n,
            complete=False,
            reason="REGION_PROGRESS_PRESENT",
        )
    return SourceDayStatus(
        date=date,
        in_processed_dates=done,
        region_progress_count=None,
        complete=False,
        reason="PROCESSED_DATES_ONLY_DEAD_CODE",
    )


def sla_window_end(start: datetime, hours: int = 24) -> datetime:
    from datetime import timedelta

    return start + timedelta(hours=hours)
