"""Canonical S7→S13 source lifecycle normalizer.

One function for analytics, projection, opportunity sync, and research-queue admission.

Temporal rule: an open/torgi source row whose submission deadline (end_date) has
already passed is WAITING_SOURCE_OUTCOME — CRM must not treat it as active OPEN
while waiting for daily status migration.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional, Union

from src.domain.commercial_opportunity_lifecycle import SourceLifecycleEvent

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
    # ISO date or datetime prefix
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
    """Map source identity + temporal deadline to SourceLifecycleEvent.

    Rules (canonical):
      awarded / razygranye                         → AWARDED
      commission_work / commission / award_not_found → WAITING_SOURCE_OUTCOME
        (award_not_found on open table with NULL end_date is UNKNOWN — see below)
      open/torgi AND end_date < as_of              → WAITING_SOURCE_OUTCOME
      open/torgi AND end_date >= as_of             → OPEN
      open/torgi AND end_date is NULL              → UNKNOWN
        (missing factual deadline is never silently OPEN)
    """
    table = (source_table or "").strip().lower()
    stage = (crm_stage or "").strip().lower()
    award = (award_status or "").strip().lower()
    today = as_of or date.today()
    deadline = _as_date(end_date)

    # AWARDED first (table or stage or status)
    if "awarded" in table or stage == "razygranye" or award == "awarded":
        return SourceLifecycleEvent.AWARDED

    # Explicit commission table/stage
    if "commission" in table or stage == "commission" or award == "commission":
        return SourceLifecycleEvent.WAITING_SOURCE_OUTCOME

    # award_not_found with known past deadline → waiting; with NULL → UNKNOWN
    if award == "award_not_found":
        if deadline is None:
            return SourceLifecycleEvent.UNKNOWN
        return SourceLifecycleEvent.WAITING_SOURCE_OUTCOME
    is_open_surface = (
        stage == "torgi"
        or award in ("submission_open", "submission_closed_waiting_award")
        or (
            table.startswith("reestr_contract_")
            and "commission" not in table
            and "awarded" not in table
            and "unclear" not in table
            and "completed" not in table
            and "unknown" not in table
        )
    )
    if is_open_surface:
        # Missing factual deadline is UNKNOWN — never silently OPEN.
        if deadline is None:
            return SourceLifecycleEvent.UNKNOWN
        if deadline < today:
            return SourceLifecycleEvent.WAITING_SOURCE_OUTCOME
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
        # Temporal waiting: row may still physically sit in open/torgi table.
        return "torgi", "submission_closed_waiting_award"
    if event == SourceLifecycleEvent.OPEN:
        return "torgi", "submission_open"
    # UNKNOWN: stored but not admitted to Идут торги / Комиссия feeds.
    return "torgi", "award_not_found"


def lifecycle_label_ru(event: SourceLifecycleEvent | str) -> str:
    key = event.value if isinstance(event, SourceLifecycleEvent) else str(event)
    return {
        SourceLifecycleEvent.OPEN.value: "Открытые (OPEN)",
        SourceLifecycleEvent.WAITING_SOURCE_OUTCOME.value: "Ожидание исхода (WAITING)",
        SourceLifecycleEvent.AWARDED.value: "Разыгранные (AWARDED)",
        SourceLifecycleEvent.TERMINAL_NO_RESULT.value: "Терминал без результата",
        SourceLifecycleEvent.UNKNOWN.value: "Неизвестно",
    }.get(key, key)
