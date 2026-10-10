#!/usr/bin/env python3
"""Read-only Phase 3.1 Medal V1 recalibration.

DIRECT:
  cohort percentile-like value scale:
  P10=10, P25=25, P50=50, P75=75, P90=90, upper tail=100
  + canonical direct_value_floor.py hard cap

EMBEDDED:
  RESEARCH_PRIORITY_SIM = evidence + object cohort + timing + actionability
  VALUE=UNKNOWN, quantity=UNKNOWN
  provisional medal hard-capped at SILVER

No production writes.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import simulate_medal_v1_phase3 as base  # noqa: E402
from src.services.commercial_routing_v3.direct_value_floor import (  # noqa: E402
    direct_value_cap,
)

load_dotenv(ROOT / ".env")

MIN_N = 20
SILVER_RANK = 3
STRING_MEDAL_RANK = {"GOLD": 4, "SILVER": 3, "BRONZE": 2, "WOOD": 1}


def direct_percentile_score(
    value: float,
    p10: Optional[float],
    p25: Optional[float],
    p50: Optional[float],
    p75: Optional[float],
    p90: Optional[float],
) -> Optional[float]:
    points = [(p10, 10.0), (p25, 25.0), (p50, 50.0), (p75, 75.0), (p90, 90.0)]
    if any(p is None for p, _ in points):
        return None
    if value <= p10:
        return 10.0
    if value >= p90:
        return 100.0
    for (lo, lo_score), (hi, hi_score) in zip(points, points[1:]):
        if lo <= value <= hi:
            if hi == lo:
                return hi_score
            return lo_score + (value - lo) * (hi_score - lo_score) / (hi - lo)
    return 100.0


def direct_cohort_stats(
    row: Dict[str, Any], cohorts: Dict[str, Dict[Tuple, List[float]]]
) -> Tuple[str, Tuple, Dict[str, Optional[float]], int]:
    levels = base.okpd_levels(row.get("okpd_code"))
    category = row["category"]
    for level in ("okpd4", "okpd3", "okpd2"):
        code = levels[level]
        vals = cohorts[level].get((category, code)) or []
        if code and len(vals) >= MIN_N:
            return level, (category, code), {
                "p10": base.percentile(vals, 0.10),
                "p25": base.percentile(vals, 0.25),
                "p50": base.percentile(vals, 0.50),
                "p75": base.percentile(vals, 0.75),
                "p90": base.percentile(vals, 0.90),
            }, len(vals)
    vals = cohorts["category"].get((category,)) or []
    if len(vals) >= MIN_N:
        return "category", (category,), {
            "p10": base.percentile(vals, 0.10),
            "p25": base.percentile(vals, 0.25),
            "p50": base.percentile(vals, 0.50),
            "p75": base.percentile(vals, 0.75),
            "p90": base.percentile(vals, 0.90),
        }, len(vals)
    all_vals = [v for group in cohorts["okpd4"].values() for v in group]
    return "global_direct", ("GLOBAL_DIRECT",), {
        "p10": base.percentile(all_vals, 0.10),
        "p25": base.percentile(all_vals, 0.25),
        "p50": base.percentile(all_vals, 0.50),
        "p75": base.percentile(all_vals, 0.75),
        "p90": base.percentile(all_vals, 0.90),
    }, len(all_vals)


def apply_direct_floor(medal: str, price: Any) -> Tuple[str, Optional[str]]:
    cap, reason = direct_value_cap(price)
    if cap is None:
        return medal, None
    if STRING_MEDAL_RANK.get(medal, 0) > STRING_MEDAL_RANK.get(cap.value, 0):
        return cap.value, reason
    return medal, reason


def project_total_scale(row: Dict[str, Any]) -> Optional[float]:
    value = row.get("initial_price")
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def simulate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    direct_cohorts = base.build_direct_cohorts(rows)
    object_counts = base.build_object_cohorts(rows)
    transitions: Counter = Counter()
    direct_medals: Counter = Counter()
    embedded_medals: Counter = Counter()
    unknown_counts: Counter = Counter()
    cohort_usage: Counter = Counter()
    direct_components: Dict[str, List[float]] = defaultdict(list)
    embedded_components: Dict[str, List[float]] = defaultdict(list)
    category_scores: Dict[str, List[float]] = defaultdict(list)
    project_scale_values: List[float] = []
    project_scale_buckets: Counter = Counter()
    future_metrics: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "opportunity_count": 0,
            "direct_volume": 0.0,
            "direct_gmv": 0.0,
            "object_occurrence": 0,
            "doc_confirmed": 0,
            "resource_cost": "NOT_AVAILABLE",
        }
    )

    for row in rows:
        category = row["category"]
        future = future_metrics[category]
        future["opportunity_count"] += 1
        track = row["track"]
        if track == "DIRECT_SUPPLY":
            level, key, stats, n = direct_cohort_stats(row, direct_cohorts)
            cohort_usage[level] += 1
            value = row.get("expected_category_value")
            if value is None or float(value) <= 0:
                value = row.get("initial_price")
            if value is not None and float(value) > 0:
                future["direct_volume"] += float(value)
            if row.get("initial_price") is not None:
                future["direct_gmv"] += float(row["initial_price"])
            value_score = (
                direct_percentile_score(
                    float(value),
                    stats["p10"],
                    stats["p25"],
                    stats["p50"],
                    stats["p75"],
                    stats["p90"],
                )
                if value is not None and float(value) > 0
                else None
            )
            timing, _remaining = base.timing_score(row)
            category_signal = (
                float(row["category_confidence"]) * 100
                if row.get("category_confidence") is not None
                else None
            )
            evidence = 80.0 if row.get("positive_evidence") else None
            parts = {
                "value_ratio": (value_score, 0.45),
                "timing": (timing, 0.20),
                "category_signal": (category_signal, 0.20),
                "actionability": (85.0, 0.15),
                "evidence": (evidence, 0.10),
            }
            for component in ("value_ratio", "timing", "category_signal", "actionability", "evidence"):
                value_component = parts[component][0]
                if value_component is not None:
                    direct_components[component].append(float(value_component))
        elif track == "EMBEDDED_MATERIAL":
            object_type = row.get("object_type")
            object_n = object_counts.get((category, object_type), 0)
            level = "object_cohort" if object_type and object_n >= MIN_N else "category"
            cohort_usage[level] += 1
            if object_type:
                future["object_occurrence"] += 1
            timing, _remaining = base.timing_score(row)
            category_signal = (
                float(row["category_confidence"]) * 100
                if row.get("category_confidence") is not None
                else None
            )
            object_score = 80.0 if object_type and object_n >= MIN_N else (60.0 if object_type else None)
            evidence = base.embedded_evidence_score(row)
            parts = {
                "object_cohort": (object_score, 0.20),
                "evidence": (evidence, 0.25),
                "timing": (timing, 0.20),
                "category_signal": (category_signal, 0.20),
                "actionability": (72.0, 0.15),
                "value_ratio": (None, 0.0),
            }
            for component in ("object_cohort", "evidence", "timing", "category_signal", "actionability"):
                value_component = parts[component][0]
                if value_component is not None:
                    embedded_components[component].append(float(value_component))
            scale = project_total_scale(row)
            if scale is not None:
                project_scale_values.append(scale)
                if scale < 10_000:
                    project_scale_buckets["lt_10k"] += 1
                elif scale < 50_000:
                    project_scale_buckets["lt_50k"] += 1
                elif scale < 100_000:
                    project_scale_buckets["lt_100k"] += 1
                elif scale < 1_000_000:
                    project_scale_buckets["lt_1m"] += 1
                elif scale < 10_000_000:
                    project_scale_buckets["lt_10m"] += 1
                else:
                    project_scale_buckets["gte_10m"] += 1
        else:
            timing, _remaining = base.timing_score(row)
            category_signal = (
                float(row["category_confidence"]) * 100
                if row.get("category_confidence") is not None
                else None
            )
            evidence = base.embedded_evidence_score(row)
            parts = {
                "timing": (timing, 0.30),
                "category_signal": (category_signal, 0.25),
                "evidence": (evidence, 0.25),
                "actionability": (78.0 if track == "DESIGN_REQUIREMENT" else 70.0, 0.20),
            }

        score, missing = base.weighted_available(parts)
        for name in missing:
            unknown_counts[f"{track}:{name}"] += 1
        new_medal = base.medal_from_score(score)
        if track == "DIRECT_SUPPLY":
            floor_price = row.get("final_contract_price") or row.get("initial_price")
            new_medal, _floor_reason = apply_direct_floor(new_medal, floor_price)
            direct_medals[new_medal] += 1
        elif track == "EMBEDDED_MATERIAL":
            quantity_unknown = int(row.get("quantity_count") or 0) <= 0
            category_value_unknown = True  # no valid embedded category value in frozen dataset
            if (
                quantity_unknown
                and category_value_unknown
                and STRING_MEDAL_RANK.get(new_medal, 0) > SILVER_RANK
            ):
                new_medal = "SILVER"
            embedded_medals[new_medal] += 1
        old_medal = str(row.get("old_medal") or "UNKNOWN").upper()
        transitions[(old_medal, new_medal)] += 1
        if score is not None:
            category_scores[category].append(float(score))
        if row.get("material_count") or row.get("quantity_count") or row.get("positive_evidence"):
            future["doc_confirmed"] += 1

    category_medals = Counter()
    category_details = {}
    for category, scores in category_scores.items():
        median_score = base.percentile(scores, 0.50)
        category_medal = base.medal_from_score(median_score)
        category_medals[category_medal] += 1
        future = future_metrics[category]
        future["document_confirmation_rate"] = (
            round(future["doc_confirmed"] / future["opportunity_count"], 4)
            if future["opportunity_count"]
            else None
        )
        category_details[category] = {
            "n": len(scores),
            "median_score": median_score,
            "medal": category_medal,
            "future": dict(future),
        }

    return {
        "transitions": transitions,
        "direct_medals": direct_medals,
        "embedded_medals": embedded_medals,
        "category_medals": category_medals,
        "category_details": category_details,
        "unknown_counts": unknown_counts,
        "cohort_usage": cohort_usage,
        "direct_components": direct_components,
        "embedded_components": embedded_components,
        "project_scale_values": project_scale_values,
        "project_scale_buckets": project_scale_buckets,
    }


def main() -> int:
    conn = psycopg2.connect(**base.crm_dsn())
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            rows = base.load_rows(cur)
        result = simulate(rows)
        print("SIMULATION_MODEL=medal_v1_read_only_sim_v1_1")
        print(f"ROWS={len(rows)}")
        base.print_counter("TRANSITION_MATRIX old->new", result["transitions"])
        base.print_counter("CATEGORY_MEDALS", result["category_medals"])
        base.print_counter("DIRECT_MEDALS", result["direct_medals"])
        base.print_counter("EMBEDDED_MEDALS", result["embedded_medals"])
        base.print_counter("COHORT_USAGE", result["cohort_usage"])
        base.print_counter("UNKNOWN_COMPONENTS", result["unknown_counts"])
        base.print_component("DIRECT_COMPONENTS", result["direct_components"])
        base.print_component("EMBEDDED_COMPONENTS", result["embedded_components"])
        print("\nPROJECT_TOTAL_SCALE_DIAGNOSTIC")
        for key, value in sorted(result["project_scale_buckets"].items()):
            print(f"{key}={value}")
        values = result["project_scale_values"]
        print(
            "PROJECT_TOTAL_SCALE|"
            f"N={len(values)}|P25={base.percentile(values,0.25)}|"
            f"median={base.percentile(values,0.50)}|P75={base.percentile(values,0.75)}"
        )
        print("\nCATEGORY_DETAIL")
        for category, detail in sorted(result["category_details"].items()):
            print(f"{category}|{detail}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
