"""CRM-V3-ROUTING-CONTRACT-PRE-GOLDEN-BLOCKER-FIX-1 — unit/contract tests (no Qwen)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

from src.services.commercial_routing_v3.normalizer import normalize_v3_output
from src.services.commercial_routing_v3.routing_eligibility import (
    LANE_ACTIVE_OPEN,
    LANE_AWARDED_ADMITTED,
    LANE_WAITING_HOLD,
    evaluate_routing_eligibility,
    lease_expired,
)
from src.services.commercial_routing_v3.routing_runtime_config import (
    AUTOMATIC_V2_FALLBACK,
    MAX_ROUTING_ATTEMPTS,
    PRODUCTION_REQUIRES_V3,
    ROUTING_PROCESSING_LEASE_SEC,
    RoutingErrorClass,
    TRANSIENT_ERROR_CLASSES,
    WAITING_ROUTABLE,
)
from src.services.crm_ai_assessment_runner import (
    LOCK_ID,
    should_run_legacy_ai_when_v3_enabled,
)


ALLOWED = {"lighting", "computers", "waterproofing", "flooring"}


def _norm(raw: Dict[str, Any]) -> Dict[str, Any]:
    return normalize_v3_output(
        raw,
        allowed_categories=ALLOWED,
        allowed_subcategories={c: set() for c in ALLOWED},
        has_okpd=True,
    )


def test_v3_only_production_runner_no_v2_fallback() -> None:
    assert AUTOMATIC_V2_FALLBACK is False
    assert PRODUCTION_REQUIRES_V3 is True
    assert should_run_legacy_ai_when_v3_enabled(True) is False
    assert should_run_legacy_ai_when_v3_enabled(False) is False


def test_temporal_selector_active_open() -> None:
    tomorrow = (date.today() + timedelta(days=2)).isoformat()
    d = evaluate_routing_eligibility(
        {
            "auction_name": "Поставка светильников",
            "okpd_code": "27.40.1",
            "source_table": "reestr_contract_44_fz",
            "source_id": 1,
            "end_date": tomorrow,
            "crm_stage": "torgi",
            "award_status": "submission_open",
            "ai_assessment_status": "UNASSESSED",
            "ai_routing_attempt_count": 0,
        },
        priors=[{"okpd_pattern": "27.40", "match_type": "PREFIX", "commercial_category_code": "lighting", "active": True, "prior_weight": 70}],
    )
    assert d.selectable
    assert d.lane == LANE_ACTIVE_OPEN
    assert d.normalized_lifecycle == "OPEN"
    assert d.commercial_lane == "ACTIVE"


def test_expired_open_not_active() -> None:
    past = (date.today() - timedelta(days=5)).isoformat()
    d = evaluate_routing_eligibility(
        {
            "auction_name": "Поставка светильников",
            "okpd_code": "27.40.1",
            "source_table": "reestr_contract_44_fz",
            "source_id": 2,
            "end_date": past,
            "crm_stage": "torgi",
            "award_status": "submission_open",
            "ai_assessment_status": "UNASSESSED",
        },
        priors=[{"okpd_pattern": "27.40", "match_type": "PREFIX", "commercial_category_code": "lighting", "active": True}],
    )
    assert d.normalized_lifecycle == "WAITING_SOURCE_OUTCOME"
    assert d.lane != LANE_ACTIVE_OPEN
    if WAITING_ROUTABLE:
        assert d.selectable
        assert d.lane == LANE_WAITING_HOLD
        assert d.commercial_lane == "HOLD"
    else:
        assert not d.selectable


def test_waiting_policy() -> None:
    d = evaluate_routing_eligibility(
        {
            "auction_name": "Работы строительные",
            "okpd_code": "41.20",
            "source_table": "reestr_contract_44_fz_commission_work",
            "source_id": 3,
            "end_date": None,
            "crm_stage": "commission",
            "award_status": "commission",
            "ai_assessment_status": "UNASSESSED",
        },
        priors=[{"okpd_pattern": "41.2", "match_type": "PREFIX", "commercial_category_code": "flooring", "active": True}],
    )
    assert d.normalized_lifecycle == "WAITING_SOURCE_OUTCOME"
    assert d.commercial_lane == "HOLD"
    assert d.lane != LANE_ACTIVE_OPEN


def test_awarded_policy() -> None:
    d = evaluate_routing_eligibility(
        {
            "auction_name": "Капитальный ремонт",
            "okpd_code": "41.2",
            "source_table": "reestr_contract_44_fz_awarded",
            "source_id": 4,
            "end_date": None,
            "crm_stage": "razygranye",
            "award_status": "awarded",
            "ai_assessment_status": "UNASSESSED",
        },
        priors=[
            {"okpd_pattern": "41.2", "match_type": "EXACT", "commercial_category_code": "flooring", "active": True}
        ],
    )
    assert d.normalized_lifecycle == "AWARDED"
    assert d.selectable
    assert d.lane == LANE_AWARDED_ADMITTED


def test_rgk_unresolved_excluded() -> None:
    d = evaluate_routing_eligibility(
        {
            "auction_name": "x",
            "okpd_code": "27.40",
            "source_table": "rgk_contract_unresolved",
            "source_id": 9,
            "ai_assessment_status": "UNASSESSED",
        },
        priors=[],
    )
    assert not d.selectable
    assert d.reason == "RGK_UNRESOLVED"


def test_null_okpd_excluded() -> None:
    d = evaluate_routing_eligibility(
        {
            "auction_name": "Поставка",
            "okpd_code": "",
            "source_table": "reestr_contract_44_fz",
            "source_id": 5,
            "end_date": (date.today() + timedelta(days=3)).isoformat(),
            "ai_assessment_status": "UNASSESSED",
        },
        priors=[],
    )
    assert not d.selectable
    assert d.reason == "NULL_OKPD"


def test_placeholder_title_excluded() -> None:
    d = evaluate_routing_eligibility(
        {
            "auction_name": "(без названия)",
            "okpd_code": "27.40",
            "source_table": "reestr_contract_44_fz",
            "source_id": 6,
            "end_date": (date.today() + timedelta(days=3)).isoformat(),
            "ai_assessment_status": "UNASSESSED",
        },
        priors=[],
    )
    assert not d.selectable
    assert d.reason == "PLACEHOLDER_TITLE"


def test_completed_excluded_unless_force() -> None:
    base = {
        "auction_name": "Поставка ноутбука",
        "okpd_code": "26.20.11",
        "source_table": "reestr_contract_223_fz",
        "source_id": 7,
        "end_date": (date.today() - timedelta(days=1)).isoformat(),
        "ai_assessment_status": "COMPLETED",
        "ai_assessment_fingerprint": "abc",
        "current_fingerprint": "abc",
    }
    priors = [
        {"okpd_pattern": "26.20", "match_type": "PREFIX", "commercial_category_code": "computers", "active": True}
    ]
    d = evaluate_routing_eligibility(base, priors=priors)
    assert not d.selectable
    assert d.reason == "ALREADY_COMPLETED"
    d2 = evaluate_routing_eligibility(base, priors=priors, force_reassess=True)
    assert d2.selectable
    assert d2.reason == "FORCE_REASSESS"


def test_invalid_category_to_review() -> None:
    out = _norm(
        {
            "procurement_form": "SURVEY_AND_DESIGN",
            "commercial_category_hypotheses": [
                {
                    "category_code": "survey_and_design",
                    "opportunity_track": "DESIGN_REQUIREMENT",
                    "confidence": 0.9,
                    "research_action": "LIGHT_RESEARCH",
                    "candidate_medal": "WOOD",
                }
            ],
        }
    )
    assert out["commercial_category_hypotheses"] == []
    assert "survey_and_design" in out["rejected_category_codes"]
    assert out["empty_hypothesis_status"] == "REVIEW_REQUIRED"
    assert out["overall_research_action"] == "DISCOVER_COMMERCIAL_CATEGORY"
    assert out["discovery_required"] is True
    assert out["empty_hypothesis_status"] != "NO_COMMERCIAL_ENTRY"
    assert out["empty_hypothesis_status"] != "SILENT_EMPTY_INVALID"


def test_no_commercial_entry_not_forced_to_review() -> None:
    out = _norm(
        {
            "procurement_form": "SERVICES_OTHER",
            "commercial_category_hypotheses": [],
            "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
            "empty_hypothesis_reason_codes": ["no_sellable_category"],
            "preferred_opportunity_track": "NO_COMMERCIAL_ENTRY",
            "discovery_required": False,
            "overall_research_action": "SKIP",
        }
    )
    assert out["empty_hypothesis_status"] == "NO_COMMERCIAL_ENTRY"
    assert out["overall_research_action"] == "SKIP"
    assert out["discovery_required"] is False


def test_noncategory_dimension_block() -> None:
    out = _norm(
        {
            "procurement_form": "CONSTRUCTION_WORKS",
            "commercial_category_hypotheses": [
                {"category_code": "work_method", "opportunity_track": "EMBEDDED_MATERIAL", "confidence": 0.5},
                {"category_code": "material_family", "opportunity_track": "EMBEDDED_MATERIAL", "confidence": 0.5},
            ],
        }
    )
    assert out["commercial_category_hypotheses"] == []
    assert out["empty_hypothesis_status"] == "REVIEW_REQUIRED"
    assert set(out["rejected_category_codes"]) >= {"work_method", "material_family"}


def test_processing_lease() -> None:
    assert ROUTING_PROCESSING_LEASE_SEC >= 600
    now = datetime.now(timezone.utc)
    assert lease_expired(None, now=now) is True
    assert lease_expired(now - timedelta(seconds=ROUTING_PROCESSING_LEASE_SEC + 10), now=now) is True
    assert lease_expired(now - timedelta(seconds=60), now=now) is False


def test_stale_recovery_selectable() -> None:
    past = datetime.now(timezone.utc) - timedelta(seconds=ROUTING_PROCESSING_LEASE_SEC + 100)
    d = evaluate_routing_eligibility(
        {
            "auction_name": "Поставка",
            "okpd_code": "27.40",
            "source_table": "reestr_contract_44_fz",
            "source_id": 8,
            "end_date": (date.today() + timedelta(days=2)).isoformat(),
            "ai_assessment_status": "RUNNING",
            "ai_assessed_at": past,
            "ai_routing_attempt_count": 1,
        },
        priors=[{"okpd_pattern": "27.40", "match_type": "PREFIX", "commercial_category_code": "lighting", "active": True}],
    )
    assert d.selectable
    assert d.reason == "STALE_LEASE_RECLAIM"


def test_max_attempts() -> None:
    assert MAX_ROUTING_ATTEMPTS >= 2
    d = evaluate_routing_eligibility(
        {
            "auction_name": "Поставка",
            "okpd_code": "27.40",
            "source_table": "reestr_contract_44_fz",
            "source_id": 10,
            "end_date": (date.today() + timedelta(days=2)).isoformat(),
            "ai_assessment_status": "FAILED",
            "ai_routing_attempt_count": MAX_ROUTING_ATTEMPTS,
            "ai_routing_error_class": RoutingErrorClass.OLLAMA_TIMEOUT,
        },
        priors=[{"okpd_pattern": "27.40", "match_type": "PREFIX", "commercial_category_code": "lighting", "active": True}],
    )
    assert not d.selectable
    assert d.reason == "MAX_ATTEMPTS"


def test_retry_matrix() -> None:
    assert RoutingErrorClass.OLLAMA_TIMEOUT in TRANSIENT_ERROR_CLASSES
    assert RoutingErrorClass.OLLAMA_UNAVAILABLE in TRANSIENT_ERROR_CLASSES
    assert RoutingErrorClass.INVALID_JSON in TRANSIENT_ERROR_CLASSES
    assert RoutingErrorClass.UNEXPECTED_EXCEPTION in TRANSIENT_ERROR_CLASSES
    # nonretryable
    from src.services.commercial_routing_v3.routing_runtime_config import NONRETRYABLE_ERROR_CLASSES

    assert RoutingErrorClass.INVALID_CATEGORY in NONRETRYABLE_ERROR_CLASSES
    d = evaluate_routing_eligibility(
        {
            "auction_name": "Поставка",
            "okpd_code": "27.40",
            "source_table": "reestr_contract_44_fz",
            "source_id": 11,
            "end_date": (date.today() + timedelta(days=2)).isoformat(),
            "ai_assessment_status": "FAILED",
            "ai_routing_attempt_count": 1,
            "ai_routing_error_class": RoutingErrorClass.INVALID_CATEGORY,
        },
        priors=[{"okpd_pattern": "27.40", "match_type": "PREFIX", "commercial_category_code": "lighting", "active": True}],
    )
    assert not d.selectable
    assert "NONRETRYABLE" in d.reason


def test_concurrency_lock_id_stable() -> None:
    assert isinstance(LOCK_ID, int)
    assert LOCK_ID == 892341235612349014


def test_controlled_reassessment() -> None:
    base = {
        "auction_name": "Поставка ноутбука",
        "okpd_code": "26.20.11",
        "source_table": "reestr_contract_223_fz",
        "source_id": 603,
        "end_date": (date.today() - timedelta(days=1)).isoformat(),
        "ai_assessment_status": "COMPLETED",
        "ai_assessment_fingerprint": "x",
        "current_fingerprint": "x",
    }
    priors = [
        {"okpd_pattern": "26.20", "match_type": "PREFIX", "commercial_category_code": "computers", "active": True}
    ]
    assert evaluate_routing_eligibility(base, priors=priors).selectable is False
    assert evaluate_routing_eligibility(base, priors=priors, force_reassess=True).selectable is True


def test_v2_fallback_invariant() -> None:
    """V2_FALLBACK_TEST: legacy path never enabled by helper."""
    assert should_run_legacy_ai_when_v3_enabled(False) is False
