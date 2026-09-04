"""Title Text Baseline Model V2 for pre-research procurement ranking.

Learns directly from procurement title text (auction_name) using TF-IDF n-grams
and a calibrated linear classifier.
"""

from __future__ import annotations

import json
import math
import os
import pickle
from typing import Any, Dict, List, Optional, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline


TEXT_BASELINE_MODEL_NAME = "TITLE_TEXT_BASELINE_V2"
TEXT_BASELINE_MODEL_TYPE = "TFIDF_LOGISTIC_REGRESSION"


class TitleTextBaselineV2:
    """Pre-research title text ranking baseline."""

    def __init__(self, c_param: float = 1.0, max_features: int = 1500) -> None:
        self.c_param = c_param
        self.max_features = max_features
        self.pipeline: Optional[Pipeline] = None
        self.is_fitted = False
        self.training_sample_count = 0
        self.positive_count = 0

    def fit(self, titles: List[str], y: List[int]) -> "TitleTextBaselineV2":
        """Fits the text classifier on pre-research title strings."""
        if not titles or not y or len(titles) != len(y):
            raise ValueError("Titles and labels must be non-empty and of equal length.")

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

        union = FeatureUnion([
            ("word", word_vec),
            ("char", char_vec),
        ])

        clf = LogisticRegression(
            C=self.c_param,
            class_weight="balanced",
            max_iter=1000,
            random_state=42,
        )

        self.pipeline = Pipeline([
            ("features", union),
            ("clf", clf),
        ])

        self.pipeline.fit(cleaned_titles, y)
        self.is_fitted = True
        self.training_sample_count = len(titles)
        self.positive_count = sum(y)
        return self

    def predict_proba(self, titles: List[str]) -> List[float]:
        """Predicts probability P(RESEARCH_HIT) for a list of titles."""
        if not self.is_fitted or self.pipeline is None:
            raise RuntimeError("Model is not fitted.")

        cleaned_titles = [str(t or "").strip().lower() for t in titles]
        if not cleaned_titles:
            return []

        probs = self.pipeline.predict_proba(cleaned_titles)
        # Class 1 probability
        classes = list(self.pipeline.classes_)
        if 1 in classes:
            idx = classes.index(1)
            return [float(p[idx]) for p in probs]
        return [0.0 for _ in probs]

    def predict_one(self, title: str) -> float:
        """Predicts probability P(RESEARCH_HIT) for a single title."""
        res = self.predict_proba([title])
        return res[0] if res else 0.0

    def save_artifact(self, filepath: str) -> None:
        """Saves fitted model to binary artifact."""
        if not self.is_fitted or self.pipeline is None:
            raise RuntimeError("Cannot save unfitted model.")
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        meta = {
            "model_name": TEXT_BASELINE_MODEL_NAME,
            "model_type": TEXT_BASELINE_MODEL_TYPE,
            "c_param": self.c_param,
            "max_features": self.max_features,
            "training_sample_count": self.training_sample_count,
            "positive_count": self.positive_count,
        }
        with open(filepath, "wb") as f:
            pickle.dump({"meta": meta, "pipeline": self.pipeline}, f)

    @classmethod
    def load_artifact(cls, filepath: str) -> "TitleTextBaselineV2":
        """Loads fitted model from artifact."""
        with open(filepath, "rb") as f:
            data = pickle.load(f)
        meta = data.get("meta", {})
        instance = cls(
            c_param=meta.get("c_param", 1.0),
            max_features=meta.get("max_features", 1500),
        )
        instance.pipeline = data.get("pipeline")
        instance.is_fitted = True
        instance.training_sample_count = meta.get("training_sample_count", 0)
        instance.positive_count = meta.get("positive_count", 0)
        return instance
