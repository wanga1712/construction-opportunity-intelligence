"""Evaluation metrics and ranking benchmarks for research hit models.

Computes ROC-AUC, PR-AUC, Precision@K%, Recall@K%, and Lift@K%.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class ModelEvaluationMetrics:
    """Comprehensive ranking and discrimination metrics."""
    total_samples: int
    positive_count: int
    negative_count: int
    base_positive_rate: float
    roc_auc: float
    pr_auc: float
    precision_at_5: float
    precision_at_10: float
    precision_at_20: float
    recall_at_5: float
    recall_at_10: float
    recall_at_20: float
    recall_at_30: float
    lift_at_5: float
    lift_at_10: float
    lift_at_20: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_roc_auc(y_true: List[int], y_score: List[float]) -> float:
    """Computes Area Under the ROC Curve without external dependencies."""
    n = len(y_true)
    pos = sum(y_true)
    neg = n - pos
    if pos == 0 or neg == 0:
        return 0.5

    # Pair items and sort by score descending
    pairs = sorted(zip(y_score, y_true), key=lambda p: p[0], reverse=True)
    
    # Trapezoidal approximation
    tp = 0
    fp = 0
    tp_prev = 0
    fp_prev = 0
    auc = 0.0

    for score, target in pairs:
        if target == 1:
            tp += 1
        else:
            fp += 1
            # Add trapezoid area
            auc += (tp + tp_prev) / 2.0
            tp_prev = tp
            fp_prev = fp

    return round(auc / (pos * neg), 4)


def compute_pr_auc(y_true: List[int], y_score: List[float]) -> float:
    """Computes Area Under the Precision-Recall Curve without external dependencies."""
    n = len(y_true)
    total_pos = sum(y_true)
    if total_pos == 0:
        return 0.0

    pairs = sorted(zip(y_score, y_true), key=lambda p: p[0], reverse=True)
    
    tp = 0
    fp = 0
    prev_recall = 0.0
    auc = 0.0

    for score, target in pairs:
        if target == 1:
            tp += 1
        else:
            fp += 1
        
        recall = tp / total_pos
        precision = tp / (tp + fp)
        auc += precision * (recall - prev_recall)
        prev_recall = recall

    return round(auc, 4)


def evaluate_ranking_metrics(
    y_true: List[int],
    y_score: List[float],
) -> ModelEvaluationMetrics:
    """Calculates all mandatory ranking and classification metrics.

    Args:
        y_true: List of binary ground truth labels (0 or 1).
        y_score: List of continuous predicted probabilities.

    Returns:
        ModelEvaluationMetrics instance.
    """
    n = len(y_true)
    if n == 0:
        return ModelEvaluationMetrics(
            total_samples=0, positive_count=0, negative_count=0, base_positive_rate=0.0,
            roc_auc=0.5, pr_auc=0.0, precision_at_5=0.0, precision_at_10=0.0, precision_at_20=0.0,
            recall_at_5=0.0, recall_at_10=0.0, recall_at_20=0.0, recall_at_30=0.0,
            lift_at_5=1.0, lift_at_10=1.0, lift_at_20=1.0,
        )

    pos_count = sum(y_true)
    neg_count = n - pos_count
    base_rate = (pos_count / n) if n > 0 else 0.0

    roc_auc = compute_roc_auc(y_true, y_score)
    pr_auc = compute_pr_auc(y_true, y_score)

    pairs = sorted(zip(y_score, y_true), key=lambda p: p[0], reverse=True)

    def _top_k_metrics(pct: float) -> Tuple[float, float, float]:
        k = max(1, int(math.ceil(n * (pct / 100.0))))
        top_slice = pairs[:k]
        hits = sum(p[1] for p in top_slice)
        prec = (hits / k) if k > 0 else 0.0
        rec = (hits / pos_count) if pos_count > 0 else 0.0
        lift = (prec / base_rate) if base_rate > 0 else 1.0
        return round(prec, 4), round(rec, 4), round(lift, 2)

    p5, r5, l5 = _top_k_metrics(5.0)
    p10, r10, l10 = _top_k_metrics(10.0)
    p20, r20, l20 = _top_k_metrics(20.0)
    _, r30, _ = _top_k_metrics(30.0)

    return ModelEvaluationMetrics(
        total_samples=n,
        positive_count=pos_count,
        negative_count=neg_count,
        base_positive_rate=round(base_rate, 4),
        roc_auc=roc_auc,
        pr_auc=pr_auc,
        precision_at_5=p5,
        precision_at_10=p10,
        precision_at_20=p20,
        recall_at_5=r5,
        recall_at_10=r10,
        recall_at_20=r20,
        recall_at_30=r30,
        lift_at_5=l5,
        lift_at_10=l10,
        lift_at_20=l20,
    )


def compute_brier_score(y_true: List[int], y_score: List[float]) -> float:
    """Computes Mean Squared Error (Brier Score) between predictions and ground truth."""
    if not y_true or len(y_true) != len(y_score):
        return 0.0
    errors = [(p - y) ** 2 for p, y in zip(y_score, y_true)]
    return round(float(sum(errors) / len(errors)), 4)


def compute_metrics_for_scores(
    y_true: List[int],
    y_score: List[float],
) -> Dict[str, float]:
    """Calculates PR_AUC, ROC_AUC, Precision@K, Recall@K, Lift@K, Brier Score as dict."""
    n = len(y_true)
    if n == 0:
        return {
            "pr_auc": 0.0, "roc_auc": 0.5,
            "precision_at_5": 0.0, "precision_at_10": 0.0, "precision_at_20": 0.0, "precision_at_30": 0.0,
            "recall_at_5": 0.0, "recall_at_10": 0.0, "recall_at_20": 0.0, "recall_at_30": 0.0,
            "lift_at_5": 1.0, "lift_at_10": 1.0, "lift_at_20": 1.0, "brier_score": 0.0,
        }

    pos_count = sum(y_true)
    base_rate = (pos_count / n) if n > 0 else 0.0

    roc_auc = compute_roc_auc(y_true, y_score)
    pr_auc = compute_pr_auc(y_true, y_score)
    brier = compute_brier_score(y_true, y_score)

    pairs = sorted(zip(y_score, y_true), key=lambda p: p[0], reverse=True)

    def _k_metrics(pct: float) -> Tuple[float, float, float]:
        k = max(1, int(math.ceil(n * (pct / 100.0))))
        top_slice = pairs[:k]
        hits = sum(p[1] for p in top_slice)
        prec = (hits / k) if k > 0 else 0.0
        rec = (hits / pos_count) if pos_count > 0 else 0.0
        lift = (prec / base_rate) if base_rate > 0 else 1.0
        return round(prec, 4), round(rec, 4), round(lift, 2)

    p5, r5, l5 = _k_metrics(5.0)
    p10, r10, l10 = _k_metrics(10.0)
    p20, r20, l20 = _k_metrics(20.0)
    p30, r30, _ = _k_metrics(30.0)

    return {
        "pr_auc": pr_auc,
        "roc_auc": roc_auc,
        "precision_at_5": p5,
        "precision_at_10": p10,
        "precision_at_20": p20,
        "precision_at_30": p30,
        "recall_at_5": r5,
        "recall_at_10": r10,
        "recall_at_20": r20,
        "recall_at_30": r30,
        "lift_at_5": l5,
        "lift_at_10": l10,
        "lift_at_20": l20,
        "brier_score": brier,
    }


def compute_paired_bootstrap(
    y_true: List[int],
    ml_scores: List[float],
    baseline_scores: List[float],
    n_bootstraps: int = 2000,
    seed: int = 42,
) -> Dict[str, Dict[str, float]]:
    """Runs paired bootstrap resamples to compute 95% confidence intervals for (ML - Baseline)."""
    import numpy as np

    n = len(y_true)
    if n < 5 or sum(y_true) == 0 or sum(y_true) == n:
        return {}

    rng = np.random.default_rng(seed)
    indices = np.arange(n)

    delta_pr: List[float] = []
    delta_roc: List[float] = []
    delta_p10: List[float] = []
    delta_p20: List[float] = []
    delta_r30: List[float] = []
    delta_lift10: List[float] = []

    for _ in range(n_bootstraps):
        sample_idx = rng.choice(indices, size=n, replace=True)
        y_samp = [y_true[i] for i in sample_idx]
        if sum(y_samp) == 0 or sum(y_samp) == n:
            continue

        ml_samp = [ml_scores[i] for i in sample_idx]
        b_samp = [baseline_scores[i] for i in sample_idx]

        m_res = compute_metrics_for_scores(y_samp, ml_samp)
        b_res = compute_metrics_for_scores(y_samp, b_samp)

        delta_pr.append(m_res["pr_auc"] - b_res["pr_auc"])
        delta_roc.append(m_res["roc_auc"] - b_res["roc_auc"])
        delta_p10.append(m_res["precision_at_10"] - b_res["precision_at_10"])
        delta_p20.append(m_res["precision_at_20"] - b_res["precision_at_20"])
        delta_r30.append(m_res["recall_at_30"] - b_res["recall_at_30"])
        delta_lift10.append(m_res["lift_at_10"] - b_res["lift_at_10"])

    def _ci(arr: List[float]) -> Dict[str, float]:
        if not arr:
            return {"mean": 0.0, "ci_lower": 0.0, "ci_upper": 0.0}
        return {
            "mean": round(float(np.mean(arr)), 4),
            "ci_lower": round(float(np.percentile(arr, 2.5)), 4),
            "ci_upper": round(float(np.percentile(arr, 97.5)), 4),
        }

    return {
        "pr_auc": _ci(delta_pr),
        "roc_auc": _ci(delta_roc),
        "precision_at_10": _ci(delta_p10),
        "precision_at_20": _ci(delta_p20),
        "recall_at_30": _ci(delta_r30),
        "lift_at_10": _ci(delta_lift10),
    }

