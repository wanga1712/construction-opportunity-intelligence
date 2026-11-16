"""Targeted contract tests for BUSINESS_RESEARCH_ADMISSION_V2."""
from __future__ import annotations

from datetime import datetime, timezone

from src.services.commercial_routing_v3.business_research_admission import (
    ADMISSION_POLICY_VERSION,
    ELIGIBLE,
    EXCLUDED,
    HOLD,
    admission_contract,
    context_admission_fields,
    decide_admission,
    is_queue_eligible,
)


def test_runtime_admission_matrix_preserves_contract() -> None:
    assert decide_admission("OPEN", "DIRECT_GOODS") == (
        ELIGIBLE,
        "CURRENT_BUSINESS_ADMISSION",
    )
    assert decide_admission("OPEN", "WORKS_WITH_EMBEDDED_PRODUCTS")[0] == ELIGIBLE
    assert decide_admission("OPEN", "DESIGN_PROJECT")[0] == ELIGIBLE
    assert decide_admission("AWARDED", "DIRECT_GOODS") == (
        EXCLUDED,
        "AWARDED_DIRECT_GOODS",
    )
    assert decide_admission("AWARDED", "WORKS_WITH_EMBEDDED_PRODUCTS")[0] == ELIGIBLE
    assert decide_admission("AWARDED", "DESIGN_PROJECT")[0] == ELIGIBLE


def test_waiting_runtime_behavior_and_fail_closed_unknowns() -> None:
    for lifecycle in ("WAITING_SOURCE_OUTCOME", "WAITING_AWARD", "WAITING"):
        assert decide_admission(lifecycle, "DIRECT_GOODS")[0] == ELIGIBLE
    assert decide_admission("OPEN", "UNKNOWN") == (HOLD, "UNKNOWN_SCOPE")
    assert decide_admission("OPEN", "PURE_SERVICE") == (HOLD, "POLICY_UNDECIDED")
    assert decide_admission("UNKNOWN", "DIRECT_GOODS") == (
        HOLD,
        "POLICY_UNDECIDED",
    )


def test_contract_exposes_reason_code_and_policy_version() -> None:
    assert admission_contract("AWARDED", "DIRECT_GOODS") == {
        "admission_state": EXCLUDED,
        "reason_code": "AWARDED_DIRECT_GOODS",
        "admission_reason": "AWARDED_DIRECT_GOODS",
        "admission_policy_version": ADMISSION_POLICY_VERSION,
    }


def test_admission_is_isolated_from_prior_medal_and_document_fields() -> None:
    record = context_admission_fields(
        {
            "admission_state": ELIGIBLE,
            "admission_reason": "CURRENT_BUSINESS_ADMISSION",
            "admission_policy_version": ADMISSION_POLICY_VERSION,
            "research_prior_band": "GOLD",
            "commercial_medal": "GOLD",
            "document_confirmation": "CONFIRMED",
        }
    )
    assert record["admission_state"] == ELIGIBLE
    assert set(record) == {
        "admission_state",
        "admission_reason",
        "admission_policy_version",
        "admission_evaluated_at",
        "procurement_scope_type",
        "source_lifecycle",
    }


def test_json_safe_context_and_current_policy_claim_gate() -> None:
    fields = context_admission_fields(
        {
            "admission_state": ELIGIBLE,
            "admission_policy_version": ADMISSION_POLICY_VERSION,
            "admission_evaluated_at": datetime(2026, 11, 9, tzinfo=timezone.utc),
        }
    )
    assert fields["admission_evaluated_at"] == "2026-11-09T00:00:00+00:00"
    assert is_queue_eligible(fields) is True
    assert is_queue_eligible({"admission_state": ELIGIBLE}) is False
    assert is_queue_eligible({**fields, "admission_state": HOLD}) is False
