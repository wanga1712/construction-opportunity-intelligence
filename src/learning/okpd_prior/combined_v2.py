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
TEXT_REPRESENTATION_TYPE = "TFIDF_WORD_CHAR_PLUS_DOMAIN_FEATURES"
NEURAL_EMBEDDINGS_USED = False
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
        self.training_global_positive_rate: float = 0.23
        self.target_encoding_smoothing: float = 5.0
        self.target_encoding_levels: List[str] = ["root", "level2", "level3", "full"]
        self.is_fitted = False
        self.training_sample_count = 0
        self.positive_count = 0
        self.trained_at: Optional[str] = None
        self.dataset_snapshot_sha256: Optional[str] = None

    @staticmethod
    def _compute_target_encoding_dict(
        okpd_tuples: List[Tuple[str, str, str, str]],
        y: List[int],
        global_mean: float,
        smoothing: float = 5.0,
    ) -> Dict[str, Dict[str, float]]:
        """Computes empirical smoothed target encodings dictionary from data split."""
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

        result: Dict[str, Dict[str, float]] = {}
        for level in ("root", "level2", "level3", "full"):
            result[level] = {}
            for val, (pos, tot) in counts[level].items():
                smoothed = (pos + smoothing * global_mean) / (tot + smoothing)
                result[level][val] = float(smoothed)
        return result

    def _build_target_encodings(
        self,
        okpd_tuples: List[Tuple[str, str, str, str]],
        y: List[int],
    ) -> None:
        """Computes full empirical smoothed target encodings for inference."""
        global_mean = sum(y) / len(y) if y else self.training_global_positive_rate
        self.training_global_positive_rate = float(global_mean)
        self.okpd_encodings = self._compute_target_encoding_dict(
            okpd_tuples, y, global_mean, self.target_encoding_smoothing
        )

    def _get_okpd_encoded_value(
        self,
        level: str,
        val: str,
        encoding_dict: Optional[Dict[str, Dict[str, float]]] = None,
        fallback_rate: Optional[float] = None,
    ) -> float:
        """Retrieves smoothed target encoded value with dynamic fallback."""
        d = encoding_dict if encoding_dict is not None else self.okpd_encodings
        fb = fallback_rate if fallback_rate is not None else self.training_global_positive_rate
        return d.get(level, {}).get(val, fb)

    def _extract_tabular_features(
        self,
        semantic_scores: List[float],
        titles: List[str],
        okpd_tuples: List[Tuple[str, str, str, str]],
        prices: List[float],
        okpd_encodings_per_row: Optional[List[Tuple[float, float, float, float]]] = None,
    ) -> np.ndarray:
        """Builds feature matrix from inputs."""
        rows = []
        for i, (sem, title, (root, l2, l3, full), price) in enumerate(
            zip(semantic_scores, titles, okpd_tuples, prices)
        ):
            sig = extract_domain_signals(title, full)
            log_p = float(math.log1p(max(0.0, price))) if price else 0.0

            if okpd_encodings_per_row is not None and i < len(okpd_encodings_per_row):
                r_enc, l2_enc, l3_enc, full_enc = okpd_encodings_per_row[i]
            else:
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
        """Fits combined model using cross-fitted OOF representations for both text and OKPD."""
        if not titles or not y or len(titles) != len(y):
            raise ValueError("Titles and labels must be of equal non-zero length.")

        n = len(titles)
        if len(okpd_codes) != n:
            okpd_codes = ["" for _ in range(n)]
        if len(prices) != n:
            prices = [0.0 for _ in range(n)]

        self.training_global_positive_rate = float(sum(y) / len(y)) if y else 0.23
        hierarchies = [parse_okpd_hierarchy(c) for c in okpd_codes]
        okpd_tuples = [
            (h.okpd_root, h.okpd_level2, h.okpd_level3, h.okpd_full) for h in hierarchies
        ]

        # 1. Compute OOF semantic scores (leakage-free)
        oof_semantic_scores = self.semantic_model.fit_oof_predictions(
            titles, okpd_codes, y, n_splits=5
        )

        # 2. Compute OOF OKPD target encodings (each training row's label does NOT participate in its encoding)
        from sklearn.model_selection import StratifiedKFold
        oof_okpd_encs: List[Tuple[float, float, float, float]] = [(0.0, 0.0, 0.0, 0.0)] * n
        pos_cnt = sum(y)
        neg_cnt = n - pos_cnt
        actual_splits = min(5, min(pos_cnt, neg_cnt))

        if actual_splits >= 2:
            skf = StratifiedKFold(n_splits=actual_splits, shuffle=True, random_state=self.random_state)
            for tr_idx, val_idx in skf.split(titles, y):
                tr_tuples = [okpd_tuples[i] for i in tr_idx]
                tr_y = [y[i] for i in tr_idx]
                tr_mean = sum(tr_y) / len(tr_y) if tr_y else self.training_global_positive_rate
                fold_enc_dict = self._compute_target_encoding_dict(
                    tr_tuples, tr_y, tr_mean, self.target_encoding_smoothing
                )

                for vi in val_idx:
                    root, l2, l3, full = okpd_tuples[vi]
                    r_e = self._get_okpd_encoded_value("root", root, fold_enc_dict, tr_mean)
                    l2_e = self._get_okpd_encoded_value("level2", l2, fold_enc_dict, tr_mean)
                    l3_e = self._get_okpd_encoded_value("level3", l3, fold_enc_dict, tr_mean)
                    f_e = self._get_okpd_encoded_value("full", full, fold_enc_dict, tr_mean)
                    oof_okpd_encs[vi] = (r_e, l2_e, l3_e, f_e)
        else:
            # Fallback for very small non-splittable sample
            full_dict = self._compute_target_encoding_dict(
                okpd_tuples, y, self.training_global_positive_rate, self.target_encoding_smoothing
            )
            for vi in range(n):
                root, l2, l3, full = okpd_tuples[vi]
                r_e = self._get_okpd_encoded_value("root", root, full_dict)
                l2_e = self._get_okpd_encoded_value("level2", l2, full_dict)
                l3_e = self._get_okpd_encoded_value("level3", l3, full_dict)
                f_e = self._get_okpd_encoded_value("full", full, full_dict)
                oof_okpd_encs[vi] = (r_e, l2_e, l3_e, f_e)

        # 3. Extract training tabular features using OOF inputs
        x_train = self._extract_tabular_features(
            list(oof_semantic_scores), titles, okpd_tuples, prices, oof_okpd_encs
        )

        # 4. Fit Gradient Boosting model
        min_leaf = max(1, min(3, n // 5))
        self.gbdt = HistGradientBoostingClassifier(
            max_iter=150,
            learning_rate=0.05,
            max_leaf_nodes=15,
            min_samples_leaf=min_leaf,
            class_weight="balanced",
            random_state=self.random_state,
        )
        self.gbdt.fit(x_train, y)

        # 5. AFTER training: build full-corpus target encodings for future unseen inference
        self._build_target_encodings(okpd_tuples, y)

        self.is_fitted = True
        self.training_sample_count = n
        self.positive_count = sum(y)
        self.trained_at = datetime.now(timezone.utc).isoformat()
        self.dataset_snapshot_sha256 = dataset_snapshot_sha256
        return self

    def fit_oof_predictions(
        self,
        titles: List[str],
        okpd_codes: List[str],
        prices: List[float],
        y: List[int],
        n_splits: int = 5,
    ) -> np.ndarray:
        """Computes true out-of-fold predictions with strictly cross-fitted target encodings."""
        from sklearn.model_selection import StratifiedKFold
        n = len(y)
        oof = np.zeros(n, dtype=np.float32)
        skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=self.random_state)

        for train_idx, val_idx in skf.split(titles, y):
            train_titles = [titles[i] for i in train_idx]
            val_titles = [titles[i] for i in val_idx]
            train_okpd = [okpd_codes[i] for i in train_idx]
            val_okpd = [okpd_codes[i] for i in val_idx]
            train_prices = [prices[i] for i in train_idx]
            val_prices = [prices[i] for i in val_idx]
            y_train = [y[i] for i in train_idx]

            fold_model = ResearchPriorityModelV2(random_state=self.random_state)
            fold_model.fit(train_titles, train_okpd, train_prices, y_train)
            val_probs = fold_model.predict_proba(val_titles, val_okpd, val_prices)
            for local_i, original_i in enumerate(val_idx):
                oof[original_i] = val_probs[local_i]

        return oof

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
            "training_global_positive_rate": self.training_global_positive_rate,
            "target_encoding_smoothing": self.target_encoding_smoothing,
            "target_encoding_levels": self.target_encoding_levels,
            "okpd_encodings": self.okpd_encodings,
        }
        with open(filepath, "wb") as f:
            pickle.dump({
                "meta": meta,
                "semantic_model": self.semantic_model,
                "gbdt": self.gbdt,
                "okpd_encodings": self.okpd_encodings,
                "training_global_positive_rate": self.training_global_positive_rate,
                "target_encoding_smoothing": self.target_encoding_smoothing,
                "target_encoding_levels": self.target_encoding_levels,
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
        instance.training_global_positive_rate = float(
            meta.get("training_global_positive_rate") or data.get("training_global_positive_rate", 0.23)
        )
        instance.target_encoding_smoothing = float(
            meta.get("target_encoding_smoothing") or data.get("target_encoding_smoothing", 5.0)
        )
        instance.target_encoding_levels = list(
            meta.get("target_encoding_levels") or data.get("target_encoding_levels", ["root", "level2", "level3", "full"])
        )
        instance.is_fitted = True
        instance.training_sample_count = meta.get("training_sample_count", 0)
        instance.positive_count = meta.get("positive_count", 0)
        instance.trained_at = meta.get("trained_at")
        instance.dataset_snapshot_sha256 = meta.get("dataset_snapshot_sha256")
        return instance
