"""Budget-constrained selection of exploration target clusters and procurements."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
import uuid

from src.learning.okpd_prior.hierarchy import parse_okpd_hierarchy
from src.market_exploration.dto import (
    ExplorationBudgetDTO,
    ExplorationPlanDTO,
    ExplorationPlanItemDTO,
    MarketClusterProfile,
)


def _matches_cluster(procurement: Dict[str, Any], cluster_key: str, cluster_level: str) -> bool:
    """Checks if a procurement matches a given cluster key and level."""
    raw_okpd = str(procurement.get("okpd_code") or procurement.get("okpd_code_raw") or procurement.get("okpd_raw") or "")
    hier = parse_okpd_hierarchy(raw_okpd)
    prod_cat = str(procurement.get("product_category") or "").strip()

    prefix, code = cluster_key.split(":", 1) if ":" in cluster_key else ("", cluster_key)

    if cluster_level == "OKPD_ROOT":
        return hier.okpd_root == code
    elif cluster_level == "OKPD_LEVEL2":
        return hier.okpd_level2 == code
    elif cluster_level == "OKPD_LEVEL3":
        return hier.okpd_level3 == code
    elif cluster_level == "OKPD_FULL":
        return hier.okpd_full == code
    elif cluster_level == "PRODUCT_CATEGORY":
        return prod_cat == code
    return False


def _stratified_sample_matching(
    matching: List[Dict[str, Any]],
    max_k: int,
    p25: float = 0.0,
    p75: float = 0.0,
) -> List[Dict[str, Any]]:
    """Selects stratified sample across price tiers (HIGH, MED, LOW) rather than only top lot price."""
    if len(matching) <= max_k:
        return matching

    # Sort descending by price
    sorted_items = sorted(
        matching,
        key=lambda p: float(p.get("lot_price") or p.get("initial_price") or 0.0),
        reverse=True,
    )

    if max_k == 1:
        return [sorted_items[0]]
    if max_k == 2:
        return [sorted_items[0], sorted_items[-1]]

    # For k >= 3, pick high (top), low (bottom), and evenly spaced middle items
    selected: List[Dict[str, Any]] = []
    selected.append(sorted_items[0])
    selected.append(sorted_items[-1])

    remaining_needed = max_k - 2
    middle_pool = sorted_items[1:-1]
    if middle_pool:
        step = max(1, len(middle_pool) // (remaining_needed + 1))
        for i in range(remaining_needed):
            idx = min(len(middle_pool) - 1, (i + 1) * step)
            selected.append(middle_pool[idx])

    return selected[:max_k]


def select_exploration_plan(
    profiles: List[MarketClusterProfile],
    available_procurements: List[Dict[str, Any]],
    researched_procurement_ids: Optional[Set[int]] = None,
    budget: Optional[ExplorationBudgetDTO] = None,
    is_dry_run: bool = True,
) -> ExplorationPlanDTO:
    """Selects top un-researched procurements across high-value exploration clusters within budget."""
    researched_ids = researched_procurement_ids or set()
    b = budget or ExplorationBudgetDTO()
    plan_id = f"plan_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:6]}"

    # Filter un-researched procurements
    unresearched = [
        p for p in available_procurements
        if int(p.get("procurement_id") or p.get("id") or 0) not in researched_ids
    ]

    # Sort profiles descending by exploration score
    sorted_profiles = sorted(profiles, key=lambda x: x.exploration_score, reverse=True)

    selected_items: List[ExplorationPlanItemDTO] = []
    selected_pids: Set[int] = set()
    targeted_clusters: Set[str] = set()

    cumulative_docs = 0
    cumulative_bytes = 0

    for profile in sorted_profiles:
        if len(targeted_clusters) >= b.max_clusters_per_run:
            break
        if len(selected_items) >= b.max_total_procurements:
            break
        if cumulative_docs >= b.max_document_downloads:
            break
        if cumulative_bytes >= b.max_bytes:
            break

        # Match procurements for this cluster
        matching = [
            p for p in unresearched
            if int(p.get("procurement_id") or p.get("id") or 0) not in selected_pids
            and _matches_cluster(p, profile.cluster_key, profile.cluster_level)
        ]

        if not matching:
            continue

        # Stratified sampling across price distribution
        stratified = _stratified_sample_matching(
            matching=matching,
            max_k=b.max_procurements_per_cluster,
            p25=profile.p25_contract_value,
            p75=profile.p75_contract_value,
        )

        cluster_added_count = 0
        for p in stratified:
            if len(selected_items) >= b.max_total_procurements:
                break
            
            p_docs = int(p.get("document_count") or 1)
            p_bytes = int(p.get("estimated_size_bytes") or (p_docs * 500_000))

            if cumulative_docs + p_docs > b.max_document_downloads and selected_items:
                break
            if cumulative_bytes + p_bytes > b.max_bytes and selected_items:
                break

            pid = int(p.get("procurement_id") or p.get("id") or 0)
            price = float(p.get("lot_price") or p.get("initial_price") or 0.0)
            title = str(p.get("auction_name") or p.get("title") or "")
            okpd = str(p.get("okpd_code") or p.get("okpd_raw") or "")

            item = ExplorationPlanItemDTO(
                plan_id=plan_id,
                cluster_key=profile.cluster_key,
                cluster_level=profile.cluster_level,
                procurement_id=pid,
                title=title,
                okpd_code=okpd,
                lot_price=price,
                exploration_priority=profile.exploration_score,
                reason=(
                    f"Cluster {profile.cluster_key} exploration value={profile.exploration_score:.2f} "
                    f"(coverage={profile.research_coverage*100:.1f}%, volume={profile.market_volume_score:.1f})"
                ),
            )
            selected_items.append(item)
            selected_pids.add(pid)
            cumulative_docs += p_docs
            cumulative_bytes += p_bytes
            cluster_added_count += 1

        if cluster_added_count > 0:
            targeted_clusters.add(profile.cluster_key)

    return ExplorationPlanDTO(
        plan_id=plan_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_clusters_targeted=len(targeted_clusters),
        total_procurements_targeted=len(selected_items),
        items=selected_items,
        budget=b,
        is_dry_run=is_dry_run,
        metadata={
            "total_available_unresearched": len(unresearched),
            "candidate_clusters_evaluated": len(profiles),
            "cumulative_estimated_docs": cumulative_docs,
            "cumulative_estimated_bytes": cumulative_bytes,
        },
    )
