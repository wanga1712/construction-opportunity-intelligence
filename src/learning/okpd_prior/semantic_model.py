"""Title Semantic Model V2 with domain disambiguation and OOF stacking support.

Computes continuous semantic relevance probability P(SEMANTIC_HIT) using
domain-aware feature representation and text vectorization.
"""

from __future__ import annotations

import json
import os
import pickle
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import FeatureUnion
from scipy.sparse import hstack, csr_matrix

from src.learning.okpd_prior.disambiguation import extract_domain_signals


SEMANTIC_MODEL_NAME = "TITLE_SEMANTIC_V2"
SEMANTIC_MODEL_TYPE = "DOMAIN_DISAMBIGUATED_SEMANTIC_REGRESSION"


class TitleSemanticModelV2:
    """Pre-research semantic model combining lexical features with domain signals."""

    def __init__(self, c_param: float = 1.0, max_features: int = 1000) -> None:
        self.c_param = c_param
        self.max_features = max_features
        self.vectorizer: Optional[FeatureUnion] = None
        self.classifier: Optional[LogisticRegression] = None
        self.is_fitted = False
        self.training_sample_count = 0
        self.positive_count = 0

    def _extract_dense_domain_matrix(self, titles: List[str], okpds: List[str]) -> np.ndarray:
        """Extracts dense matrix of domain prior signals."""
        rows = []
        for t, ok in zip(titles, okpds):
            sig = extract_domain_signals(t, ok)
            rows.append([
                sig["construction_prior"],
                sig["medical_risk"],
                sig["it_electronics_risk"],
                sig["furniture_risk"],
                sig["food_risk"],
                sig["works_signal"],
                sig["disambiguated_injection_score"],
            ])
        return np.array(rows, dtype=np.float32)

    def fit(self, titles: List[str], okpds: List[str], y: List[int]) -> "TitleSemanticModelV2":
        """Fits semantic model on text and OKPD codes."""
        if not titles or not y or len(titles) != len(y):
            raise ValueError("Titles, OKPDs and labels must be of equal non-zero length.")
        if len(okpds) != len(titles):
            okpds = ["" for _ in titles]

        cleaned_titles = [str(t or "").strip().lower() for t in titles]

        word_vec = TfidfVectorizer(
            ngram_range=(1, 2),
            max_features=self.max_features // 2,
            sublinear_tf=True,
            token_pattern=r"(?u)\b\w+\b",
        )
        char_vec = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            max_features=self.max_features // 2,
            sublinear_tf=True,
        )

        self.vectorizer = FeatureUnion([
            ("word", word_vec),
            ("char", char_vec),
        ])

        text_feat = self.vectorizer.fit_transform(cleaned_titles)
        domain_feat = csr_matrix(self._extract_dense_domain_matrix(titles, okpds))

        x_combined = hstack([text_feat, domain_feat])

        self.classifier = LogisticRegression(
            C=self.c_param,
            class_weight="balanced",
            max_iter=1000,
            random_state=42,
        )
        self.classifier.fit(x_combined, y)

        self.is_fitted = True
        self.training_sample_count = len(titles)
        self.positive_count = sum(y)
        return self

    def fit_oof_predictions(
        self, titles: List[str], okpds: List[str], y: List[int], n_splits: int = 5
    ) -> np.ndarray:
        """Generates out-of-fold predictions to prevent leakage when stacking."""
        if len(titles) != len(y):
            raise ValueError("Titles and labels length mismatch.")
        if len(okpds) != len(titles):
            okpds = ["" for _ in titles]

        cleaned_titles = [str(t or "").strip().lower() for t in titles]
        y_arr = np.array(y)
        oof_preds = np.zeros(len(titles), dtype=np.float32)

        pos_cnt = int(sum(y))
        neg_cnt = len(y) - pos_cnt
        min_class = min(pos_cnt, neg_cnt)
        actual_splits = min(n_splits, min_class)

        if actual_splits >= 2:
            skf = StratifiedKFold(n_splits=actual_splits, shuffle=True, random_state=42)
            for train_idx, val_idx in skf.split(cleaned_titles, y_arr):
                train_t = [cleaned_titles[i] for i in train_idx]
                train_ok = [okpds[i] for i in train_idx]
                train_y = y_arr[train_idx]

                val_t = [cleaned_titles[i] for i in val_idx]
                val_ok = [okpds[i] for i in val_idx]

                fold_model = TitleSemanticModelV2(
                    c_param=self.c_param,
                    max_features=self.max_features,
                )
                fold_model.fit(train_t, train_ok, list(train_y))
                val_probs = fold_model.predict_proba(val_t, val_ok)
                oof_preds[val_idx] = val_probs
        else:
            self.fit(titles, okpds, y)
            return np.array(self.predict_proba(titles, okpds), dtype=np.float32)

        # Fit final model on full dataset
        self.fit(titles, okpds, y)
        return oof_preds

    def predict_proba(self, titles: List[str], okpds: Optional[List[str]] = None) -> List[float]:
        """Predicts probability P(SEMANTIC_HIT) for input titles and okpds."""
        if not self.is_fitted or self.vectorizer is None or self.classifier is None:
            raise RuntimeError("Model is not fitted.")

        if not titles:
            return []
        if okpds is None or len(okpds) != len(titles):
            okpds = ["" for _ in titles]

        cleaned_titles = [str(t or "").strip().lower() for t in titles]
        text_feat = self.vectorizer.transform(cleaned_titles)
        domain_feat = csr_matrix(self._extract_dense_domain_matrix(titles, okpds))
        x_combined = hstack([text_feat, domain_feat])

        probs = self.classifier.predict_proba(x_combined)
        classes = list(self.classifier.classes_)
        if 1 in classes:
            idx = classes.index(1)
            return [float(p[idx]) for p in probs]
        return [0.0 for _ in probs]

    def predict_one(self, title: str, okpd: str = "") -> float:
        """Predicts probability P(SEMANTIC_HIT) for a single item."""
        res = self.predict_proba([title], [okpd])
        return res[0] if res else 0.0

    def save_artifact(self, filepath: str) -> None:
        """Saves fitted model to binary artifact."""
        if not self.is_fitted:
            raise RuntimeError("Cannot save unfitted model.")
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        meta = {
            "model_name": SEMANTIC_MODEL_NAME,
            "model_type": SEMANTIC_MODEL_TYPE,
            "c_param": self.c_param,
            "max_features": self.max_features,
            "training_sample_count": self.training_sample_count,
            "positive_count": self.positive_count,
        }
        with open(filepath, "wb") as f:
            pickle.dump({
                "meta": meta,
                "vectorizer": self.vectorizer,
                "classifier": self.classifier,
            }, f)

    @classmethod
    def load_artifact(cls, filepath: str) -> "TitleSemanticModelV2":
        """Loads fitted model from artifact."""
        with open(filepath, "rb") as f:
            data = pickle.load(f)
        meta = data.get("meta", {})
        instance = cls(
            c_param=meta.get("c_param", 1.0),
            max_features=meta.get("max_features", 1000),
        )
        instance.vectorizer = data.get("vectorizer")
        instance.classifier = data.get("classifier")
        instance.is_fitted = True
        instance.training_sample_count = meta.get("training_sample_count", 0)
        instance.positive_count = meta.get("positive_count", 0)
        return instance
