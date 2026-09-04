"""Categorical Machine Learning model for pre-research OKPD hit probability.

Implements MODEL_NAME = 'okpd_research_hit_v1' via CatBoostClassifier.
Input features are STRICTLY pre-research hierarchical OKPD categories:
- okpd_root
- okpd_level2
- okpd_level3
- okpd_full

Contains ZERO post-research fields, document counts, or candidate outcomes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.learning.okpd_prior.dataset import ProcurementDatasetRow
from src.learning.okpd_prior.hierarchy import OKPDHierarchy, parse_okpd_hierarchy

logger = logging.getLogger("crm.learning.okpd_prior.model")

MODEL_NAME = "okpd_research_hit_v1"
MODEL_VERSION = "v1"
MODEL_TYPE = "CatBoostClassifier"
FEATURE_NAMES = ["okpd_root", "okpd_level2", "okpd_level3", "okpd_full"]

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
    """Individual scored procurement item with tie-safe percentile and band."""
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
    """Genuinely learned categorical ML model for predicting research hit probability."""

    def __init__(self) -> None:
        self.model_name = MODEL_NAME
        self.model_version = MODEL_VERSION
        self.model_type = MODEL_TYPE
        self.feature_names = list(FEATURE_NAMES)
        self.trained_at: Optional[str] = None
        self.dataset_snapshot_sha256: Optional[str] = None
        self.training_row_count: int = 0
        self.positive_count: int = 0
        self.negative_count: int = 0
        self.hyperparameters: Dict[str, Any] = {}
        self.cbm_artifact_path: Optional[str] = None
        self._fallback_prior: float = 0.05
        self._single_class_prediction: Optional[float] = None
        self._model: Any = None
        self.is_fitted: bool = False

    def fit(
        self,
        train_rows: List[ProcurementDatasetRow],
        dataset_snapshot_sha256: Optional[str] = None,
    ) -> "OKPDResearchHitModelV1":
        """Fits the CatBoost classifier on training rows using only pre-research OKPD features."""
        usable = [r for r in train_rows if r.research_hit is not None]
        self.dataset_snapshot_sha256 = dataset_snapshot_sha256
        self.trained_at = datetime.now(timezone.utc).isoformat()
        self.training_row_count = len(usable)
        self.positive_count = sum(1 for r in usable if r.research_hit == 1)
        self.negative_count = self.training_row_count - self.positive_count
        self._fallback_prior = (
            round(self.positive_count / float(self.training_row_count), 4)
            if self.training_row_count > 0
            else 0.05
        )

        if not usable:
            self.is_fitted = True
            return self

        import pandas as pd

        X_dicts = [r.to_feature_dict() for r in usable]
        df_X = pd.DataFrame(X_dicts, columns=self.feature_names)
        # Ensure all columns are strings for categorical encoding
        for col in self.feature_names:
            df_X[col] = df_X[col].astype(str)

        y = [r.research_hit for r in usable]

        # Handle single class edge cases (e.g. all 0s or all 1s in small mock splits)
        unique_classes = set(y)
        if len(unique_classes) < 2:
            self._single_class_prediction = float(y[0])
            self.hyperparameters = {"single_class": y[0]}
            self.is_fitted = True
            return self

        try:
            from catboost import CatBoostClassifier
            params = {
                "iterations": 150,
                "learning_rate": 0.03,
                "depth": 3,
                "loss_function": "Logloss",
                "random_seed": 42,
                "verbose": False,
            }
            self.hyperparameters = params
            cb = CatBoostClassifier(**params)
            cb.fit(df_X, y, cat_features=self.feature_names, verbose=False)
            self._model = cb
            self.model_type = "CatBoostClassifier"
            self.is_fitted = True
        except ImportError:
            logger.warning("CatBoost not found in runtime, falling back to scikit-learn LogisticRegression")
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import Pipeline
            from sklearn.preprocessing import OneHotEncoder

            pipe = Pipeline([
                ("ohe", OneHotEncoder(handle_unknown="ignore")),
                ("clf", LogisticRegression(random_state=42, max_iter=200)),
            ])
            pipe.fit(df_X, y)
            self._model = pipe
            self.model_type = "LogisticRegressionPipeline"
            self.is_fitted = True

        return self

    def predict_proba_single(self, hierarchy: OKPDHierarchy) -> float:
        """Predicts continuous research hit probability P(research_hit) in [0, 1]."""
        if not self.is_fitted:
            return self._fallback_prior

        if self._single_class_prediction is not None:
            return self._single_class_prediction

        if self._model is not None:
            import pandas as pd
            feat_dict = {
                "okpd_root": [str(hierarchy.okpd_root)],
                "okpd_level2": [str(hierarchy.okpd_level2)],
                "okpd_level3": [str(hierarchy.okpd_level3)],
                "okpd_full": [str(hierarchy.okpd_full)],
            }
            df = pd.DataFrame(feat_dict, columns=self.feature_names)
            try:
                proba = float(self._model.predict_proba(df)[0][1])
                return round(max(0.0001, min(0.9999, proba)), 4)
            except Exception as e:
                logger.warning(f"Predict_proba failed: {e}")
                return self._fallback_prior

        return self._fallback_prior

    def score_population(
        self,
        rows: List[Dict[str, Any]],
    ) -> List[ModelScoringResult]:
        """Scores an arbitrary population of procurements and assigns tie-safe percentiles and bands.

        Invariant:
            if p_research_hit(A) == p_research_hit(B)
            then priority_percentile(A) == priority_percentile(B)
            and priority_band(A) == priority_band(B)

        Tie policy: MAX_RANK (fraction of population with score <= item score).
        """
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

        n = len(raw_scored)
        all_scores = [item["p_research_hit"] for item in raw_scored]

        results: List[ModelScoringResult] = []
        for item in raw_scored:
            score = item["p_research_hit"]
            # Tie-safe percentile: fraction of items with score <= current score
            count_le = sum(1 for s in all_scores if s <= score)
            percentile = round(count_le / float(n), 4)
            band = assign_priority_band(percentile)
            h = item["hierarchy"]
            results.append(ModelScoringResult(
                procurement_id=item["procurement_id"],
                p_research_hit=score,
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
        """Serializes model parameters and optional CatBoost binary artifact."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        base_path = os.path.splitext(filepath)[0]
        cbm_path = base_path + ".cbm"

        if self._model is not None and hasattr(self._model, "save_model"):
            try:
                self._model.save_model(cbm_path)
                self.cbm_artifact_path = cbm_path
            except Exception as e:
                logger.warning(f"Could not save CatBoost model to {cbm_path}: {e}")

        payload = {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "model_type": self.model_type,
            "trained_at": self.trained_at,
            "dataset_snapshot_sha256": self.dataset_snapshot_sha256,
            "feature_names": self.feature_names,
            "training_row_count": self.training_row_count,
            "positive_count": self.positive_count,
            "negative_count": self.negative_count,
            "hyperparameters": self.hyperparameters,
            "fallback_prior": self._fallback_prior,
            "single_class_prediction": self._single_class_prediction,
            "cbm_artifact_path": self.cbm_artifact_path,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    @classmethod
    def load_artifact(cls, filepath: str) -> "OKPDResearchHitModelV1":
        """Loads model from serialized JSON metadata and optional binary artifact."""
        with open(filepath, "r", encoding="utf-8") as f:
            payload = json.load(f)

        model = cls()
        model.model_name = payload["model_name"]
        model.model_version = payload["model_version"]
        model.model_type = payload.get("model_type", MODEL_TYPE)
        model.trained_at = payload.get("trained_at")
        model.dataset_snapshot_sha256 = payload.get("dataset_snapshot_sha256")
        model.feature_names = payload.get("feature_names", list(FEATURE_NAMES))
        model.training_row_count = payload.get("training_row_count", 0)
        model.positive_count = payload.get("positive_count", 0)
        model.negative_count = payload.get("negative_count", 0)
        model.hyperparameters = payload.get("hyperparameters", {})
        model._fallback_prior = payload.get("fallback_prior", 0.05)
        model._single_class_prediction = payload.get("single_class_prediction")
        model.cbm_artifact_path = payload.get("cbm_artifact_path")

        cbm_file = model.cbm_artifact_path
        if not cbm_file or not os.path.exists(cbm_file):
            candidate_cbm = os.path.splitext(filepath)[0] + ".cbm"
            if os.path.exists(candidate_cbm):
                cbm_file = candidate_cbm

        if cbm_file and os.path.exists(cbm_file):
            try:
                from catboost import CatBoostClassifier
                cb = CatBoostClassifier()
                cb.load_model(cbm_file)
                model._model = cb
            except Exception as e:
                logger.warning(f"Could not load CatBoost binary model from {cbm_file}: {e}")

        model.is_fitted = True
        return model
