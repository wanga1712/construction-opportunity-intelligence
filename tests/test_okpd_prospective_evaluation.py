"""Unit and integration tests for OKPD Prior V1 Prospective Shadow Evaluation."""

from __future__ import annotations

import json
import os
import pytest

from src.learning.okpd_prior.baseline import OKPDHierarchicalPriorV1
from src.learning.okpd_prior.dataset import (
    OUTCOME_POSITIVE,
    OUTCOME_SAFE_NEGATIVE,
    OUTCOME_UNRESOLVED,
    ProcurementDatasetRow,
    resolve_research_outcome,
)
from src.learning.okpd_prior.hierarchy import parse_okpd_hierarchy
from src.learning.okpd_prior.model import (
    BAND_BRONZE,
    BAND_GOLD,
    BAND_SILVER,
    BAND_WOOD,
    FEATURE_NAMES,
    OKPDResearchHitModelV1,
    assign_priority_band,
)
from src.learning.okpd_prior.prospective_evaluation import (
    GATE_MIN_LABELED,
    GATE_MIN_POSITIVES,
    GATE_MIN_SAFE_NEGATIVES,
    build_prospective_origin_manifest,
    compute_brier_score,
    compute_metrics_for_scores,
    compute_paired_bootstrap,
    filter_prospective_cohort,
    run_prospective_evaluation,
    score_prospective_cohort,
)


def test_origin_manifest_matches_frozen_snapshot():
    """Verifies that the origin manifest correctly pins the commit, snapshot sha, and IDs."""
    manifest = build_prospective_origin_manifest()
    assert manifest.source_git_commit == "0fcb49f8136c2bf3bbea88f7316047dabf5029c0"
    assert manifest.dataset_snapshot_sha256 == "112237b6f6393972b3ed6570938fc152a860425f9fe8362b07580eb443fcbd9a"
    assert manifest.model_name == "okpd_research_hit_v1"
    assert manifest.baseline_name == "OKPD_HIERARCHICAL_PRIOR_V1"
    assert len(manifest.original_procurement_ids) == 111
    assert 977 in manifest.original_procurement_ids
    assert 165153 in manifest.original_procurement_ids
    assert manifest.prospective_cutoff == "2026-08-31T19:54:20.149266+03:00"


def test_frozen_snapshot_rows_never_enter_prospective_cohort():
    """Verifies that any historical procurement ID is strictly excluded from the prospective cohort."""
    manifest = build_prospective_origin_manifest()
    # Candidate containing an original ID (e.g. 977) with timestamp after cutoff
    row_old = ProcurementDatasetRow(
        procurement_id=977,
        research_completed_at="2026-09-01T12:00:00+00:00",
        okpd_code_raw="42.11.20.000",
        okpd_root="42",
        okpd_level2="42.11",
        okpd_level3="42.11.20",
        okpd_full="42.11.20.000",
        outcome=OUTCOME_POSITIVE,
        research_hit=1,
        trusted_confirmed_count=1,
        rejected_count=0,
        unknown_count=0,
        pending_validation_count=0,
        research_document_count=2,
    )
    # Candidate with new ID
    row_new = ProcurementDatasetRow(
        procurement_id=999999,
        research_completed_at="2026-09-01T12:00:00+00:00",
        okpd_code_raw="42.11.20.000",
        okpd_root="42",
        okpd_level2="42.11",
        okpd_level3="42.11.20",
        okpd_full="42.11.20.000",
        outcome=OUTCOME_POSITIVE,
        research_hit=1,
        trusted_confirmed_count=1,
        rejected_count=0,
        unknown_count=0,
        pending_validation_count=0,
        research_document_count=2,
    )

    usable, unresolved = filter_prospective_cohort([row_old, row_new], manifest)
    assert len(usable) == 1
    assert usable[0].procurement_id == 999999


def test_cutoff_strictly_applied():
    """Verifies that rows completed on or before the cutoff timestamp are excluded."""
    manifest = build_prospective_origin_manifest()
    row_before = ProcurementDatasetRow(
        procurement_id=888888,
        research_completed_at="2026-08-30T10:00:00+00:00",
        okpd_code_raw="42.11.20.000",
        okpd_root="42",
        okpd_level2="42.11",
        okpd_level3="42.11.20",
        okpd_full="42.11.20.000",
        outcome=OUTCOME_POSITIVE,
        research_hit=1,
        trusted_confirmed_count=1,
        rejected_count=0,
        unknown_count=0,
        pending_validation_count=0,
        research_document_count=2,
    )
    row_after = ProcurementDatasetRow(
        procurement_id=888889,
        research_completed_at="2026-09-01T10:00:00+00:00",
        okpd_code_raw="42.11.20.000",
        okpd_root="42",
        okpd_level2="42.11",
        okpd_level3="42.11.20",
        okpd_full="42.11.20.000",
        outcome=OUTCOME_POSITIVE,
        research_hit=1,
        trusted_confirmed_count=1,
        rejected_count=0,
        unknown_count=0,
        pending_validation_count=0,
        research_document_count=2,
    )

    usable, _ = filter_prospective_cohort([row_before, row_after], manifest)
    assert len(usable) == 1
    assert usable[0].procurement_id == 888889


def test_new_label_does_not_mutate_frozen_baseline():
    """Verifies that prospective evaluations do not mutate the frozen empirical baseline stats."""
    with open("data/okpd_prior_snapshots/dataset_snapshot_v1.json", "r", encoding="utf-8") as f:
        train_raw = json.load(f)
    train_rows = [
        ProcurementDatasetRow(
            procurement_id=r["procurement_id"],
            research_completed_at=r.get("research_completed_at"),
            okpd_code_raw=r.get("okpd_code_raw"),
            okpd_root=r["okpd_root"],
            okpd_level2=r["okpd_level2"],
            okpd_level3=r["okpd_level3"],
            okpd_full=r["okpd_full"],
            outcome=r["outcome"],
            research_hit=r["research_hit"],
            trusted_confirmed_count=r.get("trusted_confirmed_count", 0),
            rejected_count=r.get("rejected_count", 0),
            unknown_count=r.get("unknown_count", 0),
            pending_validation_count=r.get("pending_validation_count", 0),
            research_document_count=r.get("research_document_count", 0),
        )
        for r in train_raw
    ]
    baseline = OKPDHierarchicalPriorV1().fit(train_rows)
    pred_before = baseline.predict(parse_okpd_hierarchy("42.11.20.000")).p_research_hit

    # Evaluate some new rows (even positive or negative)
    new_rows = [
        ProcurementDatasetRow(
            procurement_id=777777,
            research_completed_at="2026-09-02T10:00:00+00:00",
            okpd_code_raw="42.11.20.000",
            okpd_root="42",
            okpd_level2="42.11",
            okpd_level3="42.11.20",
            okpd_full="42.11.20.000",
            outcome=OUTCOME_POSITIVE,
            research_hit=1,
            trusted_confirmed_count=1,
            rejected_count=0,
            unknown_count=0,
            pending_validation_count=0,
            research_document_count=2,
        )
    ]
    score_prospective_cohort(new_rows, baseline, OKPDResearchHitModelV1.load_artifact("data/okpd_prior_models/okpd_research_hit_v1.json"))
    pred_after = baseline.predict(parse_okpd_hierarchy("42.11.20.000")).p_research_hit

    assert pred_before == pred_after


def test_unresolved_excluded_from_cohort():
    """Verifies that UNRESOLVED rows are excluded from scoring."""
    manifest = build_prospective_origin_manifest()
    row_unres = ProcurementDatasetRow(
        procurement_id=666666,
        research_completed_at="2026-09-02T10:00:00+00:00",
        okpd_code_raw="42.11.20.000",
        okpd_root="42",
        okpd_level2="42.11",
        okpd_level3="42.11.20",
        okpd_full="42.11.20.000",
        outcome=OUTCOME_UNRESOLVED,
        research_hit=None,
        trusted_confirmed_count=0,
        rejected_count=0,
        unknown_count=1,
        pending_validation_count=0,
        research_document_count=2,
    )
    usable, unresolved_cnt = filter_prospective_cohort([row_unres], manifest)
    assert len(usable) == 0
    assert unresolved_cnt == 1


def test_unknown_and_pending_do_not_turn_into_safe_negative():
    """Verifies label authority contract: unknown or pending validations resolve to UNRESOLVED, not SAFE_NEGATIVE."""
    out_unk, hit_unk = resolve_research_outcome(
        research_complete=True,
        trusted_confirmed_count=0,
        semantic_unknown_count=1,
        pending_validation_count=0,
    )
    assert out_unk == OUTCOME_UNRESOLVED
    assert hit_unk is None

    out_pend, hit_pend = resolve_research_outcome(
        research_complete=True,
        trusted_confirmed_count=0,
        semantic_unknown_count=0,
        pending_validation_count=2,
    )
    assert out_pend == OUTCOME_UNRESOLVED
    assert hit_pend is None

    out_safe, hit_safe = resolve_research_outcome(
        research_complete=True,
        trusted_confirmed_count=0,
        semantic_unknown_count=0,
        pending_validation_count=0,
    )
    assert out_safe == OUTCOME_SAFE_NEGATIVE
    assert hit_safe == 0


def test_post_research_features_count_is_zero():
    """Verifies that only pre-research OKPD hierarchy features exist in the model predictor set."""
    allowed_features = {"okpd_root", "okpd_level2", "okpd_level3", "okpd_full"}
    assert set(FEATURE_NAMES) == allowed_features
    assert "trusted_confirmed_count" not in FEATURE_NAMES
    assert "rejected_count" not in FEATURE_NAMES
    assert "unknown_count" not in FEATURE_NAMES
    assert "pending_validation_count" not in FEATURE_NAMES
    assert "research_document_count" not in FEATURE_NAMES


def test_identical_scores_produce_identical_percentile_and_band():
    """Verifies MAX_RANK tie-handling invariant: equal scores get identical percentile and band."""
    rows = [
        ProcurementDatasetRow(
            procurement_id=1000 + i,
            research_completed_at="2026-09-02T10:00:00+00:00",
            okpd_code_raw="42.11.20.000",
            okpd_root="42",
            okpd_level2="42.11",
            okpd_level3="42.11.20",
            okpd_full="42.11.20.000",
            outcome=OUTCOME_POSITIVE if i % 2 == 0 else OUTCOME_SAFE_NEGATIVE,
            research_hit=1 if i % 2 == 0 else 0,
            trusted_confirmed_count=1 if i % 2 == 0 else 0,
            rejected_count=0,
            unknown_count=0,
            pending_validation_count=0,
            research_document_count=1,
        )
        for i in range(4)
    ]
    with open("data/okpd_prior_snapshots/dataset_snapshot_v1.json", "r", encoding="utf-8") as f:
        train_raw = json.load(f)
    train_rows = [ProcurementDatasetRow(
        procurement_id=r["procurement_id"],
        research_completed_at=r.get("research_completed_at"),
        okpd_code_raw=r.get("okpd_code_raw"),
        okpd_root=r["okpd_root"],
        okpd_level2=r["okpd_level2"],
        okpd_level3=r["okpd_level3"],
        okpd_full=r["okpd_full"],
        outcome=r["outcome"],
        research_hit=r["research_hit"],
        trusted_confirmed_count=0, rejected_count=0, unknown_count=0, pending_validation_count=0, research_document_count=0,
    ) for r in train_raw]
    b_model = OKPDHierarchicalPriorV1().fit(train_rows)
    ml_model = OKPDResearchHitModelV1.load_artifact("data/okpd_prior_models/okpd_research_hit_v1.json")

    scored = score_prospective_cohort(rows, b_model, ml_model)
    # Since all rows have the identical OKPD code "42.11.20.000", their scores must be identical
    ml_scores = [r["ml_score"] for r in scored]
    assert len(set(ml_scores)) == 1

    ml_pcts = [r["ml_percentile"] for r in scored]
    assert len(set(ml_pcts)) == 1
    assert ml_pcts[0] == 1.0  # Under MAX_RANK tie policy, all 4 are <= 4/4 = 1.0

    ml_bands = [r["ml_band"] for r in scored]
    assert len(set(ml_bands)) == 1
    assert ml_bands[0] == BAND_GOLD


def test_insufficient_corpus_gate_returns_insufficient_status(tmp_path):
    """Verifies that when prospective data is below gate, status is INSUFFICIENT_PROSPECTIVE_DATA and promotion is NO."""
    # 10 labeled rows (below 100)
    candidate_rows = [
        ProcurementDatasetRow(
            procurement_id=5000 + i,
            research_completed_at="2026-09-02T10:00:00+00:00",
            okpd_code_raw="42.11.20.000",
            okpd_root="42",
            okpd_level2="42.11",
            okpd_level3="42.11.20",
            okpd_full="42.11.20.000",
            outcome=OUTCOME_POSITIVE if i < 3 else OUTCOME_SAFE_NEGATIVE,
            research_hit=1 if i < 3 else 0,
            trusted_confirmed_count=1 if i < 3 else 0,
            rejected_count=0, unknown_count=0, pending_validation_count=0, research_document_count=1,
        )
        for i in range(10)
    ]

    out_dir = str(tmp_path / "eval_out")
    report = run_prospective_evaluation(candidate_rows=candidate_rows, output_dir=out_dir)

    gates = report["evaluation_gates"]
    assert gates["evaluation_status"] == "INSUFFICIENT_PROSPECTIVE_DATA"
    assert gates["promotion_review_eligible"] == "NO"
    assert gates["production_priority_promotion"] == "NO_CHANGE"


def test_sufficient_corpus_evaluates_and_computes_paired_bootstrap(tmp_path):
    """Verifies that with a sufficient synthetic cohort (>=100 labeled, >=20 pos, >=50 safe neg), full metrics and bootstrap run."""
    candidate_rows = []
    # 25 positives, 85 negatives -> 110 labeled total
    for i in range(110):
        is_pos = (i < 25)
        okpd = "42.11.20.000" if is_pos else "32.50.13.110"
        hier = parse_okpd_hierarchy(okpd)
        candidate_rows.append(
            ProcurementDatasetRow(
                procurement_id=7000 + i,
                research_completed_at="2026-09-02T12:00:00+00:00",
                okpd_code_raw=okpd,
                okpd_root=hier.okpd_root,
                okpd_level2=hier.okpd_level2,
                okpd_level3=hier.okpd_level3,
                okpd_full=hier.okpd_full,
                outcome=OUTCOME_POSITIVE if is_pos else OUTCOME_SAFE_NEGATIVE,
                research_hit=1 if is_pos else 0,
                trusted_confirmed_count=1 if is_pos else 0,
                rejected_count=0, unknown_count=0, pending_validation_count=0, research_document_count=1,
            )
        )

    out_dir = str(tmp_path / "eval_sufficient")
    report = run_prospective_evaluation(candidate_rows=candidate_rows, output_dir=out_dir)

    gates = report["evaluation_gates"]
    assert gates["evaluation_status"] == "EVALUATED"
    assert "bootstrap_confidence_intervals" in report
    assert "pr_auc" in report["bootstrap_confidence_intervals"]
    assert "ci_lower" in report["bootstrap_confidence_intervals"]["pr_auc"]
    assert report["evaluation_gates"]["production_priority_promotion"] == "NO_CHANGE"
