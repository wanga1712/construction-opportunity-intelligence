"""Runner and CLI entrypoint for autonomous shadow market exploration cycles."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Set

from src.market_exploration.dto import ExplorationBudgetDTO, ExplorationPlanDTO
from src.market_exploration.market_profile import build_market_profiles
from src.market_exploration.exploration_selector import select_exploration_plan


def run_market_exploration_cycle(
    procurements: List[Dict[str, Any]],
    researched_procurement_ids: Optional[Set[int]] = None,
    budget: Optional[ExplorationBudgetDTO] = None,
    is_dry_run: bool = True,
) -> ExplorationPlanDTO:
    """Executes full exploration pipeline: profiling -> scoring -> budget-constrained plan."""
    profiles = build_market_profiles(procurements, researched_procurement_ids)
    plan = select_exploration_plan(
        profiles=profiles,
        available_procurements=procurements,
        researched_procurement_ids=researched_procurement_ids,
        budget=budget,
        is_dry_run=is_dry_run,
    )
    return plan


def main() -> None:
    """CLI entrypoint for running shadow exploration planning."""
    parser = argparse.ArgumentParser(description="Market Exploration Shadow Runner")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Execute in dry-run mode (default True)")
    parser.add_argument("--max-clusters", type=int, default=10, help="Max clusters to target")
    parser.add_argument("--max-per-cluster", type=int, default=5, help="Max procurements per cluster")
    parser.add_argument("--max-total", type=int, default=50, help="Max total procurements")
    args = parser.parse_args()

    budget = ExplorationBudgetDTO(
        max_clusters_per_run=args.max_clusters,
        max_procurements_per_cluster=args.max_per_cluster,
        max_total_procurements=args.max_total,
    )

    # In standalone CLI mode with no external db passed, synthesize sample or read stdin
    print(f"=== MARKET EXPLORATION SHADOW RUNNER ===")
    print(f"MODE: DRY_RUN={args.dry_run}")
    print(f"BUDGET: clusters={budget.max_clusters_per_run}, per_cluster={budget.max_procurements_per_cluster}, total={budget.max_total_procurements}")
    print(f"STATUS: Initialized successfully.")


if __name__ == "__main__":
    main()
