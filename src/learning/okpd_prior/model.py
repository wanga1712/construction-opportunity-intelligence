"""Machine learning model for pre-research OKPD hit probability.

Implements MODEL_NAME = 'okpd_research_hit_v1'.
Uses hierarchical categorical OKPD features only:
okpd_root, okpd_level2, okpd_level3, okpd_full.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

from src.learning.okpd_prior.baseline import OKPDHierarchicalPriorV1
from src.learning.okpd_prior.dataset import ProcurementDatasetRow
from src.learning.okpd_prior.hierarchy import OKPDHierarchy, parse_okpd_hierarchy
from src.learning.okpd_prior.metrics import ModelEvaluationMetrics, evaluate_ranking_metrics

MODEL_NAME = "okpd_research_hit_v1"
MODEL_VERSION = "v1"

BAND_GOLD = "GOLD"
BAND_SILVER = "SILVER"
BAND_BRONZE = "BRONZE"
BAND_WOOD = "WOOD"


def assign_priority_band(percentile: float) -> str:
    """Assigns priority band based on scored population percentile.

    - GOLD: top 10% (percentile >= 0.90)
    - SILVER: next 20% (0.70 <= percentile < 0.90)
    - BRONZE: next 30% (0.40 <= percentile < 0.70)
    - WOOD: remaining 40% (percentile < 0.40)
    """
    if percentile >= 0.90:
        return BAND_GOLD
    elif percentile >= 0.70:
        return BAND_SILVER
    elif percentile >= 0.40:
        return BAND_BRONZE
    else:
        return BAND_WOOD


@dataclass
class ModelScoringResult:
    """Individual scored procurement item."""
    procurement_id: int
    p_research_hit: float
    priority_percentile: float
    priority_band: str
    okpd_code_raw: Optional[str]
    okpd_root: str
    okpd_level2: str
    okpd_level3: str
    okpd_full: str


class OKPDResearchHitModelV1:
    """Categorical ML Model for predicting research hit probability from OKPD hierarchy."""

    def __init__(self) -> None:
        self.model_name = MODEL_NAME
        self.model_version = MODEL_VERSION
        self.trained_at: Optional[str] = None
        self.dataset_snapshot_sha256: Optional[str] = None
        self.baseline_prior = OKPDHierarchicalPriorV1()
        self.feature_weights: Dict[str, float] = {}
        self.is_fitted = False

    def fit(
        self,
        train_rows: List[ProcurementDatasetRow],
        dataset_snapshot_sha256: Optional[str] = None,
    ) -> "OKPDResearchHitModelV1":
        """Fits the model on training rows."""
        self.baseline_prior.fit(train_rows)
        self.dataset_snapshot_sha256 = dataset_snapshot_sha256
        self.trained_at = datetime.now(timezone.utc).isoformat()
        self.is_fitted = True
        return self

    def predict_proba_single(self, hierarchy: OKPDHierarchy) -> float:
        """Predicts continuous research hit probability P(research_hit) in [0, 1]."""
        if not self.is_fitted:
            return 0.05
        pred = self.baseline_prior.predict(hierarchy)
        return pred.p_research_hit

    def score_population(
        self,
        rows: List[Dict[str, Any]],
    ) -> List[ModelScoringResult]:
        """Scores an arbitrary population of procurements and assigns relative percentiles and bands."""
        if not rows:
            return []

        raw_scored = []
        for r in rows:
            pid = r.get("procurement_id") or r.get("id")
            raw_okpd = r.get("okpd_code_raw") or r.get("okpd_code")
            h = parse_okpd_hierarchy(raw_okpd)
            p = self.predict_proba_single(h)
            raw_scored.append({
                "procurement_id": pid,
                "p_research_hit": p,
                "hierarchy": h,
                "raw_okpd": raw_okpd,
            })

        # Sort by p_research_hit ascending to compute percentiles
        n = len(raw_scored)
        # Sort stable by p_research_hit ascending, then pid
        sorted_items = sorted(raw_scored, key=lambda x: (x["p_research_hit"], x["procurement_id"]))
        
        results: List[ModelScoringResult] = []
        for rank, item in enumerate(sorted_items):
            # Percentile in [0.0, 1.0]: (rank + 1) / n
            percentile = round((rank + 1) / float(n), 4)
            band = assign_priority_band(percentile)
            h = item["hierarchy"]
            results.append(ModelScoringResult(
                procurement_id=item["procurement_id"],
                p_research_hit=item["p_research_hit"],
                priority_percentile=percentile,
                priority_band=band,
                okpd_code_raw=item["raw_okpd"],
                okpd_root=h.okpd_root,
                okpd_level2=h.okpd_level2,
                okpd_level3=h.okpd_level3,
                okpd_full=h.okpd_full,
            ))

        return results

    def save_artifact(self, filepath: str) -> None:
        """Serializes model parameters to JSON file."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        nodes_dict = {
            k: asdict(v) for k, v in self.baseline_prior.nodes.items()
        }
        payload = {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "trained_at": self.trained_at,
            "dataset_snapshot_sha256": self.dataset_snapshot_sha256,
            "global_prior": self.baseline_prior.global_prior,
            "global_total": self.baseline_prior.global_total,
            "global_positive": self.baseline_prior.global_positive,
            "nodes": nodes_dict,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    @classmethod
    def load_artifact(cls, filepath: str) -> "OKPDResearchHitModelV1":
        """Loads model from serialized JSON artifact."""
        with open(filepath, "r", encoding="utf-8") as f:
            payload = json.load(f)

        model = cls()
        model.model_name = payload["model_name"]
        model.model_version = payload["model_version"]
        model.trained_at = payload.get("trained_at")
        model.dataset_snapshot_sha256 = payload.get("dataset_snapshot_sha256")
        
        from src.learning.okpd_prior.baseline import PriorNodeStats
        model.baseline_prior.global_prior = payload["global_prior"]
        model.baseline_prior.global_total = payload["global_total"]
        model.baseline_prior.global_positive = payload["global_positive"]
        model.baseline_prior.nodes = {
            k: PriorNodeStats(**v) for k, v in payload["nodes"].items()
        }
        model.baseline_prior.is_fitted = True
        model.is_fitted = True
        return model
