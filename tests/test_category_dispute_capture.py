"""Focused tests: HUMAN-CATEGORY-DISPUTE-CAPTURE-1 (capture-only, no DB)."""
from __future__ import annotations

import pytest

from src.services.category_dispute_service import (
    REASON_CODES,
    STATE_CANCELLED,
    STATE_NONE,
    STATE_PENDING_RECHECK,
    STATE_VERIFIED_CONFIRMED,
    STATE_VERIFIED_REJECTED,
    build_dispute_entry,
    cancel_dispute_entry,
    dispute_state_from_payload,
    is_pending,
    upsert_dispute_entry,
)


def _entry(cat, sub=None, reason="WRONG_PRODUCT_TYPE", comment="", created="2026-10-08T00:00:00+00:00"):
    return build_dispute_entry(
        category_code=cat, subcategory_code=sub, reason_code=reason,
        comment=comment, created_by="tester", created_at=created,
    )


def test_payload_contract_fields():
    e = _entry("computers", "all_in_one_computers")
    assert e["expert_action"] == "REQUEST_RECHECK"
    assert e["verification_state"] == STATE_PENDING_RECHECK
    assert e["reason_code"] in REASON_CODES
    for k in ("category_code", "subcategory_code", "reason_code", "comment",
              "model_assessment_id", "model_inference_run_id", "created_by", "created_at"):
        assert k in e


def test_invalid_reason_rejected():
    with pytest.raises(ValueError):
        build_dispute_entry(category_code="computers", reason_code="NOPE", created_by="t")


def test_upsert_is_category_specific_and_preserves_rest():
    payload = {
        "opportunities": [{"category_code": "computers"}],
        "expert_medal": "SILVER",
        "taxonomy_proposals": [{"x": 1}],
        "rejected_model_opportunities": [],
    }
    out = upsert_dispute_entry(payload, _entry("computers", "all_in_one_computers"))
    assert payload["rejected_model_opportunities"] == []          # input not mutated
    assert out["expert_medal"] == "SILVER"                        # medal untouched
    assert out["opportunities"] == payload["opportunities"]       # opportunity untouched
    assert len(out["rejected_model_opportunities"]) == 1
    assert "expert_category_scope" not in out                     # NOT global OUT_OF_CATEGORY


def test_multi_category_isolation_bridge():
    payload = {"rejected_model_opportunities": []}
    payload = upsert_dispute_entry(payload, _entry("lighting"))
    assert dispute_state_from_payload(payload, category_code="lighting", subcategory_code=None) == STATE_PENDING_RECHECK
    for other in ("waterproofing", "drainage_water_management", "composite_structures"):
        assert dispute_state_from_payload(payload, category_code=other, subcategory_code=None) == STATE_NONE
        assert is_pending(payload, category_code=other, subcategory_code=None) is False


def test_repeat_dispute_same_link_replaces_single_entry():
    payload = {"rejected_model_opportunities": []}
    payload = upsert_dispute_entry(payload, _entry("computers", "all_in_one_computers"))
    payload = upsert_dispute_entry(payload, _entry("computers", "all_in_one_computers", reason="WRONG_SUBCATEGORY"))
    entries = payload["rejected_model_opportunities"]
    assert len(entries) == 1
    assert entries[0]["reason_code"] == "WRONG_SUBCATEGORY"


def test_subcategory_is_part_of_key():
    payload = upsert_dispute_entry({"rejected_model_opportunities": []}, _entry("computers", "all_in_one_computers"))
    assert dispute_state_from_payload(payload, category_code="computers", subcategory_code=None) == STATE_NONE
    assert dispute_state_from_payload(payload, category_code="computers", subcategory_code="all_in_one_computers") == STATE_PENDING_RECHECK


def test_cancel_preserves_history_and_restores_none_pending():
    payload = upsert_dispute_entry({"rejected_model_opportunities": []}, _entry("computers", "all_in_one_computers"))
    cancelled = cancel_dispute_entry(payload, category_code="computers", subcategory_code="all_in_one_computers", created_by="t")
    assert cancelled is not None
    # history preserved: original pending + cancellation entry
    assert len(cancelled["rejected_model_opportunities"]) == 2
    assert dispute_state_from_payload(cancelled, category_code="computers", subcategory_code="all_in_one_computers") == STATE_CANCELLED
    assert is_pending(cancelled, category_code="computers", subcategory_code="all_in_one_computers") is False


def test_cancel_without_dispute_is_noop():
    assert cancel_dispute_entry({"rejected_model_opportunities": []}, category_code="computers", subcategory_code=None, created_by="t") is None


def test_verified_states_are_contract_ready():
    for state, expected in (("VERIFIED_REJECTED", STATE_VERIFIED_REJECTED), ("VERIFIED_CONFIRMED", STATE_VERIFIED_CONFIRMED)):
        payload = {"rejected_model_opportunities": [{
            "expert_action": "REQUEST_RECHECK", "category_code": "computers",
            "subcategory_code": None, "verification_state": state,
        }]}
        assert dispute_state_from_payload(payload, category_code="computers", subcategory_code=None) == expected


def test_none_state_when_absent():
    assert dispute_state_from_payload({}, category_code="computers", subcategory_code=None) == STATE_NONE
    assert dispute_state_from_payload(None, category_code="computers", subcategory_code=None) == STATE_NONE
