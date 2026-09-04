"""Deterministic empirical hierarchical Bayesian prior baseline.

Implements BASELINE_MODEL = 'OKPD_HIERARCHICAL_PRIOR_V1'.
Uses m-estimate smoothing and strict hierarchical fallback:
full code -> level3 -> level2 -> root -> global prior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.learning.okpd_prior.dataset import ProcurementDatasetRow
from src.learning.okpd_prior.hierarchy import OKPDHierarchy, UNKNOWN_OKPD, parse_okpd_hierarchy

BASELINE_MODEL_NAME = "OKPD_HIERARCHICAL_PRIOR_V1"
DEFAULT_SMOOTHING_WEIGHT = 5.0
DEFAULT_MIN_SUPPORT = 3


@dataclass(frozen=True)
class PriorNodeStats:
    """Statistics for an OKPD hierarchy node."""
    prefix: str
    level: str
    total: int
    positive: int
    negative: int
    raw_hit_rate: float
    smoothed_hit_rate: float


@dataclass(frozen=True)
class BaselinePrediction:
    """Result of baseline prior prediction for a single procurement."""
    p_research_hit: float
    fallback_level: str
    matched_prefix: str
    support_count: int
    raw_hit_rate: float
    smoothed_hit_rate: float


class OKPDHierarchicalPriorV1:
    """Hierarchical empirical Bayesian prior model with shrinkage and fallback."""

    def __init__(
        self,
        smoothing_weight: float = DEFAULT_SMOOTHING_WEIGHT,
        min_support: int = DEFAULT_MIN_SUPPORT,
    ) -> None:
        self.smoothing_weight = smoothing_weight
        self.min_support = min_support
        self.global_total = 0
        self.global_positive = 0
        self.global_prior = 0.0
        self.nodes: Dict[str, PriorNodeStats] = {}
        self.is_fitted = False

    def fit(self, rows: List[ProcurementDatasetRow]) -> "OKPDHierarchicalPriorV1":
        """Fits the hierarchical prior table on training rows."""
        usable = [r for r in rows if r.research_hit is not None]
        self.global_total = len(usable)
        self.global_positive = sum(1 for r in usable if r.research_hit == 1)
        self.global_prior = (
            (self.global_positive / self.global_total) if self.global_total > 0 else 0.05
        )

        counts: Dict[str, Dict[str, Any]] = {}

        def _record(prefix: str, level: str, hit: int) -> None:
            if prefix not in counts:
                counts[prefix] = {
                    "prefix": prefix,
                    "level": level,
                    "total": 0,
                    "positive": 0,
                }
            counts[prefix]["total"] += 1
            if hit == 1:
                counts[prefix]["positive"] += 1

        for r in usable:
            hit = r.research_hit or 0
            if r.okpd_root != UNKNOWN_OKPD:
                _record(r.okpd_root, "root", hit)
                _record(r.okpd_level2, "level2", hit)
                _record(r.okpd_level3, "level3", hit)
                _record(r.okpd_full, "full", hit)

        self.nodes = {}
        m = self.smoothing_weight

        # 1. Roots (parent = global)
        for prefix, c in counts.items():
            if c["level"] == "root":
                tot = c["total"]
                pos = c["positive"]
                raw = (pos / tot) if tot > 0 else 0.0
                smoothed = (pos + m * self.global_prior) / (tot + m)
                self.nodes[prefix] = PriorNodeStats(
                    prefix=prefix,
                    level="root",
                    total=tot,
                    positive=pos,
                    negative=tot - pos,
                    raw_hit_rate=round(raw, 4),
                    smoothed_hit_rate=round(smoothed, 4),
                )

        # 2. Level 2 (parent = root)
        for prefix, c in counts.items():
            if c["level"] == "level2":
                tot = c["total"]
                pos = c["positive"]
                root_prefix = prefix.split(".")[0]
                parent_prior = (
                    self.nodes[root_prefix].smoothed_hit_rate
                    if root_prefix in self.nodes
                    else self.global_prior
                )
                raw = (pos / tot) if tot > 0 else 0.0
                smoothed = (pos + m * parent_prior) / (tot + m)
                self.nodes[prefix] = PriorNodeStats(
                    prefix=prefix,
                    level="level2",
                    total=tot,
                    positive=pos,
                    negative=tot - pos,
                    raw_hit_rate=round(raw, 4),
                    smoothed_hit_rate=round(smoothed, 4),
                )

        # 3. Level 3 (parent = level2)
        for prefix, c in counts.items():
            if c["level"] == "level3":
                tot = c["total"]
                pos = c["positive"]
                parts = prefix.split(".")
                l2_prefix = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else parts[0]
                parent_prior = (
                    self.nodes[l2_prefix].smoothed_hit_rate
                    if l2_prefix in self.nodes
                    else self.global_prior
                )
                raw = (pos / tot) if tot > 0 else 0.0
                smoothed = (pos + m * parent_prior) / (tot + m)
                self.nodes[prefix] = PriorNodeStats(
                    prefix=prefix,
                    level="level3",
                    total=tot,
                    positive=pos,
                    negative=tot - pos,
                    raw_hit_rate=round(raw, 4),
                    smoothed_hit_rate=round(smoothed, 4),
                )

        # 4. Full (parent = level3)
        for prefix, c in counts.items():
            if c["level"] == "full":
                tot = c["total"]
                pos = c["positive"]
                parts = prefix.split(".")
                l3_prefix = f"{parts[0]}.{parts[1]}.{parts[2]}" if len(parts) >= 3 else prefix
                parent_prior = (
                    self.nodes[l3_prefix].smoothed_hit_rate
                    if l3_prefix in self.nodes
                    else self.global_prior
                )
                raw = (pos / tot) if tot > 0 else 0.0
                smoothed = (pos + m * parent_prior) / (tot + m)
                self.nodes[prefix] = PriorNodeStats(
                    prefix=prefix,
                    level="full",
                    total=tot,
                    positive=pos,
                    negative=tot - pos,
                    raw_hit_rate=round(raw, 4),
                    smoothed_hit_rate=round(smoothed, 4),
                )

        self.is_fitted = True
        return self

    def predict(self, hierarchy: OKPDHierarchy) -> BaselinePrediction:
        """Predicts research hit probability with hierarchical fallback."""
        if not self.is_fitted:
            return BaselinePrediction(
                p_research_hit=0.05,
                fallback_level="unfitted",
                matched_prefix="NONE",
                support_count=0,
                raw_hit_rate=0.0,
                smoothed_hit_rate=0.05,
            )

        # Check full
        if hierarchy.okpd_full in self.nodes:
            n = self.nodes[hierarchy.okpd_full]
            if n.total >= self.min_support:
                return BaselinePrediction(
                    p_research_hit=n.smoothed_hit_rate,
                    fallback_level="full",
                    matched_prefix=n.prefix,
                    support_count=n.total,
                    raw_hit_rate=n.raw_hit_rate,
                    smoothed_hit_rate=n.smoothed_hit_rate,
                )

        # Check level3
        if hierarchy.okpd_level3 in self.nodes:
            n = self.nodes[hierarchy.okpd_level3]
            if n.total >= self.min_support:
                return BaselinePrediction(
                    p_research_hit=n.smoothed_hit_rate,
                    fallback_level="level3",
                    matched_prefix=n.prefix,
                    support_count=n.total,
                    raw_hit_rate=n.raw_hit_rate,
                    smoothed_hit_rate=n.smoothed_hit_rate,
                )

        # Check level2
        if hierarchy.okpd_level2 in self.nodes:
            n = self.nodes[hierarchy.okpd_level2]
            if n.total >= self.min_support:
                return BaselinePrediction(
                    p_research_hit=n.smoothed_hit_rate,
                    fallback_level="level2",
                    matched_prefix=n.prefix,
                    support_count=n.total,
                    raw_hit_rate=n.raw_hit_rate,
                    smoothed_hit_rate=n.smoothed_hit_rate,
                )

        # Check root
        if hierarchy.okpd_root in self.nodes:
            n = self.nodes[hierarchy.okpd_root]
            if n.total >= self.min_support:
                return BaselinePrediction(
                    p_research_hit=n.smoothed_hit_rate,
                    fallback_level="root",
                    matched_prefix=n.prefix,
                    support_count=n.total,
                    raw_hit_rate=n.raw_hit_rate,
                    smoothed_hit_rate=n.smoothed_hit_rate,
                )

        # Fallback to global
        raw_g = (
            (self.global_positive / self.global_total)
            if self.global_total > 0
            else 0.0
        )
        return BaselinePrediction(
            p_research_hit=round(self.global_prior, 4),
            fallback_level="global",
            matched_prefix="GLOBAL",
            support_count=self.global_total,
            raw_hit_rate=round(raw_g, 4),
            smoothed_hit_rate=round(self.global_prior, 4),
        )

    def get_root_summary_table(self) -> List[Dict[str, Any]]:
        """Returns sorted table of all root statistics for diagnostics and UI."""
        roots = [n for n in self.nodes.values() if n.level == "root"]
        roots.sort(key=lambda x: (x.total, x.positive), reverse=True)
        return [asdict(r) for r in roots]
