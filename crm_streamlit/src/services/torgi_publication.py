"""Authoritative V3 publication contract for manager-visible «Идут торги» feed.

A projected procurement row is a source container — not an active lead.
Publication requires valid current assessment AND at least one CURRENT
commercially visible opportunity (ACTIVE / FOLLOW_UP_AWARDED).

Fail-closed: ambiguous or missing V3 schema → hide all (no legacy fallback).
"""
from __future__ import annotations

import json
import logging
from datetime import date
from enum import StrEnum
from typing import Any, Mapping, Optional, Sequence

from src.services.commercial_routing_v3.projection import (
    VISIBLE_OPPORTUNITY_STATES,
    active_feed_includes_procurement,
    opportunity_is_visible,
)

log = logging.getLogger(__name__)

TORGI_VISIBILITY_AUTHORITIES = 1
VISIBILITY_GATE_FAILS_CLOSED = True
RAW_PROJECTED_PROCUREMENT_IS_ACTIVE_LEAD = False

# SQL tuple for IN (...) — keep in sync with VISIBLE_OPPORTUNITY_STATES
_VISIBLE_STATES_SQL = tuple(sorted(VISIBLE_OPPORTUNITY_STATES))


class TorgiHideReason(StrEnum):
    SOURCE_LIFECYCLE = "SOURCE_LIFECYCLE"
    UNASSESSED = "UNASSESSED"
    FAILED = "FAILED"
    INCOMPLETE = "INCOMPLETE"
    MALFORMED = "MALFORMED"
    NO_VISIBLE_OPPORTUNITY = "NO_VISIBLE_OPPORTUNITY"
    SCHEMA_NOT_READY = "SCHEMA_NOT_READY"


def normalized_result_is_publication_valid(normalized_result: Any) -> bool:
    """Minimal schema gate aligned with effective_assessment._validate_normalized_result."""
    if normalized_result is None:
        return False
    if isinstance(normalized_result, str):
        try:
            normalized_result = json.loads(normalized_result)
        except Exception:
            return False
    if not isinstance(normalized_result, dict):
        return False
    return (
        "business_scope_status" in normalized_result
        or "category_opportunities" in normalized_result
        or "candidate_level" in normalized_result
    )


def assessment_publication_status(
    *,
    ai_row: Optional[Mapping[str, Any]],
) -> tuple[bool, Optional[TorgiHideReason]]:
    """Return (publishable, hide_reason). Fail-closed on missing/invalid assessment."""
    if ai_row is None:
        return False, TorgiHideReason.UNASSESSED
    raw_status = (ai_row.get("status") or "").upper()
    if raw_status in ("ERROR", "FAILED"):
        return False, TorgiHideReason.FAILED
    nr = ai_row.get("normalized_result")
    if not nr:
        return False, TorgiHideReason.INCOMPLETE
    if not normalized_result_is_publication_valid(nr):
        return False, TorgiHideReason.MALFORMED
    return True, None


def source_lifecycle_allows_torgi(
    *,
    crm_stage: str,
    award_status: str,
    end_date: Optional[date],
    today: Optional[date] = None,
) -> bool:
    today = today or date.today()
    if crm_stage != "torgi":
        return False
    if award_status != "submission_open":
        return False
    if end_date is None:
        return False
    return end_date >= today


def has_visible_current_opportunity(opportunities: Sequence[Mapping[str, Any]]) -> bool:
    return active_feed_includes_procurement(list(opportunities), v3_schema_ready=True)


def is_torgi_publication_visible(
    *,
    crm_stage: str,
    award_status: str,
    end_date: Optional[date],
    ai_row: Optional[Mapping[str, Any]],
    opportunities: Sequence[Mapping[str, Any]],
    v3_schema_ready: bool = True,
    today: Optional[date] = None,
) -> tuple[bool, Optional[TorgiHideReason]]:
    if not v3_schema_ready:
        return False, TorgiHideReason.SCHEMA_NOT_READY
    if not source_lifecycle_allows_torgi(
        crm_stage=crm_stage,
        award_status=award_status,
        end_date=end_date,
        today=today,
    ):
        return False, TorgiHideReason.SOURCE_LIFECYCLE
    ok, reason = assessment_publication_status(ai_row=ai_row)
    if not ok:
        return False, reason
    if not has_visible_current_opportunity(opportunities):
        return False, TorgiHideReason.NO_VISIBLE_OPPORTUNITY
    return True, None


def publication_schema_ready(crm_db) -> bool:
    """Minimum V3 tables/columns required for opportunity-gated publication."""
    try:
        if not crm_db.execute_scalar(
            "SELECT to_regclass('public.crm_procurement_category_opportunities') IS NOT NULL"
        ):
            return False
        rows = crm_db.execute_query(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'crm_procurement_category_opportunities'
              AND column_name = 'commercial_state'
            LIMIT 1
            """
        )
        return bool(rows)
    except Exception as exc:
        log.error("publication_schema_ready check failed: %s", exc)
        return False


def torgi_publication_sql_filters() -> str:
    """SQL AND-fragment (leading AND ...) for authoritative torgi publication."""
    states = ", ".join(f"'{s}'" for s in _VISIBLE_STATES_SQL)
    return f"""
                  AND EXISTS (
                      SELECT 1
                      FROM procurement_ai_assessments ai_pub
                      WHERE ai_pub.procurement_id = cp.id
                        AND ai_pub.is_current = TRUE
                        AND UPPER(COALESCE(ai_pub.status, '')) NOT IN ('ERROR', 'FAILED')
                        AND ai_pub.normalized_result IS NOT NULL
                        AND (
                          ai_pub.normalized_result ? 'business_scope_status'
                          OR ai_pub.normalized_result ? 'category_opportunities'
                          OR ai_pub.normalized_result ? 'candidate_level'
                        )
                  )
                  AND EXISTS (
                      SELECT 1
                      FROM crm_procurement_category_opportunities o_pub
                      WHERE o_pub.procurement_id = cp.id
                        AND o_pub.status = 'CURRENT'
                        AND o_pub.commercial_state IN ({states})
                  )"""


def is_preliminary_ai_layer_visible(
    *,
    is_confirmed: bool,
    publication_visible: bool,
) -> bool:
    """«Предварительно ИИ»: published + not expert-confirmed."""
    return publication_visible and not is_confirmed


def is_confirmed_layer_visible(
    *,
    is_confirmed: bool,
    publication_visible: bool,
) -> bool:
    """«Подтверждено»: published + expert confirmation on a current opportunity."""
    return publication_visible and is_confirmed


CONFIRMED_VISIBILITY_CONTRACT = (
    "Expert-confirmed procurements remain in the feed only when they pass the "
    "same torgi publication contract (open lifecycle + valid assessment + "
    "CURRENT opportunity in ACTIVE/FOLLOW_UP_AWARDED). Confirmation alone does "
    "not resurrect expired/closed procurements."
)

CURRENT_V3_VISIBILITY_HELPER = (
    "src.services.commercial_routing_v3.projection.active_feed_includes_procurement "
    "+ opportunity_is_visible (VISIBLE_OPPORTUNITY_STATES)"
)
CURRENT_V2_TORGI_GATE = (
    "crm_stage=torgi AND award_status=submission_open AND end_date>=CURRENT_DATE "
    "(tabs._load_torgi — no assessment/opportunity gate before Phase 4)"
)
SEMANTIC_GAP = (
    "V2 SQL gate treats every projected open procurement as a manager lead; "
    "V3 publication contract exists in projection.py but was not wired into torgi UI."
)
