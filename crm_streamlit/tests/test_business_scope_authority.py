"""Phase 5: business scope fail-closed contract."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from src.services.business_scope import (
    SCOPE_IN_PROFILE,
    SCOPE_OUT_OF_PROFILE,
    SCOPE_UNKNOWN,
    canonicalize_business_scope,
    effective_relevance_from_scope,
    replay_scope_with_provenance,
    resolve_pipeline_scope,
    scope_is_usable_for_publication,
)
from src.services.commercial_routing_v3.runtime_adapter import decision_to_normalized_result
from src.services.effective_assessment import _compute_effective_assessment
from src.services.torgi_publication import TorgiHideReason, is_torgi_publication_visible

_TODAY = date(2026, 8, 20)
_GOLDEN_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "reports"
    / "crm_v3_model_authority_restoration"
    / "GOLDEN_BAD_CASE_SNAPSHOT.json"
)
_EXPECTED_SHA = "e959ed6dd6a89d1e6adf2fc305e8ae6c12e01370957151489dbbcddb987f3d4c"


def test_missing_scope_unknown():
    assert canonicalize_business_scope(None) == SCOPE_UNKNOWN
    assert resolve_pipeline_scope(model_payload=None) == SCOPE_UNKNOWN
    assert resolve_pipeline_scope(model_payload={}) == SCOPE_UNKNOWN


def test_null_and_empty_and_invalid_scope_unknown():
    assert canonicalize_business_scope(None) == SCOPE_UNKNOWN
    assert canonicalize_business_scope("") == SCOPE_UNKNOWN
    assert canonicalize_business_scope("   ") == SCOPE_UNKNOWN
    assert canonicalize_business_scope("not-a-scope") == SCOPE_UNKNOWN
    assert canonicalize_business_scope("UNASSESSED") == SCOPE_UNKNOWN


def test_explicit_in_and_out_of_profile_preserved():
    assert canonicalize_business_scope("IN_PROFILE") == SCOPE_IN_PROFILE
    assert canonicalize_business_scope("in_profile") == SCOPE_IN_PROFILE
    assert canonicalize_business_scope("OUT_OF_PROFILE") == SCOPE_OUT_OF_PROFILE


def test_effective_assessment_does_not_default_missing_to_in_profile():
    ea = _compute_effective_assessment(
        1,
        {
            "status": "SUCCESS",
            "normalized_result": {"candidate_level": "WOOD"},
        },
        None,
        [],
    )
    assert ea.ai_status == "ASSESSED"
    assert ea.business_relevance == SCOPE_UNKNOWN


def test_effective_assessment_preserves_explicit_scopes():
    inn = _compute_effective_assessment(
        1,
        {"status": "SUCCESS", "normalized_result": {"business_scope_status": "IN_PROFILE"}},
        None,
        [],
    )
    out = _compute_effective_assessment(
        2,
        {"status": "SUCCESS", "normalized_result": {"business_scope_status": "OUT_OF_PROFILE"}},
        None,
        [],
    )
    assert inn.business_relevance == SCOPE_IN_PROFILE
    assert out.business_relevance == SCOPE_OUT_OF_PROFILE


def test_runtime_adapter_does_not_hardcode_in_profile():
    nr = decision_to_normalized_result(decision={}, procurement={"id": 1})
    assert nr["business_scope_status"] != SCOPE_IN_PROFILE
    assert nr["business_scope_status"] == SCOPE_UNKNOWN


def test_runner_does_not_hardcode_in_profile_from_categories():
    # Former gate: proposed_cats or discovery → IN_PROFILE
    assert (
        resolve_pipeline_scope(
            route_profile="CONSTRUCTION_INFRASTRUCTURE",
            model_payload={"expected_categories": ["waterproofing"], "discovery_required": True},
        )
        == SCOPE_UNKNOWN
    )
    assert resolve_pipeline_scope(route_profile="EXCLUDED", model_payload=None) == SCOPE_OUT_OF_PROFILE
    assert (
        resolve_pipeline_scope(
            route_profile="X",
            model_payload={"business_scope_status": "IN_PROFILE"},
        )
        == SCOPE_IN_PROFILE
    )


def test_unknown_scope_cannot_become_positive_relevance():
    assert effective_relevance_from_scope(SCOPE_UNKNOWN) == SCOPE_UNKNOWN
    assert effective_relevance_from_scope(None) == SCOPE_UNKNOWN
    assert effective_relevance_from_scope("HIGH") == SCOPE_UNKNOWN
    assert effective_relevance_from_scope(SCOPE_IN_PROFILE) == SCOPE_IN_PROFILE


def test_visibility_fails_closed_when_scope_unusable():
    ok, reason = is_torgi_publication_visible(
        crm_stage="torgi",
        award_status="submission_open",
        end_date=_TODAY + timedelta(days=3),
        ai_row={"status": "SUCCESS", "normalized_result": {"candidate_level": "GOLD"}},
        opportunities=[{"status": "CURRENT", "commercial_state": "ACTIVE"}],
        today=_TODAY,
    )
    assert ok is False
    assert reason == TorgiHideReason.SCOPE_UNKNOWN
    assert scope_is_usable_for_publication(SCOPE_UNKNOWN) is False
    assert scope_is_usable_for_publication(SCOPE_IN_PROFILE) is True


def test_golden_python_hardcoded_scope_no_longer_in_profile():
    raw = _GOLDEN_PATH.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    assert data.get("GOLDEN_SNAPSHOT_SHA256") == _EXPECTED_SHA
    in_profile_after = []
    for case in data["cases"]:
        prov = (case.get("provenance_labels") or {}).get("business_scope_status")
        stored = (case.get("assessment") or {}).get("normalized_result") or {}
        stored_scope = stored.get("business_scope_status")
        new_scope = replay_scope_with_provenance(stored_scope, prov)
        if (prov or "").upper() == "PYTHON_HARDCODE" and new_scope == SCOPE_IN_PROFILE:
            in_profile_after.append(case["procurement_id"])
    assert in_profile_after == []
