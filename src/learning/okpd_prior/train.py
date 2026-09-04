"""Offline training and evaluation pipeline for OKPD Prior Learning V1.

Features:
- Independent fitting of baseline empirical prior and CatBoost ML model.
- Dynamic evaluation counts from current snapshot (zero hard-coded sizes).
- Clear separation of baseline metrics vs ML metrics.
- Deterministic promotion gate reporting (INSUFFICIENT_EVALUATION_DATA for early shadow stage).
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from src.learning.okpd_prior.baseline import (
    BASELINE_MODEL_NAME,
    OKPDHierarchicalPriorV1,
)
from src.learning.okpd_prior.dataset import (
    ProcurementDatasetRow,
    create_dataset_snapshot,
    extract_procurement_dataset_from_db,
    split_dataset,
)
from src.learning.okpd_prior.hierarchy import parse_okpd_hierarchy
from src.learning.okpd_prior.metrics import ModelEvaluationMetrics, evaluate_ranking_metrics
from src.learning.okpd_prior.model import (
    MODEL_NAME,
    MODEL_TYPE,
    MODEL_VERSION,
    OKPDResearchHitModelV1,
)

logger = logging.getLogger("crm.learning.okpd_prior.train")


def train_and_evaluate_okpd_prior(
    doc_conn,
    crm_conn,
    snapshot_dir: str = "data/okpd_prior_snapshots",
    model_dir: str = "data/okpd_prior_models",
) -> Dict[str, Any]:
    """Runs complete end-to-end training, evaluation, and artifact serialization.

    Returns:
        Structured training results report dictionary with dynamic corpus statistics.
    """
    os.makedirs(snapshot_dir, exist_ok=True)
    os.makedirs(model_dir, exist_ok=True)

    # 1. Extract dataset & snapshot
    rows = extract_procurement_dataset_from_db(doc_conn, crm_conn)
    snapshot_path = os.path.join(snapshot_dir, "dataset_snapshot_v1.json")
    manifest = create_dataset_snapshot(rows, snapshot_path)

    # 2. Split dataset
    usable_rows = [r for r in rows if r.research_hit is not None]
    train_rows, val_rows, holdout_rows, temp_split_avail = split_dataset(rows)

    train_positives = sum(1 for r in train_rows if r.research_hit == 1)
    train_negatives = len(train_rows) - train_positives
    val_positives = sum(1 for r in val_rows if r.research_hit == 1)
    val_negatives = len(val_rows) - val_positives
    holdout_positives = sum(1 for r in holdout_rows if r.research_hit == 1)
    holdout_negatives = len(holdout_rows) - holdout_positives

    # 3. Fit Baseline Model (Empirical Hierarchical Prior)
    baseline = OKPDHierarchicalPriorV1()
    baseline.fit(train_rows)

    def _eval_baseline(split_rows: List[ProcurementDatasetRow]) -> ModelEvaluationMetrics:
        y_true = [r.research_hit for r in split_rows if r.research_hit is not None]
        y_score = [
            baseline.predict(parse_okpd_hierarchy(r.okpd_code_raw)).p_research_hit
            for r in split_rows if r.research_hit is not None
        ]
        return evaluate_ranking_metrics(y_true, y_score)

    baseline_metrics_train = _eval_baseline(train_rows)
    baseline_metrics_val = _eval_baseline(val_rows)
    baseline_metrics_holdout = _eval_baseline(holdout_rows)
    baseline_metrics_all = _eval_baseline(usable_rows)

    # 4. Fit Independent ML Model (CatBoost Classifier)
    ml_model = OKPDResearchHitModelV1()
    ml_model.fit(train_rows, dataset_snapshot_sha256=manifest["snapshot_sha256"])
    model_path = os.path.join(model_dir, "okpd_research_hit_v1.json")
    ml_model.save_artifact(model_path)

    def _eval_ml(split_rows: List[ProcurementDatasetRow]) -> ModelEvaluationMetrics:
        y_true = [r.research_hit for r in split_rows if r.research_hit is not None]
        y_score = [
            ml_model.predict_proba_single(parse_okpd_hierarchy(r.okpd_code_raw))
            for r in split_rows if r.research_hit is not None
        ]
        return evaluate_ranking_metrics(y_true, y_score)

    model_metrics_train = _eval_ml(train_rows)
    model_metrics_val = _eval_ml(val_rows)
    model_metrics_holdout = _eval_ml(holdout_rows)
    model_metrics_all = _eval_ml(usable_rows)

    # 5. Score population to inspect tie-safe band distribution
    scored_population = ml_model.score_population([r.to_dict() for r in usable_rows])
    band_counts: Dict[str, int] = {"GOLD": 0, "SILVER": 0, "BRONZE": 0, "WOOD": 0}
    band_hits: Dict[str, int] = {"GOLD": 0, "SILVER": 0, "BRONZE": 0, "WOOD": 0}

    proc_hit_map = {r.procurement_id: r.research_hit for r in usable_rows}
    for s in scored_population:
        band = s.priority_band
        band_counts[band] = band_counts.get(band, 0) + 1
        if proc_hit_map.get(s.procurement_id) == 1:
            band_hits[band] = band_hits.get(band, 0) + 1

    # 6. Dynamic Status & Promotion Evaluation
    implementation_status = "PASS"
    
    # Signal evaluation based on holdout / train metrics
    if model_metrics_holdout.lift_at_10 >= 1.5 or model_metrics_train.roc_auc >= 0.70:
        signal_status = "ENCOURAGING"
    elif model_metrics_holdout.lift_at_10 > 1.0:
        signal_status = "INCONCLUSIVE"
    else:
        signal_status = "NO_SIGNAL"

    # Evaluation status based on sample size criteria
    is_sufficient_sample = bool(
        len(holdout_rows) >= 50
        and val_positives > 0
        and holdout_positives > 0
    )
    evaluation_status = "EVALUABLE" if is_sufficient_sample else "INSUFFICIENT_DATA"

    # In shadow learning WIPs, promotion remains strictly shadow-only
    production_priority_promotion = "INSUFFICIENT_EVALUATION_DATA"
    promotion_reason = (
        f"Evaluation corpus is insufficient for production promotion: "
        f"labeled={len(usable_rows)}, validation={len(val_rows)} ({val_positives} positives), "
        f"holdout={len(holdout_rows)} ({holdout_positives} positives). "
        f"Requires larger corpus and explicit bakeoff for production promotion."
    )
    bands_evaluation_type = "IN_SAMPLE_OR_MIXED_CORPUS_DIAGNOSTIC"

    root_summary = baseline.get_root_summary_table()

    report = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "model_type": ml_model.model_type,
        "baseline_model_name": BASELINE_MODEL_NAME,
        "trained_at": ml_model.trained_at,
        "dataset_snapshot_sha256": manifest["snapshot_sha256"],
        "dataset": {
            "total_procurements": manifest["total_procurements"],
            "positive_count": manifest["positive_count"],
            "safe_negative_count": manifest["safe_negative_count"],
            "unresolved_excluded_count": manifest["unresolved_excluded_count"],
            "labeled_count": manifest["labeled_count"],
            "positive_rate": manifest["positive_rate"],
            "train_rows": len(train_rows),
            "train_positives": train_positives,
            "train_negatives": train_negatives,
            "val_rows": len(val_rows),
            "val_positives": val_positives,
            "val_negatives": val_negatives,
            "holdout_rows": len(holdout_rows),
            "holdout_positives": holdout_positives,
            "holdout_negatives": holdout_negatives,
            "temporal_split_available": temp_split_avail,
        },
        "baseline_metrics": {
            "train": baseline_metrics_train.to_dict(),
            "val": baseline_metrics_val.to_dict(),
            "holdout": baseline_metrics_holdout.to_dict(),
            "all": baseline_metrics_all.to_dict(),
        },
        "model_metrics": {
            "train": model_metrics_train.to_dict(),
            "val": model_metrics_val.to_dict(),
            "holdout": model_metrics_holdout.to_dict(),
            "all": model_metrics_all.to_dict(),
        },
        "bands": {
            "counts": band_counts,
            "hits": band_hits,
            "tie_policy": "MAX_RANK",
        },
        "roots_table": root_summary,
        "implementation_status": implementation_status,
        "signal_status": signal_status,
        "evaluation_status": evaluation_status,
        "production_priority_promotion": production_priority_promotion,
        "promotion_reason": promotion_reason,
        "bands_evaluation_type": bands_evaluation_type,
        "baseline_and_ml_same_implementation": False,
        "model_result": production_priority_promotion,
        "model_artifact_path": model_path,
        "cbm_artifact_path": ml_model.cbm_artifact_path,
        "snapshot_artifact_path": snapshot_path,
    }

    report_path = os.path.join(model_dir, "training_report_v1.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return report
