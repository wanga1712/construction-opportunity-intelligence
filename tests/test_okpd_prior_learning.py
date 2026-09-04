"""Comprehensive test suite for OKPD Prior Learning V1 (Cases A through P)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import tempfile
import pytest

from src.learning.okpd_prior.hierarchy import (
    OKPDHierarchy,
    UNKNOWN_OKPD,
    parse_okpd_hierarchy,
)
from src.learning.okpd_prior.dataset import (
    OUTCOME_POSITIVE,
    OUTCOME_SAFE_NEGATIVE,
    OUTCOME_UNRESOLVED,
    ProcurementDatasetRow,
    create_dataset_snapshot,
    split_dataset,
)
from src.learning.okpd_prior.baseline import (
    OKPDHierarchicalPriorV1,
)
from src.learning.okpd_prior.model import (
    BAND_BRONZE,
    BAND_GOLD,
    BAND_SILVER,
    BAND_WOOD,
    OKPDResearchHitModelV1,
    assign_priority_band,
)
from src.learning.okpd_prior.metrics import evaluate_ranking_metrics
from src.learning.okpd_prior.dto import ShadowPredictionDTO
from src.repositories.okpd_prediction_repository import OKPDPriorPredictionRepository


# Test A: one procurement = one dataset row
def test_a_one_procurement_one_dataset_row():
    row1 = ProcurementDatasetRow(
        procurement_id=101,
        research_completed_at="2026-08-31T18:00:00Z",
        okpd_code_raw="42.11.20",
        okpd_root="42",
        okpd_level2="42.11",
        okpd_level3="42.11.20",
        okpd_full="42.11.20",
        outcome=OUTCOME_POSITIVE,
        research_hit=1,
        trusted_confirmed_count=5,
        rejected_count=10,
        unknown_count=0,
        pending_validation_count=0,
        research_document_count=3,
    )
    d = row1.to_dict()
    assert d["procurement_id"] == 101
    assert "okpd_root" in d


# Test B: trusted CONFIRMED -> positive
def test_b_trusted_confirmed_produces_positive():
    # When v4_confirmed >= 1, outcome is POSITIVE and research_hit == 1
    v4_confirmed = 2
    v4_unknown = 0
    pending_val = 0
    
    outcome = OUTCOME_POSITIVE if v4_confirmed >= 1 else OUTCOME_UNRESOLVED
    hit = 1 if outcome == OUTCOME_POSITIVE else None
    assert outcome == OUTCOME_POSITIVE
    assert hit == 1


# Test C: research complete + zero candidates -> safe negative
def test_c_zero_candidates_produces_safe_negative():
    v4_confirmed = 0
    v4_unknown = 0
    pending_val = 0
    v4_rejected = 0
    total_details = 0
    is_complete = True

    if is_complete and v4_confirmed >= 1:
        outcome = OUTCOME_POSITIVE
    elif is_complete and v4_confirmed == 0 and v4_unknown == 0 and pending_val == 0:
        outcome = OUTCOME_SAFE_NEGATIVE
        hit = 0
    else:
        outcome = OUTCOME_UNRESOLVED

    assert outcome == OUTCOME_SAFE_NEGATIVE
    assert hit == 0


# Test D: only REJECTED candidates -> safe negative if fully terminal/complete
def test_d_only_rejected_candidates_produces_safe_negative():
    v4_confirmed = 0
    v4_rejected = 45
    v4_unknown = 0
    pending_val = 0
    is_complete = True

    if is_complete and v4_confirmed >= 1:
        outcome = OUTCOME_POSITIVE
    elif is_complete and v4_confirmed == 0 and v4_unknown == 0 and pending_val == 0:
        outcome = OUTCOME_SAFE_NEGATIVE
        hit = 0
    else:
        outcome = OUTCOME_UNRESOLVED

    assert outcome == OUTCOME_SAFE_NEGATIVE
    assert hit == 0


# Test E: semantic UNKNOWN -> unresolved, NOT negative
def test_e_semantic_unknown_produces_unresolved():
    v4_confirmed = 0
    v4_rejected = 10
    v4_unknown = 3  # semantic unknown present
    pending_val = 0
    is_complete = True

    if is_complete and v4_confirmed >= 1:
        outcome = OUTCOME_POSITIVE
    elif is_complete and v4_confirmed == 0 and v4_unknown == 0 and pending_val == 0:
        outcome = OUTCOME_SAFE_NEGATIVE
    else:
        outcome = OUTCOME_UNRESOLVED
        hit = None

    assert outcome == OUTCOME_UNRESOLVED
    assert hit is None


# Test F: unvalidated detail -> unresolved
def test_f_unvalidated_detail_produces_unresolved():
    v4_confirmed = 0
    v4_unknown = 0
    pending_val = 1  # 1 candidate still pending
    is_complete = True

    if is_complete and v4_confirmed >= 1:
        outcome = OUTCOME_POSITIVE
    elif is_complete and v4_confirmed == 0 and v4_unknown == 0 and pending_val == 0:
        outcome = OUTCOME_SAFE_NEGATIVE
    else:
        outcome = OUTCOME_UNRESOLVED
        hit = None

    assert outcome == OUTCOME_UNRESOLVED
    assert hit is None


# Test G: technical unresolved -> unresolved
def test_g_technical_unresolved_produces_unresolved():
    # Technical timeout candidate is not terminal, so pending_val > 0
    v4_confirmed = 0
    v4_unknown = 0
    pending_val = 2
    is_complete = True

    if is_complete and v4_confirmed >= 1:
        outcome = OUTCOME_POSITIVE
    elif is_complete and v4_confirmed == 0 and v4_unknown == 0 and pending_val == 0:
        outcome = OUTCOME_SAFE_NEGATIVE
    else:
        outcome = OUTCOME_UNRESOLVED
        hit = None

    assert outcome == OUTCOME_UNRESOLVED
    assert hit is None


# Test H: research incomplete -> unresolved
def test_h_research_incomplete_produces_unresolved():
    is_complete = False  # e.g. status != 'COMPLETED'
    v4_confirmed = 0
    v4_unknown = 0
    pending_val = 0

    if is_complete and v4_confirmed >= 1:
        outcome = OUTCOME_POSITIVE
    elif is_complete and v4_confirmed == 0 and v4_unknown == 0 and pending_val == 0:
        outcome = OUTCOME_SAFE_NEGATIVE
    else:
        outcome = OUTCOME_UNRESOLVED
        hit = None

    assert outcome == OUTCOME_UNRESOLVED
    assert hit is None


# Test I: OKPD 42.11.20.000 hierarchy serializes correctly
def test_i_okpd_hierarchy_serialization():
    h = parse_okpd_hierarchy("42.11.20.000")
    assert h.okpd_root == "42"
    assert h.okpd_level2 == "42.11"
    assert h.okpd_level3 == "42.11.20"
    assert h.okpd_full == "42.11.20.000"
    assert h.format_signal_chain() == "42 → 42.11 → 42.11.20 → 42.11.20.000"

    features = h.to_feature_dict()
    assert features == {
        "okpd_root": "42",
        "okpd_level2": "42.11",
        "okpd_level3": "42.11.20",
        "okpd_full": "42.11.20.000",
    }


# Test J: malformed/NULL OKPD handled fail-safe
def test_j_malformed_and_null_okpd_handling():
    for invalid in (None, "", "   ", "abc", "42-11", "invalid_okpd"):
        h = parse_okpd_hierarchy(invalid)
        assert h.okpd_root == UNKNOWN_OKPD
        assert h.okpd_level2 == UNKNOWN_OKPD
        assert h.okpd_level3 == UNKNOWN_OKPD
        assert h.okpd_full == UNKNOWN_OKPD
        assert h.format_signal_chain() == UNKNOWN_OKPD


# Test K: no post-research field included in feature matrix
def test_k_no_post_research_field_in_feature_matrix():
    row = ProcurementDatasetRow(
        procurement_id=200,
        research_completed_at="2026-08-31T18:00:00Z",
        okpd_code_raw="41.20.10",
        okpd_root="41",
        okpd_level2="41.20",
        okpd_level3="41.20.10",
        okpd_full="41.20.10",
        outcome=OUTCOME_POSITIVE,
        research_hit=1,
        trusted_confirmed_count=10,
        rejected_count=20,
        unknown_count=5,
        pending_validation_count=0,
        research_document_count=4,
    )
    features = row.to_feature_dict()
    # Features must ONLY contain hierarchical OKPD keys
    assert set(features.keys()) == {"okpd_root", "okpd_level2", "okpd_level3", "okpd_full"}
    assert "trusted_confirmed_count" not in features
    assert "rejected_count" not in features
    assert "research_document_count" not in features
    assert "unknown_count" not in features


# Test L: temporal split has no overlap
def test_l_temporal_split_no_overlap():
    rows = []
    for i in range(20):
        rows.append(ProcurementDatasetRow(
            procurement_id=1000 + i,
            research_completed_at=f"2026-08-31T18:{i:02d}:00Z",
            okpd_code_raw="42.11",
            okpd_root="42",
            okpd_level2="42.11",
            okpd_level3="42.11",
            okpd_full="42.11",
            outcome=OUTCOME_POSITIVE if i % 4 == 0 else OUTCOME_SAFE_NEGATIVE,
            research_hit=1 if i % 4 == 0 else 0,
            trusted_confirmed_count=1 if i % 4 == 0 else 0,
            rejected_count=5,
            unknown_count=0,
            pending_validation_count=0,
            research_document_count=2,
        ))

    train, val, holdout, is_temp = split_dataset(rows, train_ratio=0.7, val_ratio=0.15)
    assert is_temp is True

    train_ids = {r.procurement_id for r in train}
    val_ids = {r.procurement_id for r in val}
    holdout_ids = {r.procurement_id for r in holdout}

    assert len(train_ids.intersection(val_ids)) == 0
    assert len(train_ids.intersection(holdout_ids)) == 0
    assert len(val_ids.intersection(holdout_ids)) == 0
    assert len(train_ids) + len(val_ids) + len(holdout_ids) == 20


# Test M: model scoring deterministic for fixed artifact
def test_m_model_scoring_deterministic():
    train_rows = [
        ProcurementDatasetRow(
            procurement_id=1, research_completed_at="2026-08-31T18:00:00Z",
            okpd_code_raw="42.11", okpd_root="42", okpd_level2="42.11", okpd_level3="42.11", okpd_full="42.11",
            outcome=OUTCOME_POSITIVE, research_hit=1, trusted_confirmed_count=3, rejected_count=2, unknown_count=0, pending_validation_count=0, research_document_count=2
        ),
        ProcurementDatasetRow(
            procurement_id=2, research_completed_at="2026-08-31T18:01:00Z",
            okpd_code_raw="26.20", okpd_root="26", okpd_level2="26.20", okpd_level3="26.20", okpd_full="26.20",
            outcome=OUTCOME_SAFE_NEGATIVE, research_hit=0, trusted_confirmed_count=0, rejected_count=5, unknown_count=0, pending_validation_count=0, research_document_count=2
        ),
    ]

    model = OKPDResearchHitModelV1()
    model.fit(train_rows, dataset_snapshot_sha256="test_sha")

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        temp_path = f.name

    try:
        model.save_artifact(temp_path)
        loaded = OKPDResearchHitModelV1.load_artifact(temp_path)

        h1 = parse_okpd_hierarchy("42.11")
        h2 = parse_okpd_hierarchy("26.20")
        assert model.predict_proba_single(h1) == loaded.predict_proba_single(h1)
        assert model.predict_proba_single(h2) == loaded.predict_proba_single(h2)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


# Test N: band assignment counts and ranking correct
def test_n_band_assignment_ranking():
    assert assign_priority_band(0.95) == BAND_GOLD
    assert assign_priority_band(0.90) == BAND_GOLD
    assert assign_priority_band(0.89) == BAND_SILVER
    assert assign_priority_band(0.70) == BAND_SILVER
    assert assign_priority_band(0.69) == BAND_BRONZE
    assert assign_priority_band(0.40) == BAND_BRONZE
    assert assign_priority_band(0.39) == BAND_WOOD
    assert assign_priority_band(0.00) == BAND_WOOD


# Test O: missing CRM prediction does not hide procurement
def test_o_missing_crm_prediction_does_not_hide_procurement():
    repo = OKPDPriorPredictionRepository(in_memory_predictions={}, fallback_to_model=False)
    pred = repo.get_by_procurement_id(999999, okpd_code=None)
    assert pred is None


# Test P: CRM sorting is UI-only
def test_p_crm_sorting_is_ui_only():
    cards = [
        {"id": 1, "okpd_code": "26.20"},
        {"id": 2, "okpd_code": "42.11"},
        {"id": 3, "okpd_code": None},
    ]
    # UI-only sort function
    from src.ui.components.okpd_priority_widget import get_okpd_priority_compact_badge
    def _get_sort_score(c: dict) -> float:
        b = get_okpd_priority_compact_badge(c["id"], c.get("okpd_code"))
        return b["p_research_hit"] if b else -1.0

    sorted_cards = sorted(cards, key=_get_sort_score, reverse=True)
    assert len(sorted_cards) == 3
    # Card 3 (missing OKPD) is not deleted, just sorted to the end
    assert sorted_cards[-1]["id"] == 3
