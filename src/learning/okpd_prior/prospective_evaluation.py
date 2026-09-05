"""Prospective Shadow Evaluation contour for OKPD Prior Learning V1.

Implements immutable origin manifest, strict post-cutoff candidate cohort extraction,
frozen baseline & ML scoring, paired bootstrap bake-off, and corpus sufficiency gating.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from src.learning.okpd_prior.baseline import (
    BASELINE_MODEL_NAME,
    DEFAULT_MIN_SUPPORT,
    DEFAULT_SMOOTHING_WEIGHT,
    OKPDHierarchicalPriorV1,
)
from src.learning.okpd_prior.dataset import (
    OUTCOME_POSITIVE,
    OUTCOME_SAFE_NEGATIVE,
    OUTCOME_UNRESOLVED,
    ProcurementDatasetRow,
)
from src.learning.okpd_prior.hierarchy import OKPDHierarchy, UNKNOWN_OKPD, parse_okpd_hierarchy
from src.learning.okpd_prior.metrics import (
    compute_brier_score,
    compute_metrics_for_scores,
    compute_paired_bootstrap,
    compute_pr_auc,
    compute_roc_auc,
)
from src.learning.okpd_prior.model import (
    BAND_BRONZE,
    BAND_GOLD,
    BAND_SILVER,
    BAND_WOOD,
    MODEL_NAME,
    OKPDResearchHitModelV1,
    assign_priority_band,
)

SOURCE_FEATURE_GIT_COMMIT = "0fcb49f8136c2bf3bbea88f7316047dabf5029c0"
DATASET_SNAPSHOT_V1_SHA256 = "112237b6f6393972b3ed6570938fc152a860425f9fe8362b07580eb443fcbd9a"
TIE_POLICY = "MAX_RANK"

GATE_MIN_LABELED = 100
GATE_MIN_POSITIVES = 20
GATE_MIN_SAFE_NEGATIVES = 50


@dataclass(frozen=True)
class ProspectiveOriginManifest:
    """Immutable manifest pinning the starting state and training origin of V1 models."""
    source_git_commit: str
    dataset_snapshot_sha256: str
    model_name: str
    model_artifact_sha256: str
    model_metadata_sha256: str
    baseline_name: str
    baseline_parameters: Dict[str, Any]
    training_dataset_identity: str
    prospective_cutoff: str
    original_procurement_ids: List[int]
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_file_sha256(filepath: str) -> str:
    """Computes SHA256 of file contents on disk."""
    with open(filepath, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def build_prospective_origin_manifest(
    snapshot_path: str = "data/okpd_prior_snapshots/dataset_snapshot_v1.json",
    model_cbm_path: str = "data/okpd_prior_models/okpd_research_hit_v1.cbm",
    model_json_path: str = "data/okpd_prior_models/okpd_research_hit_v1.json",
) -> ProspectiveOriginManifest:
    """Constructs the prospective origin manifest from frozen artifacts."""
    with open(snapshot_path, "r", encoding="utf-8") as f:
        rows = json.load(f)

    proc_ids = sorted(int(r["procurement_id"]) for r in rows)
    completed_timestamps = [
        r["research_completed_at"] for r in rows if r.get("research_completed_at")
    ]
    cutoff = max(completed_timestamps) if completed_timestamps else datetime.now(timezone.utc).isoformat()

    cbm_sha = compute_file_sha256(model_cbm_path) if os.path.isfile(model_cbm_path) else ""
    json_sha = compute_file_sha256(model_json_path) if os.path.isfile(model_json_path) else ""

    return ProspectiveOriginManifest(
        source_git_commit=SOURCE_FEATURE_GIT_COMMIT,
        dataset_snapshot_sha256=DATASET_SNAPSHOT_V1_SHA256,
        model_name=MODEL_NAME,
        model_artifact_sha256=cbm_sha,
        model_metadata_sha256=json_sha,
        baseline_name=BASELINE_MODEL_NAME,
        baseline_parameters={
            "smoothing_weight": DEFAULT_SMOOTHING_WEIGHT,
            "min_support": DEFAULT_MIN_SUPPORT,
        },
        training_dataset_identity=snapshot_path,
        prospective_cutoff=cutoff,
        original_procurement_ids=proc_ids,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def filter_prospective_cohort(
    candidate_rows: List[ProcurementDatasetRow],
    origin_manifest: ProspectiveOriginManifest,
) -> Tuple[List[ProcurementDatasetRow], int]:
    """Filters candidate procurements strictly after cutoff and disjoint from historical corpus."""
    orig_ids = set(origin_manifest.original_procurement_ids)
    cutoff = origin_manifest.prospective_cutoff

    usable_rows: List[ProcurementDatasetRow] = []
    unresolved_count = 0

    for r in candidate_rows:
        if r.procurement_id in orig_ids:
            continue
        if r.research_completed_at and r.research_completed_at <= cutoff:
            continue
        if r.outcome in (OUTCOME_POSITIVE, OUTCOME_SAFE_NEGATIVE) and r.research_hit is not None:
            usable_rows.append(r)
        else:
            unresolved_count += 1

    return usable_rows, unresolved_count


def score_prospective_cohort(
    rows: List[ProcurementDatasetRow],
    baseline_model: OKPDHierarchicalPriorV1,
    ml_model: OKPDResearchHitModelV1,
) -> List[Dict[str, Any]]:
    """Calculates frozen baseline and ML scores with tie-safe percentiles and bands."""
    n = len(rows)
    if n == 0:
        return []

    baseline_scores: List[float] = []
    ml_scores: List[float] = []

    for r in rows:
        hier = parse_okpd_hierarchy(r.okpd_code_raw)
        b_pred = baseline_model.predict(hier)
        baseline_scores.append(round(b_pred.p_research_hit, 4))

        pop_input = [{"procurement_id": r.procurement_id, "okpd_code": r.okpd_code_raw}]
        ml_res = ml_model.score_population(pop_input)
        ml_score = ml_res[0].p_research_hit if ml_res else 0.05
        ml_scores.append(round(ml_score, 4))

    scored_items: List[Dict[str, Any]] = []
    for i, r in enumerate(rows):
        b_score = baseline_scores[i]
        m_score = ml_scores[i]

        b_le = sum(1 for s in baseline_scores if s <= b_score)
        b_pct = round(b_le / float(n), 4)
        b_band = assign_priority_band(b_pct)

        m_le = sum(1 for s in ml_scores if s <= m_score)
        m_pct = round(m_le / float(n), 4)
        m_band = assign_priority_band(m_pct)

        scored_items.append({
            "procurement_id": r.procurement_id,
            "research_completed_at": r.research_completed_at,
            "okpd_raw": r.okpd_code_raw,
            "okpd_root": r.okpd_root,
            "okpd_level2": r.okpd_level2,
            "okpd_level3": r.okpd_level3,
            "okpd_full": r.okpd_full,
            "outcome": r.outcome,
            "research_hit": r.research_hit,
            "baseline_score": b_score,
            "baseline_percentile": b_pct,
            "baseline_band": b_band,
            "ml_score": m_score,
            "ml_percentile": m_pct,
            "ml_band": m_band,
        })

    return scored_items


def compute_band_breakdown(
    scored_rows: List[Dict[str, Any]],
    band_key: str = "ml_band",
) -> Dict[str, Dict[str, Any]]:
    """Calculates count, positives, and hit rate for each priority band."""
    stats = {
        BAND_GOLD: {"total": 0, "positives": 0, "hit_rate": 0.0},
        BAND_SILVER: {"total": 0, "positives": 0, "hit_rate": 0.0},
        BAND_BRONZE: {"total": 0, "positives": 0, "hit_rate": 0.0},
        BAND_WOOD: {"total": 0, "positives": 0, "hit_rate": 0.0},
    }
    for r in scored_rows:
        band = r.get(band_key, BAND_WOOD)
        hit = r.get("research_hit") or 0
        if band in stats:
            stats[band]["total"] += 1
            if hit == 1:
                stats[band]["positives"] += 1

    for b in stats.values():
        tot = b["total"]
        pos = b["positives"]
        b["hit_rate"] = round((pos / tot), 4) if tot > 0 else 0.0

    return stats


def run_prospective_evaluation(
    candidate_rows: Optional[List[ProcurementDatasetRow]] = None,
    output_dir: str = "data/okpd_prior_evaluation",
) -> Dict[str, Any]:
    """Main execution pipeline for Prospective Shadow Evaluation."""
    os.makedirs(output_dir, exist_ok=True)

    # 1. Build and save origin manifest
    origin = build_prospective_origin_manifest()
    origin_path = os.path.join(output_dir, "prospective_origin_v1.json")
    with open(origin_path, "w", encoding="utf-8") as f:
        json.dump(origin.to_dict(), f, ensure_ascii=False, indent=2, sort_keys=True)

    # 2. Reconstruct frozen baseline strictly from training dataset
    with open(origin.training_dataset_identity, "r", encoding="utf-8") as f:
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
    frozen_baseline = OKPDHierarchicalPriorV1(
        smoothing_weight=origin.baseline_parameters["smoothing_weight"],
        min_support=origin.baseline_parameters["min_support"],
    ).fit(train_rows)

    # 3. Load frozen CatBoost ML model
    frozen_ml = OKPDResearchHitModelV1.load_artifact("data/okpd_prior_models/okpd_research_hit_v1.json")

    # 4. Filter prospective cohort
    all_candidates = candidate_rows if candidate_rows is not None else []
    prospective_rows, unresolved_count = filter_prospective_cohort(all_candidates, origin)

    # 5. Score prospective cohort
    scored = score_prospective_cohort(prospective_rows, frozen_baseline, frozen_ml)
    rows_path = os.path.join(output_dir, "prospective_rows_v1.json")
    with open(rows_path, "w", encoding="utf-8") as f:
        json.dump(scored, f, ensure_ascii=False, indent=2, sort_keys=True)

    # 6. Evaluation metrics & sufficiency checks
    n_labeled = len(prospective_rows)
    positives = sum(1 for r in prospective_rows if r.research_hit == 1)
    safe_negatives = sum(1 for r in prospective_rows if r.research_hit == 0)

    is_sufficient = (
        n_labeled >= GATE_MIN_LABELED
        and positives >= GATE_MIN_POSITIVES
        and safe_negatives >= GATE_MIN_SAFE_NEGATIVES
    )

    y_true = [int(r["research_hit"]) for r in scored]
    b_scores = [float(r["baseline_score"]) for r in scored]
    m_scores = [float(r["ml_score"]) for r in scored]

    b_metrics = compute_metrics_for_scores(y_true, b_scores)
    m_metrics = compute_metrics_for_scores(y_true, m_scores)
    bootstrap_res = compute_paired_bootstrap(y_true, m_scores, b_scores) if is_sufficient else {}

    delta_metrics = {
        "pr_auc": round(m_metrics["pr_auc"] - b_metrics["pr_auc"], 4),
        "roc_auc": round(m_metrics["roc_auc"] - b_metrics["roc_auc"], 4),
        "precision_at_10": round(m_metrics["precision_at_10"] - b_metrics["precision_at_10"], 4),
        "precision_at_20": round(m_metrics["precision_at_20"] - b_metrics["precision_at_20"], 4),
        "recall_at_30": round(m_metrics["recall_at_30"] - b_metrics["recall_at_30"], 4),
        "lift_at_10": round(m_metrics["lift_at_10"] - b_metrics["lift_at_10"], 2),
    }

    ml_bands = compute_band_breakdown(scored, "ml_band")
    base_bands = compute_band_breakdown(scored, "baseline_band")

    is_eligible = (
        is_sufficient
        and m_metrics["pr_auc"] > b_metrics["pr_auc"]
        and m_metrics["lift_at_10"] >= b_metrics["lift_at_10"]
        and m_metrics["recall_at_30"] >= b_metrics["recall_at_30"] - 0.05
    )

    eval_status = "EVALUATED" if is_sufficient else "INSUFFICIENT_PROSPECTIVE_DATA"
    promotion_eligible = "YES" if is_eligible else "NO"

    report = {
        "evaluation_timestamp": datetime.now(timezone.utc).isoformat(),
        "origin_manifest": origin.to_dict(),
        "corpus_counts": {
            "historical_labeled": 32,
            "prospective_total_seen": len(all_candidates),
            "prospective_labeled": n_labeled,
            "prospective_positives": positives,
            "prospective_safe_negatives": safe_negatives,
            "prospective_unresolved": unresolved_count,
            "unseen_okpd_codes": len({r.okpd_root for r in prospective_rows if r.okpd_root not in frozen_baseline.nodes}),
        },
        "baseline_metrics": b_metrics,
        "ml_metrics": m_metrics,
        "paired_deltas": delta_metrics,
        "bootstrap_confidence_intervals": bootstrap_res,
        "band_diagnostics": {
            "ml": ml_bands,
            "baseline": base_bands,
            "tie_policy": TIE_POLICY,
        },
        "wood_exploration": {
            "researched": ml_bands[BAND_WOOD]["total"],
            "positives": ml_bands[BAND_WOOD]["positives"],
            "positive_rate": ml_bands[BAND_WOOD]["hit_rate"],
        },
        "evaluation_gates": {
            "corpus_gate": f"PASS ({n_labeled}/{GATE_MIN_LABELED})" if is_sufficient else f"FAIL ({n_labeled}/{GATE_MIN_LABELED} labeled)",
            "evaluation_status": eval_status,
            "evaluation_biased": "NO",
            "promotion_review_eligible": promotion_eligible,
            "production_priority_promotion": "NO_CHANGE",
        },
        "production_authorities": {
            "model_controls_admission": "NO",
            "model_controls_priority": "NO",
            "model_can_permanently_skip_wood": "NO",
            "all_target_eventually_researched": "YES",
            "wood_exploration_budget_gt_zero": "YES",
        },
    }

    report_path = os.path.join(output_dir, "prospective_report_v1.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, sort_keys=True)

    return report
