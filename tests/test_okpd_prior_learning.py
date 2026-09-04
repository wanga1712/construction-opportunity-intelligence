"""Comprehensive test suite for OKPD Prior Learning V1 (Cases A through R)."""

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
    resolve_research_outcome,
    split_dataset,
)
from src.learning.okpd_prior.baseline import (
    BASELINE_MODEL_NAME,
    OKPDHierarchicalPriorV1,
)
from src.learning.okpd_prior.model import (
    BAND_BRONZE,
    BAND_GOLD,
    BAND_SILVER,
    BAND_WOOD,
    FEATURE_NAMES,
    MODEL_NAME,
    MODEL_TYPE,
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


# Test B: trusted CONFIRMED -> positive (via resolve_research_outcome)
def test_b_trusted_confirmed_produces_positive():
    outcome, hit = resolve_research_outcome(
        research_complete=True,
        trusted_confirmed_count=2,
        semantic_unknown_count=0,
        pending_validation_count=0,
        technical_gap_count=0,
    )
    assert outcome == OUTCOME_POSITIVE
    assert hit == 1


# Test C: research complete + zero candidates -> safe negative (via resolve_research_outcome)
def test_c_zero_candidates_produces_safe_negative():
    outcome, hit = resolve_research_outcome(
        research_complete=True,
        trusted_confirmed_count=0,
        semantic_unknown_count=0,
        pending_validation_count=0,
        technical_gap_count=0,
    )
    assert outcome == OUTCOME_SAFE_NEGATIVE
    assert hit == 0


# Test D: only REJECTED candidates -> safe negative if fully terminal/complete (via resolve_research_outcome)
def test_d_only_rejected_candidates_produces_safe_negative():
    outcome, hit = resolve_research_outcome(
        research_complete=True,
        trusted_confirmed_count=0,
        semantic_unknown_count=0,
        pending_validation_count=0,
        technical_gap_count=0,
    )
    assert outcome == OUTCOME_SAFE_NEGATIVE
    assert hit == 0


# Test E: semantic UNKNOWN -> unresolved, NOT negative (via resolve_research_outcome)
def test_e_semantic_unknown_produces_unresolved():
    outcome, hit = resolve_research_outcome(
        research_complete=True,
        trusted_confirmed_count=0,
        semantic_unknown_count=3,
        pending_validation_count=0,
        technical_gap_count=0,
    )
    assert outcome == OUTCOME_UNRESOLVED
    assert hit is None


# Test F: unvalidated detail -> unresolved (via resolve_research_outcome)
def test_f_unvalidated_detail_produces_unresolved():
    outcome, hit = resolve_research_outcome(
        research_complete=True,
        trusted_confirmed_count=0,
        semantic_unknown_count=0,
        pending_validation_count=1,
        technical_gap_count=0,
    )
    assert outcome == OUTCOME_UNRESOLVED
    assert hit is None


# Test G: technical unresolved -> unresolved (via resolve_research_outcome)
def test_g_technical_unresolved_produces_unresolved():
    outcome, hit = resolve_research_outcome(
        research_complete=True,
        trusted_confirmed_count=0,
        semantic_unknown_count=0,
        pending_validation_count=0,
        technical_gap_count=2,
    )
    assert outcome == OUTCOME_UNRESOLVED
    assert hit is None


# Test H: research incomplete -> unresolved (via resolve_research_outcome)
def test_h_research_incomplete_produces_unresolved():
    outcome, hit = resolve_research_outcome(
        research_complete=False,
        trusted_confirmed_count=0,
        semantic_unknown_count=0,
        pending_validation_count=0,
        technical_gap_count=0,
    )
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


# Test M: baseline and ML classes are not same prediction authority
def test_m_baseline_and_ml_are_independent_authorities():
    baseline = OKPDHierarchicalPriorV1()
    ml_model = OKPDResearchHitModelV1()

    assert baseline.min_support == 3
    assert BASELINE_MODEL_NAME == "OKPD_HIERARCHICAL_PRIOR_V1"
    assert ml_model.model_name == MODEL_NAME
    assert ml_model.model_name != BASELINE_MODEL_NAME
    assert ml_model.feature_names == FEATURE_NAMES


# Test N: ML fit produces genuine model artifact and reload reproduces probabilities
def test_n_ml_fit_and_artifact_reproduction():
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
        ProcurementDatasetRow(
            procurement_id=3, research_completed_at="2026-08-31T18:02:00Z",
            okpd_code_raw="43.21", okpd_root="43", okpd_level2="43.21", okpd_level3="43.21", okpd_full="43.21",
            outcome=OUTCOME_POSITIVE, research_hit=1, trusted_confirmed_count=1, rejected_count=1, unknown_count=0, pending_validation_count=0, research_document_count=1
        ),
        ProcurementDatasetRow(
            procurement_id=4, research_completed_at="2026-08-31T18:03:00Z",
            okpd_code_raw="26.20", okpd_root="26", okpd_level2="26.20", okpd_level3="26.20", okpd_full="26.20",
            outcome=OUTCOME_SAFE_NEGATIVE, research_hit=0, trusted_confirmed_count=0, rejected_count=3, unknown_count=0, pending_validation_count=0, research_document_count=1
        ),
    ]

    model = OKPDResearchHitModelV1()
    model.fit(train_rows, dataset_snapshot_sha256="test_sha")
    assert model.is_fitted is True

    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = os.path.join(tmpdir, "okpd_research_hit_v1.json")
        model.save_artifact(json_path)
        assert os.path.exists(json_path)

        loaded = OKPDResearchHitModelV1.load_artifact(json_path)
        h1 = parse_okpd_hierarchy("42.11")
        h2 = parse_okpd_hierarchy("26.20")

        p1_orig = model.predict_proba_single(h1)
        p1_loaded = loaded.predict_proba_single(h1)
        p2_orig = model.predict_proba_single(h2)
        p2_loaded = loaded.predict_proba_single(h2)

        assert abs(p1_orig - p1_loaded) < 1e-4
        assert abs(p2_orig - p2_loaded) < 1e-4


# Test O: Tie-safe percentiles and bands (equal probability -> equal percentile & medal)
def test_o_tie_safe_percentiles_and_medals():
    model = OKPDResearchHitModelV1()
    # Mock single class or custom predict_proba to test ties
    population = [
        {"id": 1, "okpd_code_raw": "42.11"},
        {"id": 2, "okpd_code_raw": "42.11"},  # Exact same OKPD -> exact same probability
        {"id": 3, "okpd_code_raw": "26.20"},
        {"id": 4, "okpd_code_raw": "26.20"},  # Exact same OKPD -> exact same probability
    ]

    scored = model.score_population(population)
    assert len(scored) == 4

    p_map = {s.procurement_id: s for s in scored}
    # Items 1 and 2 must have identical score, percentile, and band
    assert p_map[1].p_research_hit == p_map[2].p_research_hit
    assert p_map[1].priority_percentile == p_map[2].priority_percentile
    assert p_map[1].priority_band == p_map[2].priority_band

    # Items 3 and 4 must have identical score, percentile, and band
    assert p_map[3].p_research_hit == p_map[4].p_research_hit
    assert p_map[3].priority_percentile == p_map[4].priority_percentile
    assert p_map[3].priority_band == p_map[4].priority_band


# Test P: Tie at exact medal boundary remains semantically equal
def test_p_tie_crossing_boundary_remains_equal():
    model = OKPDResearchHitModelV1()
    # 10 items total: 8 items with same low score, 2 items with same high score
    # In old code, rank 8 and rank 9 would cross 0.90 boundary (8/10=0.80 -> SILVER, 9/10=0.90 -> GOLD)
    raw_population = [
        {"id": 1, "okpd_code_raw": "26.20"},
        {"id": 2, "okpd_code_raw": "26.20"},
        {"id": 3, "okpd_code_raw": "26.20"},
        {"id": 4, "okpd_code_raw": "26.20"},
        {"id": 5, "okpd_code_raw": "26.20"},
        {"id": 6, "okpd_code_raw": "26.20"},
        {"id": 7, "okpd_code_raw": "26.20"},
        {"id": 8, "okpd_code_raw": "26.20"},
        {"id": 9, "okpd_code_raw": "42.11"},
        {"id": 10, "okpd_code_raw": "42.11"},
    ]

    scored = model.score_population(raw_population)
    low_scored = [s for s in scored if s.okpd_code_raw == "26.20"]
    high_scored = [s for s in scored if s.okpd_code_raw == "42.11"]

    # All 8 low-scored items must receive the EXACT same percentile and band
    low_percentiles = {s.priority_percentile for s in low_scored}
    low_bands = {s.priority_band for s in low_scored}
    assert len(low_percentiles) == 1
    assert len(low_bands) == 1

    # Both high-scored items must receive the EXACT same percentile and band
    high_percentiles = {s.priority_percentile for s in high_scored}
    high_bands = {s.priority_band for s in high_scored}
    assert len(high_percentiles) == 1
    assert len(high_bands) == 1


# Test Q: Promotion gate uses dynamic dataset counts and sets shadow promotion status
def test_q_promotion_gate_dynamic_counts_and_shadow_status():
    from src.learning.okpd_prior.train import train_and_evaluate_okpd_prior
    
    class MockDocConn:
        pass
    class MockCrmConn:
        pass

    import unittest.mock as mock
    with mock.patch("src.learning.okpd_prior.train.extract_procurement_dataset_from_db") as mock_extract:
        mock_extract.return_value = [
            ProcurementDatasetRow(
                procurement_id=1, research_completed_at="2026-08-31T18:00:00Z",
                okpd_code_raw="42.11", okpd_root="42", okpd_level2="42.11", okpd_level3="42.11", okpd_full="42.11",
                outcome=OUTCOME_POSITIVE, research_hit=1, trusted_confirmed_count=1, rejected_count=0, unknown_count=0, pending_validation_count=0, research_document_count=1
            ),
            ProcurementDatasetRow(
                procurement_id=2, research_completed_at="2026-08-31T18:01:00Z",
                okpd_code_raw="26.20", okpd_root="26", okpd_level2="26.20", okpd_level3="26.20", okpd_full="26.20",
                outcome=OUTCOME_SAFE_NEGATIVE, research_hit=0, trusted_confirmed_count=0, rejected_count=1, unknown_count=0, pending_validation_count=0, research_document_count=1
            ),
            ProcurementDatasetRow(
                procurement_id=3, research_completed_at="2026-08-31T18:02:00Z",
                okpd_code_raw="43.21", okpd_root="43", okpd_level2="43.21", okpd_level3="43.21", okpd_full="43.21",
                outcome=OUTCOME_POSITIVE, research_hit=1, trusted_confirmed_count=2, rejected_count=0, unknown_count=0, pending_validation_count=0, research_document_count=1
            ),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            res = train_and_evaluate_okpd_prior(
                MockDocConn(), MockCrmConn(),
                snapshot_dir=os.path.join(tmpdir, "snapshots"),
                model_dir=os.path.join(tmpdir, "models")
            )
            assert res["implementation_status"] == "PASS"
            assert res["evaluation_status"] == "INSUFFICIENT_DATA"
            assert res["production_priority_promotion"] == "INSUFFICIENT_EVALUATION_DATA"
            assert res["bands_evaluation_type"] == "IN_SAMPLE_OR_MIXED_CORPUS_DIAGNOSTIC"
            assert res["baseline_and_ml_same_implementation"] is False
            assert "labeled=3" in res["promotion_reason"]


# Test R: Shadow badge text and UI safety
def test_r_shadow_badge_and_missing_prediction_safety():
    from src.ui.components.okpd_priority_widget import SHADOW_HELP_TEXT
    assert "Пока прогноз не влияет на скачивание и обработку закупки" in SHADOW_HELP_TEXT

    repo = OKPDPriorPredictionRepository(in_memory_predictions={}, fallback_to_model=False)
    pred = repo.get_by_procurement_id(999999, okpd_code=None)
    assert pred is None
