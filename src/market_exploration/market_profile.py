"""Market Cluster Profiling across procurement hierarchy levels."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math
import statistics
from typing import Any, Dict, List, Optional, Set, Tuple

from src.learning.okpd_prior.hierarchy import parse_okpd_hierarchy
from src.market_exploration.dto import MarketClusterProfile
from src.market_exploration.exploration_scoring import (
    calculate_exploration_score,
    calculate_market_volume_score,
    calculate_uncertainty_score,
)


def _parse_procurement_date(procurement: Dict[str, Any]) -> Optional[datetime]:
    """Extracts and parses publication or notification timestamp."""
    for key in ("publish_date", "created_at", "notification_date", "submission_start_date", "date"):
        val = procurement.get(key)
        if val:
            if isinstance(val, datetime):
                return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
            if isinstance(val, str):
                try:
                    dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                except Exception:
                    pass
    return None


def filter_by_rolling_window(
    procurements: List[Dict[str, Any]],
    window_days: Optional[int] = 365,
) -> List[Dict[str, Any]]:
    """Filters procurements to rolling time window relative to latest available date."""
    if window_days is None:
        return procurements

    dated_items: List[Tuple[Optional[datetime], Dict[str, Any]]] = [
        (_parse_procurement_date(p), p) for p in procurements
    ]
    valid_dates = [dt for dt, _ in dated_items if dt is not None]
    if not valid_dates:
        return procurements

    max_dt = max(valid_dates)
    filtered = []
    for dt, p in dated_items:
        if dt is None or (max_dt - dt).total_seconds() <= window_days * 86400:
            filtered.append(p)
    return filtered


def _estimate_cluster_simplicity(cluster_key: str, cluster_level: str, items: List[Dict[str, Any]]) -> float:
    """Estimates execution simplicity blending OKPD domain code and text signals."""
    if "PRODUCT_CAT:" in cluster_key:
        return 0.85

    code = cluster_key.split(":")[-1].split(".")[0]
    base_simplicity = 0.60
    if code in ("27", "26", "28", "25", "31"):
        base_simplicity = 0.80
    elif code in ("20", "22", "23"):
        base_simplicity = 0.75
    elif code == "43":
        base_simplicity = 0.65
    elif code in ("41", "42"):
        base_simplicity = 0.50

    # Adjust with title text signals if available
    goods_keywords = {"поставка", "приобретение", "закупка", "оборудование", "материал"}
    works_keywords = {"строительство", "реконструкция", "капитальный", "монтаж", "ремонт"}

    goods_count = 0
    works_count = 0
    for p in items:
        title = str(p.get("auction_name") or p.get("title") or "").lower()
        if any(k in title for k in goods_keywords):
            goods_count += 1
        if any(k in title for k in works_keywords):
            works_count += 1

    total_text = goods_count + works_count
    if total_text > 0:
        text_adjustment = (goods_count - works_count) / float(total_text) * 0.10
        return round(max(0.1, min(0.95, base_simplicity + text_adjustment)), 4)

    return base_simplicity


def _calculate_percentiles(values: List[float]) -> Tuple[float, float, float]:
    """Calculates p25, median (p50), and p75 robustly."""
    if not values:
        return 0.0, 0.0, 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    med = statistics.median(sorted_vals)
    if n < 4:
        return sorted_vals[0], med, sorted_vals[-1]
    
    # quantiles gives 3 cut points for 4 intervals: [q25, q50, q75]
    quants = statistics.quantiles(sorted_vals, n=4)
    return quants[0], quants[1], quants[2]


def build_market_profiles(
    procurements: List[Dict[str, Any]],
    researched_procurement_ids: Optional[Set[int]] = None,
    researched_outcomes: Optional[Dict[int, str]] = None,
    levels: Optional[List[str]] = None,
    window_days: Optional[int] = 365,
) -> List[MarketClusterProfile]:
    """Aggregates procurements into hierarchical market clusters with rich exploration metrics."""
    researched_ids = researched_procurement_ids or set()
    outcomes = researched_outcomes or {}
    target_levels = levels or ["OKPD_ROOT", "OKPD_LEVEL2", "OKPD_LEVEL3", "OKPD_FULL", "PRODUCT_CATEGORY"]

    window_filtered = filter_by_rolling_window(procurements, window_days=window_days)

    # Level-grouped buckets: (level, cluster_key) -> list of procurements
    buckets: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    parent_map: Dict[Tuple[str, str], Optional[str]] = {}
    child_map: Dict[Tuple[str, str], Set[str]] = defaultdict(set)

    for p in window_filtered:
        raw_okpd = str(p.get("okpd_code") or p.get("okpd_code_raw") or p.get("okpd_raw") or "")
        hier = parse_okpd_hierarchy(raw_okpd)
        prod_cat = str(p.get("product_category") or "").strip()

        if hier.okpd_root and hier.okpd_root != "UNKNOWN" and "OKPD_ROOT" in target_levels:
            k_root = f"OKPD_ROOT:{hier.okpd_root}"
            buckets[("OKPD_ROOT", k_root)].append(p)
            parent_map[("OKPD_ROOT", k_root)] = None

        if hier.okpd_level2 and hier.okpd_level2 != "UNKNOWN" and "OKPD_LEVEL2" in target_levels:
            k_l2 = f"OKPD_LEVEL2:{hier.okpd_level2}"
            buckets[("OKPD_LEVEL2", k_l2)].append(p)
            p_key = f"OKPD_ROOT:{hier.okpd_root}" if hier.okpd_root else None
            parent_map[("OKPD_LEVEL2", k_l2)] = p_key
            if p_key:
                child_map[("OKPD_ROOT", p_key)].add(k_l2)

        if hier.okpd_level3 and hier.okpd_level3 != "UNKNOWN" and "OKPD_LEVEL3" in target_levels:
            k_l3 = f"OKPD_LEVEL3:{hier.okpd_level3}"
            buckets[("OKPD_LEVEL3", k_l3)].append(p)
            p_key = f"OKPD_LEVEL2:{hier.okpd_level2}" if hier.okpd_level2 else None
            parent_map[("OKPD_LEVEL3", k_l3)] = p_key
            if p_key:
                child_map[("OKPD_LEVEL2", p_key)].add(k_l3)

        if hier.okpd_full and hier.okpd_full != "UNKNOWN" and "OKPD_FULL" in target_levels:
            k_full = f"OKPD_FULL:{hier.okpd_full}"
            buckets[("OKPD_FULL", k_full)].append(p)
            p_key = f"OKPD_LEVEL3:{hier.okpd_level3}" if hier.okpd_level3 else None
            parent_map[("OKPD_FULL", k_full)] = p_key
            if p_key:
                child_map[("OKPD_LEVEL3", p_key)].add(k_full)

        if prod_cat and "PRODUCT_CATEGORY" in target_levels:
            k_cat = f"PRODUCT_CAT:{prod_cat}"
            buckets[("PRODUCT_CATEGORY", k_cat)].append(p)
            parent_map[("PRODUCT_CATEGORY", k_cat)] = None

    profiles: List[MarketClusterProfile] = []

    for (level, cluster_key), items in buckets.items():
        n = len(items)
        prices = [float(p.get("lot_price") or p.get("initial_price") or 0.0) for p in items]
        total_val = sum(prices)
        p25_val, med_val, p75_val = _calculate_percentiles(prices)

        pids = [int(p.get("procurement_id") or p.get("id") or 0) for p in items]
        researched = sum(1 for pid in pids if pid in researched_ids)
        coverage = round(researched / float(n), 4) if n > 0 else 0.0

        pos_count = 0
        neg_count = 0
        unres_count = 0
        for pid in pids:
            if pid in researched_ids:
                out = outcomes.get(pid, "").upper()
                if out in ("POSITIVE", "HIT", "1"):
                    pos_count += 1
                elif out in ("SAFE_NEGATIVE", "NEGATIVE", "0"):
                    neg_count += 1
                else:
                    unres_count += 1

        customers = {str(p.get("customer_inn") or p.get("customer_name") or p.get("customer") or "") for p in items}
        customers.discard("")
        regions = {str(p.get("region") or p.get("delivery_region") or p.get("customer_region") or "") for p in items}
        regions.discard("")

        uncertainty = calculate_uncertainty_score(n, researched)
        vol_score = calculate_market_volume_score(total_val)
        simplicity = _estimate_cluster_simplicity(cluster_key, level, items)
        repeatability = round(min(1.0, 0.3 + (n / 50.0)), 4)

        # Average research cost estimation
        doc_counts = [float(p.get("document_count") or 1.0) for p in items]
        avg_docs = statistics.mean(doc_counts) if doc_counts else 1.0
        cost_est = round(min(5.0, max(0.5, 0.5 + (avg_docs * 0.2))), 2)

        # Child cluster counts
        children = child_map.get((level, cluster_key), set())
        child_count = len(children)
        unseen_children = 0
        for c_key in children:
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
            p25_contract_value=round(p25_val, 2),
            p75_contract_value=round(p75_val, 2),
            researched_count=researched,
            positive_count=pos_count,
            safe_negative_count=neg_count,
            unresolved_count=unres_count,
            research_coverage=coverage,
            distinct_customers=len(customers),
            distinct_regions=len(regions),
            uncertainty_score=uncertainty,
            market_volume_score=vol_score,
            execution_simplicity_estimate=simplicity,
            repeatability_estimate=repeatability,
            research_cost_estimate=cost_est,
            child_cluster_count=child_count,
            unseen_child_cluster_count=unseen_children,
        )
        profile.exploration_score = calculate_exploration_score(profile)
        profiles.append(profile)

    profiles.sort(key=lambda x: x.exploration_score, reverse=True)
    return profiles
