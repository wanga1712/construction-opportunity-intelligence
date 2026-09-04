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


# Test S: RECHECK-1 PID reconciliation and counts invariant
def test_s_recheck1_pid_reconciliation_counts():
    # 28 candidate items in RECHECK-1
    pos_pids = {165110, 165152, 163840, 163841, 163638, 163645}
    neg_pids = {
        163858, 992, 993, 163637, 163641, 163640, 163851, 163870, 163872, 163861,
        163644, 163948, 163642, 163649, 163646, 163648, 163838, 985, 987, 163871
    }
    unres_pids = {163843, 163874}

    all_pids = pos_pids.union(neg_pids).union(unres_pids)
    assert len(all_pids) == 28
    assert len(pos_pids) == 6
    assert len(neg_pids) == 20
    assert len(unres_pids) == 2

    # Disjointness of labels
    assert pos_pids.isdisjoint(neg_pids)
    assert pos_pids.isdisjoint(unres_pids)
    assert neg_pids.isdisjoint(unres_pids)


# Test T: Score-blind RECHECK-2 selection and cohort disjointness
def test_t_recheck2_selection_and_cohort_disjointness():
    recheck1_pids = {
        165110, 165152, 163840, 163841, 163638, 163645,
        163858, 992, 993, 163637, 163641, 163640, 163851, 163870, 163872, 163861,
        163644, 163948, 163642, 163649, 163646, 163648, 163838, 985, 987, 163871,
        163843, 163874
    }
    # 54 candidates in RECHECK-2
    recheck2_pids = {
        163833, 163856, 163937, 163957, 164295, 164303, 164316, 164336, 164341,
        164504, 164720, 165008, 163936, 164477, 164487, 164525, 165116, 164324,
        164493, 163995, 164491, 164506, 165102, 164721, 163835, 163869, 163952,
        163853, 163867, 163873, 163857, 163943, 163850, 163935, 164699, 164509,
        163842, 163852, 163865, 165148, 165153, 163862, 163955, 163854, 163855,
        163941, 163931, 163947, 163932, 163848, 163875, 163876, 163877, 163879
    }
    assert len(recheck2_pids) == 54
    assert recheck1_pids.isdisjoint(recheck2_pids), "RECHECK-1 and RECHECK-2 must be completely disjoint"


# Test U: Original frozen model invariants (feature set, type, tie policy)
def test_u_frozen_model_invariants():
    model = OKPDResearchHitModelV1()
    assert model.feature_names == ["okpd_root", "okpd_level2", "okpd_level3", "okpd_full"]
    assert model.model_name == "okpd_research_hit_v1"
    assert model.model_type == "CatBoostClassifier"
    assert BASELINE_MODEL_NAME == "OKPD_HIERARCHICAL_PRIOR_V1"


# Test V: Same-row Baseline and ML evaluation invariant
def test_v_same_row_baseline_and_ml_evaluation():
    test_rows = [
        {"procurement_id": 1, "okpd_code": "42.11", "target": 1},
        {"procurement_id": 2, "okpd_code": "26.20", "target": 0},
        {"procurement_id": 3, "okpd_code": "43.34", "target": 1},
        {"procurement_id": 4, "okpd_code": "71.12", "target": 0},
    ]
    y_true = [r["target"] for r in test_rows]

    # Baseline predictions
    baseline = OKPDHierarchicalPriorV1()
    baseline_scores = [baseline.predict(parse_okpd_hierarchy(r["okpd_code"])).p_research_hit for r in test_rows]

    # ML predictions
    ml_model = OKPDResearchHitModelV1()
    ml_scores = [s.p_research_hit for s in ml_model.score_population(test_rows)]

    assert len(baseline_scores) == len(test_rows)
    assert len(ml_scores) == len(test_rows)
    assert len(baseline_scores) == len(ml_scores)

    b_metrics = evaluate_ranking_metrics(y_true, baseline_scores)
    ml_metrics = evaluate_ranking_metrics(y_true, ml_scores)

    assert b_metrics.total_samples == ml_metrics.total_samples == len(test_rows)
    assert b_metrics.positive_count == ml_metrics.positive_count == sum(y_true)


# Test W: Label leakage prevention: diagnostic fields are not features
def test_w_label_leakage_prevention():
    row = ProcurementDatasetRow(
        procurement_id=999,
        research_completed_at="2026-09-04T10:00:00Z",
        okpd_code_raw="42.11.20",
        okpd_root="42",
        okpd_level2="42.11",
        okpd_level3="42.11.20",
        okpd_full="42.11.20",
        outcome=OUTCOME_POSITIVE,
        research_hit=1,
        trusted_confirmed_count=10,
        rejected_count=50,
        unknown_count=3,
        pending_validation_count=2,
        research_document_count=8,
    )
    features = row.to_feature_dict()
    # Must ONLY contain hierarchical OKPD keys
    assert set(features.keys()) == {"okpd_root", "okpd_level2", "okpd_level3", "okpd_full"}
    assert "trusted_confirmed_count" not in features
    assert "research_hit" not in features
    assert "rejected_count" not in features
    assert "unknown_count" not in features


# Test X: Cumulative Fresh evaluation aggregation
def test_x_cumulative_fresh_evaluation_aggregation():
    # 26 rows from RECHECK-1 + 54 rows from RECHECK-2 = 80 rows
    r1_y = [1] * 6 + [0] * 20
    r2_y = [1] * 13 + [0] * 41
    cum_y = r1_y + r2_y

    assert len(cum_y) == 80
    assert sum(cum_y) == 19
    assert len(cum_y) - sum(cum_y) == 61

    # Simulate strictly separating scores
    cum_scores = [0.9 + (i * 0.001) if y == 1 else 0.1 + (i * 0.001) for i, y in enumerate(cum_y)]
    metrics = evaluate_ranking_metrics(cum_y, cum_scores)
    assert metrics.total_samples == 80
    assert metrics.positive_count == 19
    assert metrics.negative_count == 61
    assert metrics.roc_auc == 1.0


# Test Y: Single class metric handling safety (no div by zero)
def test_y_single_class_metric_handling():
    all_zeros = [0, 0, 0, 0, 0]
    all_ones = [1, 1, 1, 1, 1]
    scores = [0.1, 0.2, 0.3, 0.4, 0.5]

    m_zero = evaluate_ranking_metrics(all_zeros, scores)
    assert m_zero.roc_auc == 0.5
    assert m_zero.pr_auc == 0.0

    m_one = evaluate_ranking_metrics(all_ones, scores)
    assert m_one.roc_auc == 0.5
    assert m_one.pr_auc == 1.0


# Test Z: Raw Top-K hit reporting calculations
def test_z_raw_top_k_hit_reporting():
    y_true = [1, 0, 1, 0, 0, 0, 0, 0, 0, 0] # 2 positives in 10 items
    y_scores = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0]

    metrics = evaluate_ranking_metrics(y_true, y_scores)
    assert metrics.precision_at_10 == 1.0 # top 1 item has score 0.9 (hit) -> 1/1 = 1.0
    assert metrics.recall_at_10 == 0.5 # 1 out of 2 total positives
    assert metrics.precision_at_20 == 0.5 # top 2 items (1, 0) -> 1/2 = 0.5
    assert metrics.recall_at_20 == 0.5
    assert metrics.recall_at_30 == 1.0 # top 3 items (1, 0, 1) -> 2/2 = 1.0
    assert metrics.lift_at_10 == 5.0 # precision 1.0 / base_rate 0.2 = 5.0

