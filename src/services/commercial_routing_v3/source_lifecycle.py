"""Canonical S7->S13 source lifecycle normalizer.

Lifecycle authority = the physical S7 status table (Phase 2 / Phase 3).
Temporal data (``end_date`` / deadline) NEVER changes lifecycle here; it is
used downstream only for timing / urgency / validation / anomaly signals.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional, Union

from src.domain.commercial_opportunity_lifecycle import SourceLifecycleEvent

DateLike = Union[date, datetime, str, None]

MAIN_44 = "reestr_contract_44_fz"
MAIN_223 = "reestr_contract_223_fz"

_TERMINAL_TOKENS = ("completed", "unclear", "unknown", "bad")


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


def normalize_source_lifecycle_event(
    *,
    source_table: str = "",
    crm_stage: str = "",
    award_status: str = "",
    end_date: DateLike = None,
    as_of: Optional[date] = None,
) -> SourceLifecycleEvent:
    """Map physical S7 status table -> SourceLifecycleEvent.

    reestr_contract_44_fz / reestr_contract_223_fz   -> OPEN
    *_commission_work                                -> WAITING_SOURCE_OUTCOME
    *_awarded                                        -> AWARDED
    *_unclear / *_completed / *_unknown / *_bad      -> TERMINAL_NO_RESULT (fail closed)
    anything else                                    -> UNKNOWN

    ``end_date`` / ``as_of`` are accepted for API compatibility only and do NOT
    affect the result (dates must not be a lifecycle authority).
    """
    table = (source_table or "").strip().lower()
    if table:
        if any(tok in table for tok in _TERMINAL_TOKENS):
            return SourceLifecycleEvent.TERMINAL_NO_RESULT
        if "awarded" in table:
            return SourceLifecycleEvent.AWARDED
        if "commission" in table:
            return SourceLifecycleEvent.WAITING_SOURCE_OUTCOME
        if table in (MAIN_44, MAIN_223):
            return SourceLifecycleEvent.OPEN
        return SourceLifecycleEvent.UNKNOWN

    # No physical table: use explicit projection hints only (never dates).
    stage = (crm_stage or "").strip().lower()
    award = (award_status or "").strip().lower()
    if stage == "razygranye" or award == "awarded":
        return SourceLifecycleEvent.AWARDED
    if stage == "commission" or award in ("commission", "award_not_found"):
        return SourceLifecycleEvent.WAITING_SOURCE_OUTCOME
    if stage == "torgi":
        return SourceLifecycleEvent.OPEN
    return SourceLifecycleEvent.UNKNOWN


def normalize_source_lifecycle_from_procurement(proc: Dict[str, Any]) -> SourceLifecycleEvent:
    return normalize_source_lifecycle_event(
        source_table=str(proc.get("source_table") or ""),
        crm_stage=str(proc.get("crm_stage") or ""),
        award_status=str(proc.get("award_status") or ""),
        end_date=proc.get("end_date"),
    )


def lifecycle_crm_stage_status(
    event: SourceLifecycleEvent,
    *,
    source_table: str = "",
) -> tuple[str, str]:
    """Map lifecycle event to crm_procurements (crm_stage, award_status)."""
    table = (source_table or "").strip().lower()
    if event == SourceLifecycleEvent.AWARDED:
        return "razygranye", "awarded"
    if event == SourceLifecycleEvent.WAITING_SOURCE_OUTCOME:
        if "commission" in table:
            return "commission", "commission"
        return "torgi", "submission_closed_waiting_award"
    if event == SourceLifecycleEvent.OPEN:
        return "torgi", "submission_open"
    if event == SourceLifecycleEvent.TERMINAL_NO_RESULT:
        return "commission", "terminal_no_result"
    return "torgi", "submission_open"


def lifecycle_label_ru(event: SourceLifecycleEvent | str) -> str:
    key = event.value if isinstance(event, SourceLifecycleEvent) else str(event)
    return {
        SourceLifecycleEvent.OPEN.value: "Открытые (OPEN)",
        SourceLifecycleEvent.WAITING_SOURCE_OUTCOME.value: "Ожидание исхода (WAITING)",
        SourceLifecycleEvent.AWARDED.value: "Разыгранные (AWARDED)",
        SourceLifecycleEvent.TERMINAL_NO_RESULT.value: "Терминал без результата",
        SourceLifecycleEvent.UNKNOWN.value: "Неизвестно",
    }.get(key, key)
