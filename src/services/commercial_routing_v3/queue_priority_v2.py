"""Canonical Queue V2 priority / lifecycle policy (PHASE 4A).

Freshness and procurement stage dominate the medal:

    TIER 0 FRESH OPEN        -> live tender, submission window open
    TIER 1 LIVE PROJECT      -> awarded OBJECT/PROJECT whose execution window
                                is still open (submission window is irrelevant)
    TIER 2 BACKLOG           -> historical / catch-up

DIRECT after the submission window closed is NOT an acquisition target.
The two time axes (submission window vs project execution window) are never
mixed: ``project_dates_from_source`` deliberately excludes ``end_date``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional, Tuple

from .claim_freshness import TIER_BACKLOG, TIER_CHANGED, TIER_FRESH, compute_work_tier
from .post_award_execution_timing import compute_execution_clock
from .research_action_v2 import (
    GROUP_DESIGN,
    GROUP_DIRECT,
    GROUP_EMBEDDED,
    ResearchAction,
    track_group,
)

PRIORITY_POLICY_VERSION = "queue_priority_v2"

PHASE_RANK = {
    "EARLY_EXECUTION": 0,
    "MID_EXECUTION": 1,
    "LATE_EXECUTION": 2,
    "NOT_AVAILABLE": 3,
}
MEDAL_RANK = {"GOLD": 4, "SILVER": 3, "BRONZE": 2, "WOOD": 1}
TIMELINE_GUARD_DAYS = 5 * 365


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _ordinal(value: Optional[date]) -> int:
    return value.toordinal() if value else 0


@dataclass(frozen=True)
class QueuePriorityV2:
    work_tier: Optional[int]
    acquisition_allowed: bool
    track_group: str
    source_lifecycle: str
    project_active: bool
    project_end_at: Optional[str]
    project_remaining_days: Optional[float]
    execution_phase: str
    reason: str
    sort_key: Tuple = field(default=())
    policy_version: str = PRIORITY_POLICY_VERSION


def classify_source_lifecycle(crm_stage: Optional[str], award_status: Optional[str]) -> str:
    stage = (crm_stage or "").strip().lower()
    award = (award_status or "").strip().lower()
    if stage == "torgi" and award == "submission_open":
        return "OPEN"
    if stage == "razygranye" or award == "awarded":
        return "AWARDED"
    if stage == "commission":
        return "TERMINAL"
    if stage == "torgi":
        return "SUBMISSION_CLOSED"
    return "UNKNOWN"


def compute_queue_priority_v2(
    *,
    opportunity_track: Optional[str],
    crm_stage: Optional[str] = None,
    award_status: Optional[str] = None,
    source_status: Optional[str] = None,
    start_date: Any = None,
    end_date: Any = None,
    delivery_start_date: Any = None,
    delivery_end_date: Any = None,
    execution_start_at: Any = None,
    execution_end_at: Any = None,
    medal: Optional[str] = None,
    commercial_priority: Optional[int] = None,
    as_of: Optional[date] = None,
) -> QueuePriorityV2:
    """Deterministic TIER + project clock + sort key for one procurement."""
    today = as_of or datetime.now(timezone.utc).date()
    group = track_group(opportunity_track)
    lifecycle = (source_status or "").strip().upper() or classify_source_lifecycle(
        crm_stage, award_status
    )
    if lifecycle not in {"OPEN", "AWARDED", "SUBMISSION_CLOSED", "TERMINAL", "UNKNOWN"}:
        lifecycle = classify_source_lifecycle(crm_stage, award_status)
    stage = (crm_stage or "").strip().lower()
    award = (award_status or "").strip().lower()
    start = _as_date(start_date)
    end = _as_date(end_date)
    project_end = _as_date(delivery_end_date) or _as_date(execution_end_at)
    project_start = _as_date(delivery_start_date) or _as_date(execution_start_at)
    if project_start and project_end and (project_end - project_start).days > TIMELINE_GUARD_DAYS:
        project_end = None  # implausible source timeline -> fail closed
    project_active = bool(project_end and project_end >= today)
    clock = compute_execution_clock(
        execution_start_at=project_start,
        execution_end_at=project_end,
        as_of=today,
    )
    phase = clock.execution_phase.value if hasattr(clock.execution_phase, "value") else str(clock.execution_phase)
    remaining = clock.execution_remaining_days
    medal_rank = -MEDAL_RANK.get((medal or "").strip().upper(), 0)
    priority = -int(commercial_priority or 0)
    freshness = -_ordinal(start)

    if group == GROUP_DIRECT:
        if award == "awarded" or stage == "razygranye":
            return QueuePriorityV2(
                None, False, group, lifecycle, False, None, None, phase,
                "DIRECT_AWARDED_WINDOW_CLOSED",
            )
        if stage == "torgi" and award == "submission_closed_waiting_award":
            return QueuePriorityV2(
                None, False, group, lifecycle, False, None, None, phase,
                "DIRECT_SUBMISSION_CLOSED",
            )
        if stage == "commission":
            return QueuePriorityV2(
                None, False, group, lifecycle, False, None, None, phase,
                "DIRECT_TERMINAL",
            )
        tier = compute_work_tier(
            {"start_date": start_date, "end_date": end_date, "crm_stage": crm_stage, "award_status": award_status},
            today=today,
        )
        return QueuePriorityV2(
            tier, True, group, lifecycle, False, None, None, phase,
            "DIRECT_OPEN" if tier == TIER_FRESH else "DIRECT_OPEN_AGING",
            sort_key=(tier, freshness, 0, PHASE_RANK["NOT_AVAILABLE"], medal_rank, priority),
        )

    if group in (GROUP_EMBEDDED, GROUP_DESIGN):
        if stage == "commission":
            return QueuePriorityV2(
                None, False, group, lifecycle, project_active,
                project_end.isoformat() if project_end else None, remaining, phase,
                "PROJECT_TERMINAL",
            )
        if stage == "razygranye" or award == "awarded":
            if not project_active:
                return QueuePriorityV2(
                    None, False, group, lifecycle, False,
                    project_end.isoformat() if project_end else None, remaining, phase,
                    "PROJECT_CLOSED_NO_EXECUTION_WINDOW",
                )
            return QueuePriorityV2(
                TIER_CHANGED, True, group, lifecycle, True,
                project_end.isoformat() if project_end else None, remaining, phase,
                "AWARDED_ACTIVE_PROJECT_FOLLOW_UP",
                sort_key=(
                    TIER_CHANGED, 0, 0, PHASE_RANK.get(phase, 3), medal_rank, priority,
                ),
            )
        tier = compute_work_tier(
            {"start_date": start_date, "end_date": end_date, "crm_stage": crm_stage, "award_status": award_status},
            today=today,
        )
        if tier == TIER_FRESH:
            reason = "PROJECT_SUBMISSION_OPEN_FRESH"
        elif tier == TIER_CHANGED:
            reason = "PROJECT_SUBMISSION_CLOSED_LIVE"
        else:
            reason = "PROJECT_BACKLOG"
        return QueuePriorityV2(
            tier, True, group, lifecycle, project_active,
            project_end.isoformat() if project_end else None, remaining, phase, reason,
            sort_key=(
                tier,
                freshness if tier == TIER_FRESH else 0,
                0 if project_active else 1,
                PHASE_RANK.get(phase, 3),
                medal_rank,
                priority,
            ),
        )

    # UNKNOWN / NONE track: claimable but last, and still subject to the
    # project-window gate (an awarded project without runway is not live work).
    if (stage == "razygranye" or award == "awarded") and not project_active:
        return QueuePriorityV2(
            None, False, group, lifecycle, False,
            project_end.isoformat() if project_end else None, remaining, phase,
            "UNKNOWN_TRACK_AWARDED_NO_EXECUTION_WINDOW",
        )
    if stage == "commission":
        return QueuePriorityV2(
            None, False, group, lifecycle, project_active,
            project_end.isoformat() if project_end else None, remaining, phase,
            "UNKNOWN_TRACK_TERMINAL",
        )
    return QueuePriorityV2(
        TIER_BACKLOG, True, group, lifecycle, project_active,
        project_end.isoformat() if project_end else None, remaining, phase,
        "TRACK_UNKNOWN_BACKLOG",
        sort_key=(TIER_BACKLOG, 0, 0, PHASE_RANK.get(phase, 3), medal_rank, priority),
    )


def research_action_for_priority(priority: QueuePriorityV2, base_action: ResearchAction) -> ResearchAction:
    """Priority can only DOWNGRADE research (never upgrade)."""
    if not priority.acquisition_allowed:
        return ResearchAction.NO_DOCUMENT_RESEARCH
    return base_action
