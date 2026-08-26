"""Tests for first-stage product category gate."""
from __future__ import annotations

from src.services.annotation_category_gate import (
    CATEGORY_SCOPE_FIELD,
    FIRST_GATE_QUESTION,
    IN_CATEGORY,
    OUT_OF_CATEGORY,
    UNCERTAIN,
    build_in_category_payload,
    build_out_of_category_payload,
    build_uncertain_payload,
    compare_human_vs_model,
    is_legacy_negative_payload,
)
from src.services.annotation_state_service import (
    LEGACY_NOT_INTERESTING,
    REVIEWED,
    UNREVIEWED,
    annotation_state_counts,
    classify_annotation_payload,
    load_current_annotation_states,
)
from src.ui.components.analytics_v2.stage_workspace import FILTERS


def test_first_gate_wording_is_category_specific():
    assert "товарным категориям" in FIRST_GATE_QUESTION
    assert "профилю" not in FIRST_GATE_QUESTION.lower()
    assert any(key == OUT_OF_CATEGORY for key, _ in FILTERS)
    assert any("Старые" in label for _, label in FILTERS)


def test_out_of_category_payload_has_no_nce_authority():
    payload = build_out_of_category_payload(assessment={"id": 9}, created_by="tester")
    assert payload[CATEGORY_SCOPE_FIELD] == OUT_OF_CATEGORY
    assert payload.get("expert_category_codes") == []
    assert payload.get("expert_scope_verdict") is None
    assert payload.get("expert_medal") is None
    assert payload.get("expert_commercial_verdict") is None
    assert "OUT_OF_PROFILE" not in (payload.get("error_reasons") or [])


def test_in_category_requires_codes_and_persists_multiple():
    payload = build_in_category_payload(
        assessment=None,
        created_by="tester",
        category_codes=["CAT_A", "CAT_B"],
        category_names={"CAT_A": "Alpha", "CAT_B": "Beta"},
    )
    assert payload[CATEGORY_SCOPE_FIELD] == IN_CATEGORY
    assert payload["expert_category_codes"] == ["CAT_A", "CAT_B"]
    assert [o["category_code"] for o in payload["opportunities"]] == ["CAT_A", "CAT_B"]


def test_uncertain_stays_unresolved():
    payload = build_uncertain_payload(assessment=None, created_by="tester")
    assert payload[CATEGORY_SCOPE_FIELD] == UNCERTAIN
    assert payload["expert_category_codes"] == []


def test_legacy_negative_not_auto_converted():
    legacy = {
        "expert_scope_verdict": "OUT_OF_PROFILE",
        "expert_medal": "NCE",
        "expert_commercial_verdict": "NO_COMMERCIAL_ENTRY",
        "error_reasons": ["OUT_OF_PROFILE"],
    }
    assert is_legacy_negative_payload(legacy) is True
    assert is_legacy_negative_payload({**legacy, CATEGORY_SCOPE_FIELD: OUT_OF_CATEGORY}) is False


def test_counters_use_category_scope_reviewed_semantics():
    class DB:
        def execute_query(self, sql, params):
            return [
                {
                    "id": 1,
                    "procurement_id": 10,
                    "annotation_version": 1,
                    "created_at": "t",
                    "payload": {CATEGORY_SCOPE_FIELD: OUT_OF_CATEGORY},
                },
                {
                    "id": 2,
                    "procurement_id": 11,
                    "annotation_version": 1,
                    "created_at": "t",
                    "payload": {
                        CATEGORY_SCOPE_FIELD: IN_CATEGORY,
                        "expert_category_codes": ["X"],
                    },
                },
                {
                    "id": 3,
                    "procurement_id": 12,
                    "annotation_version": 1,
                    "created_at": "t",
                    "payload": {
                        "expert_medal": "NCE",
                        "expert_scope_verdict": "OUT_OF_PROFILE",
                    },
                },
            ]

    states = load_current_annotation_states([10, 11, 12, 13], DB())
    counts = annotation_state_counts(states)
    assert counts["ALL"] == counts[UNREVIEWED] + counts[REVIEWED] == 4
    assert counts[REVIEWED] == 2
    assert counts[UNREVIEWED] == 2
    assert counts[OUT_OF_CATEGORY] == 1
    assert counts[LEGACY_NOT_INTERESTING] == 1
    assert classify_annotation_payload({CATEGORY_SCOPE_FIELD: OUT_OF_CATEGORY}) == OUT_OF_CATEGORY


def test_model_comparison_is_partial_when_model_scope_missing():
    result = compare_human_vs_model(
        human_scope=OUT_OF_CATEGORY,
        human_codes=[],
        assessment={"normalized_result": {}},
    )
    assert result["comparison_mode"] == "PARTIAL"
    assert result["disagreement_type"] == "MODEL_SCOPE_UNAVAILABLE"
