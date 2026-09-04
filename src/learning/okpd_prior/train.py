"""Offline training and evaluation pipeline for OKPD Prior Learning V1."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from src.learning.okpd_prior.baseline import OKPDHierarchicalPriorV1
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
        Structured training results report dictionary.
    """
    os.makedirs(snapshot_dir, exist_ok=True)
    os.makedirs(model_dir, exist_ok=True)

    # 1. Extract dataset
    rows = extract_procurement_dataset_from_db(doc_conn, crm_conn)
    snapshot_path = os.path.join(snapshot_dir, "dataset_snapshot_v1.json")
    manifest = create_dataset_snapshot(rows, snapshot_path)

    # 2. Split dataset
    usable_rows = [r for r in rows if r.research_hit is not None]
    train_rows, val_rows, holdout_rows, temp_split_avail = split_dataset(rows)

    # 3. Fit Baseline Model
    baseline = OKPDHierarchicalPriorV1()
    baseline.fit(train_rows)

    # Evaluate baseline on all usable rows
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

    # 4. Fit ML Model
    model = OKPDResearchHitModelV1()
    model.fit(train_rows, dataset_snapshot_sha256=manifest["snapshot_sha256"])
    model_path = os.path.join(model_dir, "okpd_research_hit_v1.json")
    model.save_artifact(model_path)

    # Evaluate ML Model
    def _eval_model(split_rows: List[ProcurementDatasetRow]) -> ModelEvaluationMetrics:
        y_true = [r.research_hit for r in split_rows if r.research_hit is not None]
        y_score = [
            model.predict_proba_single(parse_okpd_hierarchy(r.okpd_code_raw))
            for r in split_rows if r.research_hit is not None
        ]
        return evaluate_ranking_metrics(y_true, y_score)

    model_metrics_train = _eval_model(train_rows)
    model_metrics_val = _eval_model(val_rows)
    model_metrics_holdout = _eval_model(holdout_rows)
    model_metrics_all = _eval_model(usable_rows)

    # 5. Score full usable population to check bands
    scored_population = model.score_population([r.to_dict() for r in usable_rows])
    band_counts: Dict[str, int] = {"GOLD": 0, "SILVER": 0, "BRONZE": 0, "WOOD": 0}
    band_hits: Dict[str, int] = {"GOLD": 0, "SILVER": 0, "BRONZE": 0, "WOOD": 0}

    proc_hit_map = {r.procurement_id: r.research_hit for r in usable_rows}
    for s in scored_population:
        band = s.priority_band
        band_counts[band] = band_counts.get(band, 0) + 1
        if proc_hit_map.get(s.procurement_id) == 1:
            band_hits[band] = band_hits.get(band, 0) + 1

    # 6. Promotion Gate Evaluation
    # Small sample caveat: 32 labeled rows total, 6 holdout rows, 0 validation positives.
    is_useful = bool(
        model_metrics_holdout.lift_at_10 >= 2.0
        and model_metrics_holdout.recall_at_30 > 0.30
    )
    implementation_status = "PASS"
    signal_status = "ENCOURAGING" if is_useful else "INSUFFICIENT"
    production_priority_promotion = "INSUFFICIENT_EVALUATION_DATA"
    promotion_reason = (
        "Small sample size (32 labeled rows total, 6 holdout rows, 0 validation positives). "
        "Requires larger corpus for production promotion."
    )
    bands_evaluation_type = "IN_SAMPLE_OR_MIXED_CORPUS_DIAGNOSTIC"

    # OKPD Root breakdown for report
    root_summary = baseline.get_root_summary_table()

    report = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "trained_at": model.trained_at,
        "dataset_snapshot_sha256": manifest["snapshot_sha256"],
        "dataset": {
            "total_procurements": manifest["total_procurements"],
            "positive_count": manifest["positive_count"],
            "safe_negative_count": manifest["safe_negative_count"],
            "unresolved_excluded_count": manifest["unresolved_excluded_count"],
            "labeled_count": manifest["labeled_count"],
            "positive_rate": manifest["positive_rate"],
            "train_rows": len(train_rows),
            "val_rows": len(val_rows),
            "holdout_rows": len(holdout_rows),
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
        },
        "roots_table": root_summary,
        "implementation_status": implementation_status,
        "signal_status": signal_status,
        "production_priority_promotion": production_priority_promotion,
        "promotion_reason": promotion_reason,
        "bands_evaluation_type": bands_evaluation_type,
        "model_result": production_priority_promotion,
        "model_artifact_path": model_path,
        "snapshot_artifact_path": snapshot_path,
    }

    report_path = os.path.join(model_dir, "training_report_v1.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return report

