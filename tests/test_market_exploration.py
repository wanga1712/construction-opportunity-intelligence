"""Unit and integration tests for Market Exploration subsystem."""

from __future__ import annotations

from src.market_exploration.dto import ExplorationBudgetDTO, MarketClusterProfile
from src.market_exploration.exploration_runner import run_market_exploration_cycle
from src.market_exploration.exploration_scoring import (
    calculate_exploration_score,
    calculate_market_volume_score,
    calculate_novel_child_bonus,
    calculate_uncertainty_score,
)
from src.market_exploration.exploration_selector import select_exploration_plan
from src.market_exploration.market_profile import build_market_profiles


def test_exploration_scoring_components():
    """Verifies that uncertainty, volume, novel bonus, and exploration score calculate correctly."""
    # Uncertainty
    assert calculate_uncertainty_score(100, 0) == 1.0
    assert calculate_uncertainty_score(100, 50) == 0.5
    assert calculate_uncertainty_score(100, 100) == 0.0

    # Volume score (log10 scale)
    assert calculate_market_volume_score(0.0) == 0.0
    assert calculate_market_volume_score(99.0) == 2.0
    assert calculate_market_volume_score(999_999.0) == 6.0

    # Novel child bonus
    assert calculate_novel_child_bonus(0) == 0.0
    assert calculate_novel_child_bonus(3) == 0.6
    assert calculate_novel_child_bonus(10) == 1.0

    # Composite score
    profile = MarketClusterProfile(
        cluster_key="OKPD_LEVEL2:27.4",
        cluster_level="OKPD_LEVEL2",
        procurement_count=20,
        total_market_value=100_000_000.0,
        researched_count=2,
        execution_simplicity_estimate=0.8,
        repeatability_estimate=0.7,
        research_cost_estimate=1.0,
        unseen_child_cluster_count=2,
    )
    score = calculate_exploration_score(profile)
    assert score > 0.0


def test_build_market_profiles_hierarchical():
    """Verifies hierarchical profiling of procurement database across OKPD levels."""
    sample_tenders = [
        {"procurement_id": 1, "okpd_code": "27.40.15.110", "lot_price": 5_000_000.0, "product_category": "lighting_luminaire"},
        {"procurement_id": 2, "okpd_code": "27.40.25.120", "lot_price": 7_000_000.0, "product_category": "lighting_luminaire"},
        {"procurement_id": 3, "okpd_code": "27.90.11.000", "lot_price": 3_000_000.0, "product_category": ""},
        {"procurement_id": 4, "okpd_code": "42.11.20.000", "lot_price": 50_000_000.0, "product_category": "road_construction"},
        {"procurement_id": 5, "okpd_code": "42.11.20.000", "lot_price": 30_000_000.0, "product_category": "road_construction"},
    ]
    researched = {1, 4}

    profiles = build_market_profiles(sample_tenders, researched_procurement_ids=researched)
    assert len(profiles) > 0

    # Verify cluster levels present
    levels = {p.cluster_level for p in profiles}
    assert "OKPD_ROOT" in levels
    assert "OKPD_LEVEL2" in levels
    assert "PRODUCT_CATEGORY" in levels

    # Verify root 27 profiling
    root_27 = next((p for p in profiles if p.cluster_key == "OKPD_ROOT:27"), None)
    assert root_27 is not None
    assert root_27.procurement_count == 3
    assert root_27.total_market_value == 15_000_000.0
    assert root_27.researched_count == 1
    assert root_27.research_coverage == round(1 / 3.0, 4)


def test_select_exploration_plan_budget_compliance():
    """Verifies that selector adheres to cluster and procurement budget limits."""
    sample_tenders = [
        {"procurement_id": i, "okpd_code": f"27.{i % 5}.00.000", "lot_price": float(i * 100_000)}
        for i in range(1, 40)
    ]
    profiles = build_market_profiles(sample_tenders, researched_procurement_ids=set())

    budget = ExplorationBudgetDTO(
        max_clusters_per_run=3,
        max_procurements_per_cluster=2,
        max_total_procurements=5,
    )

    plan = select_exploration_plan(
        profiles=profiles,
        available_procurements=sample_tenders,
        researched_procurement_ids=set(),
        budget=budget,
    )

    assert plan.total_clusters_targeted <= budget.max_clusters_per_run
    assert plan.total_procurements_targeted <= budget.max_total_procurements
    assert len(plan.items) <= budget.max_total_procurements

    # Check that each cluster in items has at most max_procurements_per_cluster items
    from collections import Counter
    cluster_counts = Counter(item.cluster_key for item in plan.items)
    for c_key, count in cluster_counts.items():
        assert count <= budget.max_procurements_per_cluster


def test_run_market_exploration_cycle_dry_run():
    """Verifies end-to-end execution of shadow market exploration runner."""
    sample_tenders = [
        {"procurement_id": 101, "okpd_code": "25.11.23.110", "auction_name": "Поставка металлических опор", "lot_price": 8_000_000.0},
        {"procurement_id": 102, "okpd_code": "27.40.39.110", "auction_name": "Поставка уличных светильников", "lot_price": 6_000_000.0},
    ]
    plan = run_market_exploration_cycle(sample_tenders, is_dry_run=True)
    assert plan.is_dry_run is True
    assert plan.total_procurements_targeted > 0
    assert len(plan.items) > 0
