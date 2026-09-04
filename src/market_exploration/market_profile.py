"""Market Cluster Profiling across procurement hierarchy levels."""

from __future__ import annotations

from collections import defaultdict
import statistics
from typing import Any, Dict, List, Optional, Set, Tuple

from src.learning.okpd_prior.hierarchy import parse_okpd_hierarchy
from src.market_exploration.dto import MarketClusterProfile
from src.market_exploration.exploration_scoring import (
    calculate_exploration_score,
    calculate_market_volume_score,
    calculate_uncertainty_score,
)


def _estimate_cluster_simplicity(cluster_key: str, cluster_level: str) -> float:
    """Estimates execution simplicity based on OKPD domain characteristics."""
    if "PRODUCT_CAT:" in cluster_key:
        return 0.85
    code = cluster_key.split(":")[-1].split(".")[0]
    # Manufacturing / goods / lighting / electrical
    if code in ("27", "26", "28", "25", "31"):
        return 0.80
    # Materials / chemistry
    if code in ("20", "22", "23"):
        return 0.75
    # Specialized construction works
    if code == "43":
        return 0.65
    # Heavy civil engineering / infrastructure
    if code in ("41", "42"):
        return 0.50
    return 0.60


def build_market_profiles(
    procurements: List[Dict[str, Any]],
    researched_procurement_ids: Optional[Set[int]] = None,
    levels: Optional[List[str]] = None,
) -> List[MarketClusterProfile]:
    """Aggregates procurements into hierarchical market clusters with exploration metrics."""
    researched_ids = researched_procurement_ids or set()
    target_levels = levels or ["OKPD_ROOT", "OKPD_LEVEL2", "OKPD_LEVEL3", "OKPD_FULL", "PRODUCT_CATEGORY"]

    # Level-grouped buckets: (level, cluster_key) -> list of procurements
    buckets: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    parent_map: Dict[Tuple[str, str], Optional[str]] = {}
    child_map: Dict[Tuple[str, str], Set[str]] = defaultdict(set)

    for p in procurements:
        raw_okpd = str(p.get("okpd_code") or p.get("okpd_raw") or "")
        hier = parse_okpd_hierarchy(raw_okpd)
        prod_cat = str(p.get("product_category") or "").strip()

        # 1. OKPD ROOT
        if hier.okpd_root and hier.okpd_root != "UNKNOWN" and "OKPD_ROOT" in target_levels:
            k_root = f"OKPD_ROOT:{hier.okpd_root}"
            buckets[("OKPD_ROOT", k_root)].append(p)
            parent_map[("OKPD_ROOT", k_root)] = None

        # 2. OKPD LEVEL 2
        if hier.okpd_level2 and hier.okpd_level2 != "UNKNOWN" and "OKPD_LEVEL2" in target_levels:
            k_l2 = f"OKPD_LEVEL2:{hier.okpd_level2}"
            buckets[("OKPD_LEVEL2", k_l2)].append(p)
            p_key = f"OKPD_ROOT:{hier.okpd_root}" if hier.okpd_root else None
            parent_map[("OKPD_LEVEL2", k_l2)] = p_key
            if p_key:
                child_map[("OKPD_ROOT", p_key)].add(k_l2)

        # 3. OKPD LEVEL 3
        if hier.okpd_level3 and hier.okpd_level3 != "UNKNOWN" and "OKPD_LEVEL3" in target_levels:
            k_l3 = f"OKPD_LEVEL3:{hier.okpd_level3}"
            buckets[("OKPD_LEVEL3", k_l3)].append(p)
            p_key = f"OKPD_LEVEL2:{hier.okpd_level2}" if hier.okpd_level2 else None
            parent_map[("OKPD_LEVEL3", k_l3)] = p_key
            if p_key:
                child_map[("OKPD_LEVEL2", p_key)].add(k_l3)

        # 4. OKPD FULL
        if hier.okpd_full and hier.okpd_full != "UNKNOWN" and "OKPD_FULL" in target_levels:
            k_full = f"OKPD_FULL:{hier.okpd_full}"
            buckets[("OKPD_FULL", k_full)].append(p)
            p_key = f"OKPD_LEVEL3:{hier.okpd_level3}" if hier.okpd_level3 else None
            parent_map[("OKPD_FULL", k_full)] = p_key
            if p_key:
                child_map[("OKPD_LEVEL3", p_key)].add(k_full)

        # 5. PRODUCT CATEGORY
        if prod_cat and "PRODUCT_CATEGORY" in target_levels:
            k_cat = f"PRODUCT_CAT:{prod_cat}"
            buckets[("PRODUCT_CATEGORY", k_cat)].append(p)
            parent_map[("PRODUCT_CATEGORY", k_cat)] = None

    profiles: List[MarketClusterProfile] = []

    for (level, cluster_key), items in buckets.items():
        n = len(items)
        prices = [float(p.get("lot_price") or p.get("initial_price") or 0.0) for p in items]
        total_val = sum(prices)
        med_val = statistics.median(prices) if prices else 0.0

        pids = [int(p.get("procurement_id") or p.get("id") or 0) for p in items]
        researched = sum(1 for pid in pids if pid in researched_ids)
        coverage = round(researched / float(n), 4) if n > 0 else 0.0
        uncertainty = calculate_uncertainty_score(n, researched)
        vol_score = calculate_market_volume_score(total_val)

        simplicity = _estimate_cluster_simplicity(cluster_key, level)
        repeatability = round(min(1.0, 0.3 + (n / 50.0)), 4)

        # Child cluster counts
        children = child_map.get((level, cluster_key), set())
        child_count = len(children)
        unseen_children = 0
        for c_key in children:
            # check if any item in child cluster was researched
            # Find level of child
            c_level = "OKPD_LEVEL2" if level == "OKPD_ROOT" else ("OKPD_LEVEL3" if level == "OKPD_LEVEL2" else "OKPD_FULL")
            c_items = buckets.get((c_level, c_key), [])
            c_pids = [int(p.get("procurement_id") or p.get("id") or 0) for p in c_items]
            if not any(pid in researched_ids for pid in c_pids):
                unseen_children += 1

        profile = MarketClusterProfile(
            cluster_key=cluster_key,
            cluster_level=level,
            parent_key=parent_map.get((level, cluster_key)),
            procurement_count=n,
            total_market_value=round(total_val, 2),
            median_contract_value=round(med_val, 2),
            researched_count=researched,
            research_coverage=coverage,
            uncertainty_score=uncertainty,
            market_volume_score=vol_score,
            execution_simplicity_estimate=simplicity,
            repeatability_estimate=repeatability,
            research_cost_estimate=1.0,
            child_cluster_count=child_count,
            unseen_child_cluster_count=unseen_children,
        )
        profile.exploration_score = calculate_exploration_score(profile)
        profiles.append(profile)

    # Sort descending by exploration score
    profiles.sort(key=lambda x: x.exploration_score, reverse=True)
    return profiles
