"""ONE canonical production routing eligibility contract.

Consumed by crm_ai_assessment_runner.fetch_candidates / controlled reassess.
Uses normalize_source_lifecycle_event — physical OPEN ≠ ACTIVE when deadline past.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from src.services.commercial_routing_v3.okpd_priors import match_okpd_priors
from src.services.commercial_routing_v3.procurement_form import classify_procurement_form
from src.services.commercial_routing_v3.routing_runtime_config import (
    MAX_ROUTING_ATTEMPTS,
    ROUTING_PROCESSING_LEASE_SEC,
    WAITING_ROUTABLE,
)
from src.services.commercial_routing_v3.source_contour import resolve_source_contour
from src.services.commercial_routing_v3.source_lifecycle import (
    normalize_source_lifecycle_event,
)
from src.services.commercial_routing_v3.submission_window import (
    TOO_SHORT_REASON, is_actionable_submission_window,
)

PLACEHOLDER_TITLES = frozenset(
    {"", "(без названия)", "без названия", "не указано", "н/д", "null"}
)

LANE_ACTIVE_OPEN = "ACTIVE_OPEN"
LANE_WAITING_HOLD = "WAITING_HOLD"
LANE_AWARDED_ADMITTED = "AWARDED_ADMITTED"
LANE_REVIEW_DISCOVERY = "REVIEW_DISCOVERY"


@dataclass(frozen=True)
class RoutingEligibilityDecision:
    selectable: bool
    lane: Optional[str]
    reason: str
    normalized_lifecycle: str
    source_valid: bool
    commercial_lane: str  # ACTIVE | HOLD | AWARDED | NONE
    attempt_count: int
    status: str


def _placeholder(title: Any) -> bool:
    return str(title or "").strip().lower() in PLACEHOLDER_TITLES


def _as_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return None


def lease_expired(ai_assessed_at: Any, *, now: Optional[datetime] = None) -> bool:
    started = _as_dt(ai_assessed_at)
    if started is None:
        return True
    now = now or datetime.now(timezone.utc)
    return (now - started).total_seconds() > ROUTING_PROCESSING_LEASE_SEC


def source_integrity_ok(proc: Dict[str, Any]) -> tuple[bool, str]:
    okpd = str(proc.get("okpd_code") or "").strip()
    title = proc.get("auction_name") or proc.get("title")
    st = str(proc.get("source_table") or "").strip()
    sid = proc.get("source_id")
    if not okpd:
        return False, "NULL_OKPD"
    if _placeholder(title):
        return False, "PLACEHOLDER_TITLE"
    if not st or sid is None:
        return False, "MISSING_SOURCE_IDENTITY"
    if "rgk_contract_unresolved" in st.lower():
        return False, "RGK_UNRESOLVED"
    contour = resolve_source_contour(source_table=st)
    if getattr(contour, "value", str(contour)) == "UNKNOWN":
        return False, "UNKNOWN_CONTOUR"
    return True, "OK"


def evaluate_routing_eligibility(
    proc: Dict[str, Any],
    *,
    priors: Optional[list] = None,
    force_reassess: bool = False,
    now: Optional[datetime] = None,
    as_of: Optional[date] = None,
) -> RoutingEligibilityDecision:
    """Canonical production eligibility. force_reassess bypasses COMPLETED gate only."""
    now = now or datetime.now(timezone.utc)
    as_of = as_of or now.date()
    status = str(proc.get("ai_assessment_status") or "UNASSESSED").upper()
    attempts = int(proc.get("ai_routing_attempt_count") or 0)
    ok, why = source_integrity_ok(proc)
    lifecycle = normalize_source_lifecycle_event(
        source_table=str(proc.get("source_table") or ""),
        crm_stage=str(proc.get("crm_stage") or ""),
        award_status=str(proc.get("award_status") or ""),
        end_date=proc.get("end_date"),
        as_of=as_of,
    ).value

    if not ok:
        return RoutingEligibilityDecision(
            False, None, why, lifecycle, False, "NONE", attempts, status
        )

    if bool(proc.get("manual_override")):
        return RoutingEligibilityDecision(
            False, None, "MANUAL_OVERRIDE", lifecycle, True, "NONE", attempts, status
        )

    form = classify_procurement_form(
        {
            "auction_name": proc.get("auction_name") or proc.get("title"),
            "okpd_code": proc.get("okpd_code"),
            "okpd_name": proc.get("okpd_name"),
        }
    )
    okpd = str(proc.get("okpd_code") or "").strip()
    matched = match_okpd_priors(okpd, priors or []) if priors is not None else []
    has_prior = bool(matched)
    designish = form.value in (
        "DESIGN_ONLY",
        "SURVEY_AND_DESIGN",
        "DESIGN_AND_BUILD",
        "DESIGN_EXPERTISE_AND_BUILD",
    )

    # Lane from normalized lifecycle (never physical table alone)
    if lifecycle == "OPEN":
        if not is_actionable_submission_window(proc.get("end_date"), now=now, today=as_of):
            return RoutingEligibilityDecision(
                False, None, TOO_SHORT_REASON, lifecycle, True, "NONE", attempts, status
            )
        lane, commercial = LANE_ACTIVE_OPEN, "ACTIVE"
    elif lifecycle == "WAITING_SOURCE_OUTCOME":
        if not WAITING_ROUTABLE:
            return RoutingEligibilityDecision(
                False, None, "WAITING_NOT_ROUTABLE", lifecycle, True, "HOLD", attempts, status
            )
        lane, commercial = LANE_WAITING_HOLD, "HOLD"
    elif lifecycle == "AWARDED":
        if not has_prior and not designish:
            return RoutingEligibilityDecision(
                False, None, "AWARDED_NO_PRIOR", lifecycle, True, "AWARDED", attempts, status
            )
        lane, commercial = LANE_AWARDED_ADMITTED, "AWARDED"
    else:
        return RoutingEligibilityDecision(
            False, None, "LIFECYCLE_UNKNOWN", lifecycle, True, "NONE", attempts, status
        )

    if designish and not has_prior and lane != LANE_ACTIVE_OPEN:
        # discovery lane label when design without prior
        if lane == LANE_WAITING_HOLD or lane == LANE_AWARDED_ADMITTED:
            lane = LANE_REVIEW_DISCOVERY

    # Assessment state
    if force_reassess:
        return RoutingEligibilityDecision(
            True, lane, "FORCE_REASSESS", lifecycle, True, commercial, attempts, status
        )

    if status == "RUNNING":
        if lease_expired(proc.get("ai_assessed_at"), now=now):
            # reclaimable — treated as selectable (caller should mark STALE first)
            return RoutingEligibilityDecision(
                True, lane, "STALE_LEASE_RECLAIM", lifecycle, True, commercial, attempts, status
            )
        return RoutingEligibilityDecision(
            False, None, "RUNNING_LEASE_ACTIVE", lifecycle, True, commercial, attempts, status
        )

    if status == "COMPLETED":
        fp = proc.get("ai_assessment_fingerprint")
        cur = proc.get("current_fingerprint")
        if cur and fp and cur != fp:
            return RoutingEligibilityDecision(
                True, lane, "FINGERPRINT_CHANGED", lifecycle, True, commercial, attempts, status
            )
        if proc.get("reassessment_requested"):
            return RoutingEligibilityDecision(
                True, lane, "REASSESSMENT_REQUESTED", lifecycle, True, commercial, attempts, status
            )
        return RoutingEligibilityDecision(
            False, None, "ALREADY_COMPLETED", lifecycle, True, commercial, attempts, status
        )

    if status == "NEEDS_REVIEW":
        return RoutingEligibilityDecision(
            False, None, "NEEDS_REVIEW_HOLD", lifecycle, True, commercial, attempts, status
        )

    if status in ("FAILED", "STALE"):
        if attempts >= MAX_ROUTING_ATTEMPTS:
            return RoutingEligibilityDecision(
                False, None, "MAX_ATTEMPTS", lifecycle, True, commercial, attempts, status
            )
        err = str(proc.get("ai_routing_error_class") or "")
        from src.services.commercial_routing_v3.routing_runtime_config import (
            NONRETRYABLE_ERROR_CLASSES,
            failed_retry_backoff_sec,
        )

        if err in NONRETRYABLE_ERROR_CLASSES and status == "FAILED":
            return RoutingEligibilityDecision(
                False, None, f"NONRETRYABLE:{err}", lifecycle, True, commercial, attempts, status
            )
        if status == "FAILED":
            assessed_at = proc.get("ai_assessed_at")
            if assessed_at is not None:
                if getattr(assessed_at, "tzinfo", None) is None:
                    assessed_at = assessed_at.replace(tzinfo=timezone.utc)
                age = (now - assessed_at).total_seconds()
                need = failed_retry_backoff_sec(attempts)
                if age < need:
                    return RoutingEligibilityDecision(
                        False,
                        None,
                        "FAILED_BACKOFF",
                        lifecycle,
                        True,
                        commercial,
                        attempts,
                        status,
                    )
        return RoutingEligibilityDecision(
            True, lane, f"RETRY_{status}", lifecycle, True, commercial, attempts, status
        )

    if status in ("UNASSESSED", "QUEUED", ""):
        return RoutingEligibilityDecision(
            True, lane, "PENDING", lifecycle, True, commercial, attempts, status
        )

    return RoutingEligibilityDecision(
        False, None, f"STATUS_{status}", lifecycle, True, commercial, attempts, status
    )


# Public alias for reports
CANONICAL_ROUTING_ELIGIBILITY_FUNCTION = (
    "src.services.commercial_routing_v3.routing_eligibility.evaluate_routing_eligibility"
)
