"""PROJECT LIFECYCLE V1 — project freshness authority (separate from DIRECT submission).

Two lifecycles must never be conflated (WIP PROJECT_LIFECYCLE_V1):

    PROCUREMENT LIFECYCLE: publication -> submission -> winner / awarded
    PROJECT LIFECYCLE:     design -> expertise -> construction -> fit-out -> completion

Product invariant:

    "ended tender" != "ended commercial opportunity"

for WORKS_WITH_EMBEDDED_PRODUCTS. A closed/awarded tender does not by itself close
the commercial window for an embedded supplier while the project is still being
built.

MVP gate (deliberately minimal, no expertise/phase engine):

    WORKS_WITH_EMBEDDED_PRODUCTS
    AND positive category signal
    AND project_end_date > today
    -> project considered active -> document admission = YES

PROJECT_LIFECYCLE_V2 (expertise, construction permits, actual works stage,
readiness percent, fit-out windows, optimal supplier entry) is explicitly NOT
part of this module.

Read-only and deterministic: no DB access, no model calls, never invents a date.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional, Tuple

from src.services.commercial_routing_v3.post_award_execution_timing import (
    ExecutionClock,
    compute_execution_clock,
)

PROJECT_LIFECYCLE_POLICY_VERSION = "project_lifecycle_v1_project_end_gate"

#: Track that means "works/project with embedded products".
PROJECT_TRACKS = frozenset({"EMBEDDED_MATERIAL"})

#: Canonical project window sources — audited existing fields, never submission.
PROJECT_START_SOURCE = (
    "crm_procurements.execution_start_at|delivery_start_date "
    "(canonical_card.contract_execution_start_at / execution clock start)"
)
PROJECT_END_SOURCE = (
    "crm_procurements.execution_end_at|delivery_end_date "
    "(canonical_card.contract_execution_end_at / execution clock end); "
    "submission_deadline_at / end_date are NEVER used as project end"
)

PROJECT_TIMING_POLICY = (
    "PROJECT_END_DATE_BASED: an active project (project_end >= today) uses project "
    "runway timing; submission-deadline decay is NOT applied to the project track"
)
PROJECT_DOCUMENT_ADMISSION_POLICY = (
    "track == EMBEDDED_MATERIAL AND has_positive_category_signal AND "
    "project_end_date > today -> document_admission = YES"
)

PROJECT_LIFECYCLE_V2_DEFERRED = (
    "expertise",
    "construction_permit",
    "actual_smr_stage",
    "readiness_percent",
    "fit_out_works",
    "optimal_supplier_entry_window",
)

REASON_PROJECT_ACTIVE = "PROJECT_ACTIVE"
REASON_PROJECT_COMPLETED = "PROJECT_COMPLETED"
REASON_PROJECT_END_UNKNOWN = "PROJECT_END_UNKNOWN"
REASON_NO_CATEGORY_SIGNAL = "NO_POSITIVE_CATEGORY_SIGNAL"
REASON_NOT_PROJECT_TRACK = "NOT_PROJECT_TRACK"

UI_TENDER_LABEL = "Торги"
UI_TENDER_STATUS_AWARDED = "завершены"
UI_TENDER_STATUS_OPEN = "идут"
UI_TENDER_STATUS_UNKNOWN = "неизвестно"
UI_PROJECT_STATUS_ACTIVE = "Активен"
UI_PROJECT_STATUS_INACTIVE = "Не активен"
UI_PROJECT_END_LABEL = "Проект активен до"
UI_PROJECT_END_UNKNOWN = "срок не определён"


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def is_project_track(track: Any) -> bool:
    """True for WORKS_WITH_EMBEDDED_PRODUCTS tracks."""
    return str(track or "").strip().upper() in PROJECT_TRACKS


def project_dates_from_source(proc: Dict[str, Any]) -> Tuple[Optional[date], Optional[date]]:
    """Return (project_start, project_end) from audited existing source fields.

    ``end_date`` is deliberately NOT a project-end fallback: for OPEN rows it is the
    submission window and must never masquerade as the project end.
    """
    start = _as_date(
        proc.get("execution_start_at")
        or proc.get("delivery_start_date")
        or proc.get("contract_execution_start_at")
    )
    end = _as_date(
        proc.get("execution_end_at")
        or proc.get("delivery_end_date")
        or proc.get("contract_execution_end_at")
    )
    return start, end


@dataclass(frozen=True)
class ProjectClock:
    project_start_at: Optional[str]
    project_end_at: Optional[str]
    remaining_project_days: Optional[float]
    remaining_project_ratio: Optional[float]
    project_total_days: Optional[float]
    project_active: bool
    timing_value: Optional[float]
    timing_source: str
    policy_version: str = PROJECT_LIFECYCLE_POLICY_VERSION

    def as_dict(self) -> Dict[str, Any]:
        return {
            "project_start_at": self.project_start_at,
            "project_end_at": self.project_end_at,
            "remaining_project_days": self.remaining_project_days,
            "remaining_project_ratio": self.remaining_project_ratio,
            "project_total_days": self.project_total_days,
            "project_active": self.project_active,
            "project_timing_value": self.timing_value,
            "project_timing_source": self.timing_source,
            "project_lifecycle_policy_version": self.policy_version,
        }


def compute_project_clock(
    proc_or_dates: Optional[Dict[str, Any]] = None,
    *,
    project_start_at: Any = None,
    project_end_at: Any = None,
    as_of: Optional[date] = None,
) -> ProjectClock:
    """Project runway clock from the canonical execution window.

    Fail-closed: when no project end exists the project is NOT active and no
    timing value is produced, so the caller keeps the existing DIRECT-style rule.
    """
    today = as_of or datetime.now(timezone.utc).date()
    if project_start_at is None and project_end_at is None and proc_or_dates:
        project_start_at, project_end_at = project_dates_from_source(proc_or_dates)

    end = _as_date(project_end_at)
    start = _as_date(project_start_at)
    if end is None and start is None:
        return ProjectClock(
            project_start_at=None,
            project_end_at=None,
            remaining_project_days=None,
            remaining_project_ratio=None,
            project_total_days=None,
            project_active=False,
            timing_value=None,
            timing_source="NOT_AVAILABLE",
        )

    clock: ExecutionClock = compute_execution_clock(
        execution_start_at=start,
        execution_end_at=end,
        as_of=today,
    )
    active = end is not None and end >= today
    return ProjectClock(
        project_start_at=clock.execution_start_at,
        project_end_at=clock.execution_end_at,
        remaining_project_days=clock.execution_remaining_days,
        remaining_project_ratio=clock.execution_remaining_ratio,
        project_total_days=clock.execution_total_days,
        project_active=bool(active),
        timing_value=clock.post_award_commercial_timing_value if active else 0.0,
        timing_source="PROJECT_END_DATE" if end is not None else "PROJECT_END_UNKNOWN",
    )


def evaluate_project_admission(
    *,
    track: Any,
    has_positive_category_signal: bool,
    project_clock: ProjectClock,
) -> Dict[str, Any]:
    """MVP project-active gate: category admission is a precondition, never bypassed.

    Order (WIP section 20): scope/track -> category admission -> project lifecycle
    admission -> scoring -> document admission. "Project active" alone never
    creates an opportunity.
    """
    if not is_project_track(track):
        return {
            "document_admission": False,
            "project_active": False,
            "reason": REASON_NOT_PROJECT_TRACK,
            "policy_version": PROJECT_LIFECYCLE_POLICY_VERSION,
        }
    if project_clock.project_end_at is None:
        return {
            "document_admission": False,
            "project_active": False,
            "reason": REASON_PROJECT_END_UNKNOWN,
            "policy_version": PROJECT_LIFECYCLE_POLICY_VERSION,
        }
    if not project_clock.project_active:
        return {
            "document_admission": False,
            "project_active": False,
            "reason": REASON_PROJECT_COMPLETED,
            "policy_version": PROJECT_LIFECYCLE_POLICY_VERSION,
        }
    if not has_positive_category_signal:
        return {
            "document_admission": False,
            "project_active": True,
            "reason": REASON_NO_CATEGORY_SIGNAL,
            "policy_version": PROJECT_LIFECYCLE_POLICY_VERSION,
        }
    return {
        "document_admission": True,
        "project_active": True,
        "reason": REASON_PROJECT_ACTIVE,
        "policy_version": PROJECT_LIFECYCLE_POLICY_VERSION,
    }


def project_ui_semantics(
    *,
    track: Any,
    lifecycle: Any,
    project_clock: Optional[ProjectClock] = None,
) -> Optional[Dict[str, Any]]:
    """UI vocabulary for the project track — never show submission as project life.

    Returns None for non-project tracks so DIRECT keeps its own vocabulary
    ("Подача до" / "Осталось времени").
    """
    if not is_project_track(track):
        return None
    lc = str(lifecycle or "").strip().upper()
    tender_status = {
        "AWARDED": UI_TENDER_STATUS_AWARDED,
        "WAITING_SOURCE_OUTCOME": UI_TENDER_STATUS_AWARDED,
        "OPEN": UI_TENDER_STATUS_OPEN,
    }.get(lc, UI_TENDER_STATUS_UNKNOWN)
    clock = project_clock
    return {
        "tender_label": UI_TENDER_LABEL,
        "tender_status": tender_status,
        "project_status": (
            UI_PROJECT_STATUS_ACTIVE if (clock and clock.project_active)
            else UI_PROJECT_STATUS_INACTIVE
        ),
        "project_end_label": UI_PROJECT_END_LABEL,
        "project_end": clock.project_end_at if clock else None,
        "project_end_display": (
            clock.project_end_at if (clock and clock.project_end_at)
            else UI_PROJECT_END_UNKNOWN
        ),
        "remaining_days": clock.remaining_project_days if clock else None,
    }
