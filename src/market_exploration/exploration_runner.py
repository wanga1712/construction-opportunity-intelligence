"""Runner and CLI entrypoint for autonomous shadow market exploration cycles."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import sys
from typing import Any, Dict, List, Optional, Set

from src.market_exploration.data_source import (
    InMemoryMarketExplorationDataSource,
    MarketExplorationDataSourceProtocol,
    PostgresMarketExplorationDataSource,
)
from src.market_exploration.dto import (
    ExplorationBudgetDTO,
    ExplorationPlanDTO,
    generate_exploration_run_key,
)
from src.market_exploration.exploration_selector import select_exploration_plan
from src.market_exploration.market_profile import build_market_profiles


def run_market_exploration_cycle(
    procurements: List[Dict[str, Any]],
    researched_procurement_ids: Optional[Set[int]] = None,
    researched_outcomes: Optional[Dict[int, str]] = None,
    budget: Optional[ExplorationBudgetDTO] = None,
    window_days: Optional[int] = 365,
    is_dry_run: bool = True,
) -> ExplorationPlanDTO:
    """Executes full exploration pipeline: profiling -> scoring -> budget-constrained plan."""
    profiles = build_market_profiles(
        procurements=procurements,
        researched_procurement_ids=researched_procurement_ids,
        researched_outcomes=researched_outcomes,
        window_days=window_days,
    )
    plan = select_exploration_plan(
        profiles=profiles,
        available_procurements=procurements,
        researched_procurement_ids=researched_procurement_ids,
        budget=budget,
        is_dry_run=is_dry_run,
    )
    return plan


def execute_exploration_from_data_source(
    data_source: MarketExplorationDataSourceProtocol,
    budget: Optional[ExplorationBudgetDTO] = None,
    window_days: Optional[int] = 365,
    is_dry_run: bool = True,
) -> ExplorationPlanDTO:
    """Runs exploration cycle directly against a configured data source."""
    procs = data_source.get_active_procurements(limit=5000)
    researched_ids = data_source.get_researched_procurement_ids()
    outcomes = data_source.get_researched_outcomes()

    plan = run_market_exploration_cycle(
        procurements=procs,
        researched_procurement_ids=researched_ids,
        researched_outcomes=outcomes,
        budget=budget,
        window_days=window_days,
        is_dry_run=is_dry_run,
    )
    return plan


def main() -> None:
    """CLI entrypoint for running shadow exploration planning."""
    parser = argparse.ArgumentParser(description="Market Exploration Shadow Runner")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Execute in dry-run mode (default True)")
    parser.add_argument("--window-days", type=int, default=365, help="Rolling window in days (default 365)")
    parser.add_argument("--max-clusters", type=int, default=10, help="Max clusters to target")
    parser.add_argument("--max-per-cluster", type=int, default=5, help="Max procurements per cluster")
    parser.add_argument("--max-total", type=int, default=50, help="Max total procurements")
    parser.add_argument("--source", type=str, default="memory", choices=["memory", "postgres", "production-readonly"], help="Data source type")
    args = parser.parse_args()

    budget = ExplorationBudgetDTO(
        max_clusters_per_run=args.max_clusters,
        max_procurements_per_cluster=args.max_per_cluster,
        max_total_procurements=args.max_total,
    )

    run_key = generate_exploration_run_key(
        run_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        policy_version="v1",
        source_snapshot_id=args.source,
    )

    print("=== MARKET EXPLORATION SHADOW RUNNER ===")
    print(f"RUN_KEY: {run_key}")
    print(f"MODE: DRY_RUN={args.dry_run}")
    print(f"SOURCE: {args.source}, WINDOW_DAYS: {args.window_days}")
    print(f"BUDGET: clusters={budget.max_clusters_per_run}, per_cluster={budget.max_procurements_per_cluster}, total={budget.max_total_procurements}")

    if args.source == "memory":
        ds = InMemoryMarketExplorationDataSource([])
    else:
        ds = PostgresMarketExplorationDataSource()

    plan = execute_exploration_from_data_source(ds, budget=budget, window_days=args.window_days, is_dry_run=args.dry_run)
    print(f"PLAN_ID: {plan.plan_id}")
    print(f"TARGETED_CLUSTERS: {plan.total_clusters_targeted}")
    print(f"TARGETED_PROCUREMENTS: {plan.total_procurements_targeted}")
    print("STATUS: Completed successfully.")


if __name__ == "__main__":
    main()
