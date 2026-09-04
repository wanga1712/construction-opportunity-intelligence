"""Combined Research Priority Model V2 (research_priority_v2).

Combines semantic text representations, domain disambiguation signals, hierarchical
OKPD features, and lot price into a unified learned procurement prioritization model.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
import pickle
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from src.learning.okpd_prior.disambiguation import extract_domain_signals
from src.learning.okpd_prior.dto import ShadowPredictionDTO
from src.learning.okpd_prior.hierarchy import parse_okpd_hierarchy
from src.learning.okpd_prior.model import (
    BAND_BRONZE,
    BAND_GOLD,
    BAND_SILVER,
    BAND_WOOD,
    assign_priority_band,
)
from src.learning.okpd_prior.semantic_model import TitleSemanticModelV2


MODEL_NAME_V2 = "research_priority_v2"
MODEL_TYPE_V2 = "COMBINED_SEMANTIC_HIERARCHICAL_GBDT"
FEATURE_NAMES_V2 = [
    "semantic_score",
    "construction_prior",
    "medical_risk",
    "it_electronics_risk",
    "furniture_risk",
    "food_risk",
    "works_signal",
    "log_price",
    "okpd_root_enc",
    "okpd_level2_enc",
    "okpd_level3_enc",
    "okpd_full_enc",
]


class ResearchPriorityModelV2:
    """Stage 1 V2 Learned Classifier combining Semantic Text, Domain Signals & OKPD."""

    def __init__(self, random_state: int = 42) -> None:
        self.random_state = random_state
        self.semantic_model = TitleSemanticModelV2()
        self.gbdt: Optional[HistGradientBoostingClassifier] = None
        self.okpd_encodings: Dict[str, Dict[str, float]] = {
            "root": {},
            "level2": {},
            "level3": {},
            "full": {},
        }
        self.is_fitted = False
        self.training_sample_count = 0
        self.positive_count = 0
        self.trained_at: Optional[str] = None
        self.dataset_snapshot_sha256: Optional[str] = None

    def _build_target_encodings(
        self,
        okpd_tuples: List[Tuple[str, str, str, str]],
        y: List[int],
    ) -> None:
        """Computes empirical smoothed target encodings for OKPD hierarchy levels."""
        global_mean = sum(y) / len(y) if y else 0.23
        smoothing = 5.0

        counts: Dict[str, Dict[str, Tuple[int, int]]] = {
            "root": {},
            "level2": {},
            "level3": {},
            "full": {},
        }

        for (root, l2, l3, full), label in zip(okpd_tuples, y):
            for level, val in [("root", root), ("level2", l2), ("level3", l3), ("full", full)]:
                pos, tot = counts[level].get(val, (0, 0))
                counts[level][val] = (pos + label, tot + 1)

        for level in ("root", "level2", "level3", "full"):
            self.okpd_encodings[level] = {}
            for val, (pos, tot) in counts[level].items():
                smoothed = (pos + smoothing * global_mean) / (tot + smoothing)
                self.okpd_encodings[level][val] = float(smoothed)

    def _get_okpd_encoded_value(self, level: str, val: str) -> float:
        """Retrieves smoothed target encoded value for an OKPD string."""
        return self.okpd_encodings.get(level, {}).get(val, 0.23)

    def _extract_tabular_features(
        self,
        semantic_scores: List[float],
        titles: List[str],
        okpd_tuples: List[Tuple[str, str, str, str]],
        prices: List[float],
    ) -> np.ndarray:
        """Builds feature matrix from inputs."""
        rows = []
        for sem, title, (root, l2, l3, full), price in zip(
            semantic_scores, titles, okpd_tuples, prices
        ):
            sig = extract_domain_signals(title, full)
            log_p = float(math.log1p(max(0.0, price))) if price else 0.0

            r_enc = self._get_okpd_encoded_value("root", root)
            l2_enc = self._get_okpd_encoded_value("level2", l2)
            l3_enc = self._get_okpd_encoded_value("level3", l3)
            full_enc = self._get_okpd_encoded_value("full", full)

            rows.append([
                sem,
                sig["construction_prior"],
                sig["medical_risk"],
                sig["it_electronics_risk"],
                sig["furniture_risk"],
                sig["food_risk"],
                sig["works_signal"],
                log_p,
                r_enc,
                l2_enc,
                l3_enc,
                full_enc,
            ])
        return np.array(rows, dtype=np.float32)

    def fit(
        self,
        titles: List[str],
        okpd_codes: List[str],
        prices: List[float],
        y: List[int],
        dataset_snapshot_sha256: Optional[str] = None,
    ) -> "ResearchPriorityModelV2":
        """Fits combined model on full dataset using OOF stacking for semantic features."""
        if not titles or not y or len(titles) != len(y):
            raise ValueError("Titles and labels must be of equal non-zero length.")

        n = len(titles)
        if len(okpd_codes) != n:
            okpd_codes = ["" for _ in range(n)]
        if len(prices) != n:
            prices = [0.0 for _ in range(n)]

        hierarchies = [parse_okpd_hierarchy(c) for c in okpd_codes]
        okpd_tuples = [
            (h.okpd_root, h.okpd_level2, h.okpd_level3, h.okpd_full) for h in hierarchies
        ]

        # 1. Compute target encodings
        self._build_target_encodings(okpd_tuples, y)

        # 2. Get OOF semantic scores
        oof_semantic_scores = self.semantic_model.fit_oof_predictions(
            titles, okpd_codes, y, n_splits=5
        )

        # 3. Extract tabular features
        x_train = self._extract_tabular_features(
            list(oof_semantic_scores), titles, okpd_tuples, prices
        )

        # 4. Fit Gradient Boosting model
        self.gbdt = HistGradientBoostingClassifier(
            max_iter=150,
            learning_rate=0.05,
            max_leaf_nodes=15,
            min_samples_leaf=3,
            class_weight="balanced",
            random_state=self.random_state,
        )
        self.gbdt.fit(x_train, y)

        self.is_fitted = True
        self.training_sample_count = n
        self.positive_count = sum(y)
        self.trained_at = datetime.now(timezone.utc).isoformat()
        self.dataset_snapshot_sha256 = dataset_snapshot_sha256
        return self

    def predict_proba(
        self,
        titles: List[str],
        okpd_codes: Optional[List[str]] = None,
        prices: Optional[List[float]] = None,
    ) -> List[float]:
        """Predicts probability P(RESEARCH_HIT) for test items."""
        if not self.is_fitted or self.gbdt is None:
            raise RuntimeError("Model is not fitted.")

        n = len(titles)
        if n == 0:
            return []

        if okpd_codes is None or len(okpd_codes) != n:
            okpd_codes = ["" for _ in range(n)]
        if prices is None or len(prices) != n:
            prices = [0.0 for _ in range(n)]

        hierarchies = [parse_okpd_hierarchy(c) for c in okpd_codes]
        okpd_tuples = [
            (h.okpd_root, h.okpd_level2, h.okpd_level3, h.okpd_full) for h in hierarchies
        ]

        sem_scores = self.semantic_model.predict_proba(titles, okpd_codes)
        x_test = self._extract_tabular_features(sem_scores, titles, okpd_tuples, prices)

        probs = self.gbdt.predict_proba(x_test)
        classes = list(self.gbdt.classes_)
        if 1 in classes:
            idx = classes.index(1)
            return [float(p[idx]) for p in probs]
        return [0.0 for _ in probs]

    def predict_one(self, title: str, okpd_code: str = "", price: float = 0.0) -> float:
        """Predicts probability for a single item."""
        res = self.predict_proba([title], [okpd_code], [price])
        return res[0] if res else 0.0

    def score_population(
        self,
        procurements: List[Dict[str, Any]],
        model_version: str = "v2",
    ) -> List[ShadowPredictionDTO]:
        """Scores a population of procurements and produces tie-safe ranked DTOs."""
        if not procurements:
            return []

        titles = [str(p.get("auction_name") or p.get("title") or "") for p in procurements]
        okpds = [str(p.get("okpd_code") or p.get("okpd_raw") or "") for p in procurements]
        prices = [float(p.get("lot_price") or p.get("initial_price") or 0.0) for p in procurements]

        probs = self.predict_proba(titles, okpds, prices)
        n = len(procurements)

        all_scores = [float(p) for p in probs]
        now_iso = datetime.now(timezone.utc).isoformat()

        results: List[ShadowPredictionDTO] = []
        for i, (p, prob) in enumerate(zip(procurements, probs)):
            pid = p.get("procurement_id") or p.get("id") or 0
            hier = parse_okpd_hierarchy(okpds[i])
            score = float(prob)

            # Tie-safe percentile: fraction of population with score <= item score
            count_le = sum(1 for s in all_scores if s <= score)
            percentile = round(count_le / float(n), 4)
            band = assign_priority_band(percentile)

            results.append(
                ShadowPredictionDTO(
                    procurement_id=int(pid),
                    model_name=MODEL_NAME_V2,
                    model_version=model_version,
                    trained_at=self.trained_at,
                    dataset_snapshot_sha256=self.dataset_snapshot_sha256,
                    p_research_hit=score,
                    priority_percentile=percentile,
                    priority_band=band,
                    okpd_code_raw=hier.okpd_raw,
                    okpd_root=hier.okpd_root,
                    okpd_level2=hier.okpd_level2,
                    okpd_level3=hier.okpd_level3,
                    okpd_full=hier.okpd_full,
                    prediction_created_at=now_iso,
                    shadow_only=True,
                )
            )

        return results

    def save_artifact(self, filepath: str) -> None:
        """Saves fitted model to artifact."""
        if not self.is_fitted:
            raise RuntimeError("Cannot save unfitted model.")
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        meta = {
            "model_name": MODEL_NAME_V2,
            "model_type": MODEL_TYPE_V2,
            "feature_names": FEATURE_NAMES_V2,
            "training_sample_count": self.training_sample_count,
            "positive_count": self.positive_count,
            "trained_at": self.trained_at,
            "dataset_snapshot_sha256": self.dataset_snapshot_sha256,
            "okpd_encodings": self.okpd_encodings,
        }
        with open(filepath, "wb") as f:
            pickle.dump({
                "meta": meta,
                "semantic_model": self.semantic_model,
                "gbdt": self.gbdt,
                "okpd_encodings": self.okpd_encodings,
            }, f)

    @classmethod
    def load_artifact(cls, filepath: str) -> "ResearchPriorityModelV2":
        """Loads fitted model from artifact."""
        with open(filepath, "rb") as f:
            data = pickle.load(f)
        meta = data.get("meta", {})
        instance = cls()
        instance.semantic_model = data.get("semantic_model")
        instance.gbdt = data.get("gbdt")
        instance.okpd_encodings = data.get("okpd_encodings", {})
        instance.is_fitted = True
        instance.training_sample_count = meta.get("training_sample_count", 0)
        instance.positive_count = meta.get("positive_count", 0)
        instance.trained_at = meta.get("trained_at")
        instance.dataset_snapshot_sha256 = meta.get("dataset_snapshot_sha256")
        return instance
