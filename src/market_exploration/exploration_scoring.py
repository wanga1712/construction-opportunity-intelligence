"""Scoring algorithms for market cluster exploration value."""

from __future__ import annotations

import math
from typing import Optional

from src.market_exploration.dto import MarketClusterProfile


def calculate_uncertainty_score(procurement_count: int, researched_count: int) -> float:
    """Calculates cluster uncertainty in [0.0, 1.0] based on research coverage."""
    if procurement_count <= 0:
        return 1.0
    coverage = min(1.0, max(0.0, researched_count / float(procurement_count)))
    return round(1.0 - coverage, 4)


def calculate_market_volume_score(total_market_value: float) -> float:
    """Calculates log10-scaled market volume score."""
    val = max(0.0, float(total_market_value))
    return round(math.log10(val + 1.0), 4)


def calculate_novel_child_bonus(unseen_child_count: int) -> float:
    """Calculates bonus score for exploring clusters with undiscovered subcategories."""
    count = max(0, int(unseen_child_count))
    return round(min(1.0, 0.2 * count), 4)


def calculate_exploration_score(profile: MarketClusterProfile) -> float:
    """Calculates bounded composite exploration value score for a market cluster.

    Formula:
        Value = (log10(Volume + 1) * Uncertainty * Simplicity * Repeatability) / Cost + NovelBonus
    """
    vol_score = calculate_market_volume_score(profile.total_market_value)
    uncertainty = calculate_uncertainty_score(profile.procurement_count, profile.researched_count)
    simplicity = max(0.05, min(1.0, profile.execution_simplicity_estimate))
    repeatability = max(0.05, min(1.0, profile.repeatability_estimate))
    cost = max(0.1, profile.research_cost_estimate)
    novel_bonus = calculate_novel_child_bonus(profile.unseen_child_cluster_count)

    core_val = (vol_score * uncertainty * simplicity * repeatability) / cost
    total_score = max(0.0, core_val + novel_bonus)
    return round(total_score, 4)
