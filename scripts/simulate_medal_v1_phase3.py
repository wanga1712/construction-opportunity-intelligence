#!/usr/bin/env python3
"""Read-only Phase 3 Medal V1 simulation.

SIMULATION_MODEL=medal_v1_read_only_sim_v1

DIRECT:
  value ratio to accepted MIN_N=20 cohort
  + timing + category signal + actionability

EMBEDDED:
  evidence + object cohort + timing + actionability
  VALUE_COMPONENT=UNKNOWN (never total procurement NMCK)

No production writes.
"""

from __future__ import annotations

import math
import os
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

MIN_N = 20
THRESHOLDS = (75.0, 50.0, 25.0)


def crm_dsn() -> dict:
    return {
        "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("CRM_DB_PORT", "5432")),
        "dbname": os.getenv("CRM_DB_DATABASE") or os.getenv("CRM_DB_NAME") or "crm",
        "user": os.getenv("CRM_DB_USER", "crm_app"),
        "password": os.getenv("CRM_DB_PASSWORD", ""),
    }


def percentile(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    vals = sorted(float(v) for v in values)
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * p
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return vals[lo]
    return vals[lo] * (hi - pos) + vals[hi] * (pos - lo)


def medal_from_score(score: Optional[float]) -> str:
    if score is None:
        return "UNKNOWN"
    if score >= THRESHOLDS[0]:
        return "GOLD"
    if score >= THRESHOLDS[1]:
        return "SILVER"
    if score >= THRESHOLDS[2]:
        return "BRONZE"
    return "WOOD"


def as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def timing_score(row: Dict[str, Any]) -> Tuple[Optional[float], Optional[int]]:
    today = date.today()
    lifecycle = str(row.get("commercial_state") or row.get("crm_stage") or "").upper()
    if lifecycle in ("FOLLOW_UP_AWARDED", "AWARDED"):
        deadline = (
            row.get("execution_end_at")
            or row.get("delivery_end_date")
            or row.get("end_date")
        )
    else:
        deadline = row.get("submission_deadline_at") or row.get("end_date")
    d = as_date(deadline)
    if d is None:
        return None, None
    remaining = (d - today).days
    if remaining < 0:
        score = 10.0
    elif remaining < 3:
        score = 25.0
    elif remaining < 14:
        score = 45.0
    elif remaining < 30:
        score = 65.0
    elif remaining < 90:
        score = 80.0
    else:
        score = 100.0
    return score, remaining


def weighted_available(parts: Dict[str, Tuple[Optional[float], float]]) -> Tuple[Optional[float], List[str]]:
    available = {k: v for k, (v, _w) in parts.items() if v is not None}
    missing = [k for k, (v, _w) in parts.items() if v is None]
    if not available:
        return None, missing
    total_w = sum(_w for _w in (parts[k][1] for k in available))
    score = sum(float(parts[k][0]) * parts[k][1] for k in available) / total_w
    return score, missing


def load_rows(cur) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT o.id, o.procurement_id, o.commercial_category_code AS category,
               o.opportunity_track AS track, o.commercial_state,
               o.procurement_form, o.category_confidence,
               o.expected_category_value, o.category_value_basis,
               o.current_effective_medal AS old_medal,
               o.current_effective_score AS old_score,
               o.positive_evidence,
               p.okpd_code, p.initial_price, p.start_date, p.end_date,
               p.execution_start_at, p.execution_end_at,
               p.delivery_start_date, p.delivery_end_date, p.crm_stage,
               c.object_type,
               COALESCE(mat.material_count, 0) AS material_count,
               COALESCE(qty.quantity_count, 0) AS quantity_count
          FROM crm_procurement_category_opportunities o
          JOIN crm_procurements p ON p.id = o.procurement_id
          LEFT JOIN LATERAL (
              SELECT object_type FROM crm_procurement_object_classifications x
               WHERE x.procurement_id = o.procurement_id AND x.is_current
               ORDER BY x.id DESC LIMIT 1
          ) c ON TRUE
          LEFT JOIN LATERAL (
              SELECT count(*) AS material_count
                FROM crm_procurement_product_candidates pc
               WHERE pc.procurement_id = o.procurement_id
                 AND pc.is_current AND COALESCE(pc.material, '') <> ''
          ) mat ON TRUE
          LEFT JOIN LATERAL (
              SELECT count(*) AS quantity_count
                FROM crm_v3_product_findings pf
               WHERE pf.procurement_id = o.procurement_id
                 AND pf.quantity IS NOT NULL
          ) qty ON TRUE
         WHERE o.status = 'CURRENT'
        """
    )
    return [dict(r) for r in cur.fetchall()]


def okpd_levels(code: Any) -> Dict[str, Optional[str]]:
    text = str(code or "")
    parts = text.split(".")
    return {
        "okpd2": parts[0] if len(parts) >= 2 else None,
        "okpd3": ".".join(parts[:2]) if len(parts) >= 3 else None,
        "okpd4": ".".join(parts[:3]) if len(parts) >= 4 else None,
    }


def build_direct_cohorts(rows: List[Dict[str, Any]]) -> Dict[str, Dict[Tuple, List[float]]]:
    cohorts: Dict[str, Dict[Tuple, List[float]]] = {
        "okpd4": defaultdict(list),
        "okpd3": defaultdict(list),
        "okpd2": defaultdict(list),
        "category": defaultdict(list),
    }
    for row in rows:
        if row["track"] != "DIRECT_SUPPLY":
            continue
        value = row.get("expected_category_value")
        if value is None or float(value) <= 0:
            value = row.get("initial_price")
        if value is None or float(value) <= 0:
            continue
        value = float(value)
        levels = okpd_levels(row.get("okpd_code"))
        key_cat = row["category"]
        cohorts["category"][(key_cat,)].append(value)
        for level in ("okpd2", "okpd3", "okpd4"):
            code = levels[level]
            if code:
                cohorts[level][(key_cat, code)].append(value)
    return cohorts


def pick_direct_cohort(
    row: Dict[str, Any], cohorts: Dict[str, Dict[Tuple, List[float]]]
) -> Tuple[str, Tuple, Optional[float], Optional[float], Optional[float], int]:
    levels = okpd_levels(row.get("okpd_code"))
    cat = row["category"]
    for level in ("okpd4", "okpd3", "okpd2"):
        code = levels[level]
        key = (cat, code)
        vals = cohorts[level].get(key) or []
        if code and len(vals) >= MIN_N:
            return level, key, percentile(vals, 0.5), percentile(vals, 0.25), percentile(vals, 0.75), len(vals)
    vals = cohorts["category"].get((cat,)) or []
    if len(vals) >= MIN_N:
        return "category", (cat,), percentile(vals, 0.5), percentile(vals, 0.25), percentile(vals, 0.75), len(vals)
    all_vals = [v for group in cohorts["okpd4"].values() for v in group]
    return "global_direct", ("GLOBAL_DIRECT",), percentile(all_vals, 0.5), percentile(all_vals, 0.25), percentile(all_vals, 0.75), len(all_vals)


def build_object_cohorts(rows: List[Dict[str, Any]]) -> Dict[Tuple, int]:
    counts: Counter = Counter()
    for row in rows:
        if row["track"] == "EMBEDDED_MATERIAL":
            counts[(row["category"], row.get("object_type"))] += 1
    return counts


def embedded_evidence_score(row: Dict[str, Any]) -> Optional[float]:
    material = int(row.get("material_count") or 0)
    quantity = int(row.get("quantity_count") or 0)
    object_type = str(row.get("object_type") or "").strip()
    if material > 0 and object_type:
        return 80.0
    if object_type:
        return 65.0
    if material > 0 or quantity > 0:
        return 60.0
    return None


def direct_value_score(row: Dict[str, Any], cohort_median: Optional[float]) -> Optional[float]:
    value = row.get("expected_category_value")
    if value is None or float(value) <= 0:
        value = row.get("initial_price")
    if value is None or float(value) <= 0 or not cohort_median:
        return None
    ratio = float(value) / float(cohort_median)
    if ratio >= 2.0:
        return 100.0
    if ratio >= 1.0:
        return 75.0
    if ratio >= 0.5:
        return 50.0
    return 25.0


def simulate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    direct_cohorts = build_direct_cohorts(rows)
    object_counts = build_object_cohorts(rows)
    transitions: Counter = Counter()
    direct_medals: Counter = Counter()
    embedded_medals: Counter = Counter()
    category_scores: Dict[str, List[float]] = defaultdict(list)
    component_values: Dict[str, List[float]] = defaultdict(list)
    unknown_counts: Counter = Counter()
    cohort_usage: Counter = Counter()
    direct_cohort_usage: Counter = Counter()
    embedded_cohort_usage: Counter = Counter()
    category_details: Dict[str, Dict[str, Any]] = {}
    cohort_examples: Dict[str, Dict[str, Any]] = {}
    direct_components: Dict[str, List[float]] = defaultdict(list)
    embedded_components: Dict[str, List[float]] = defaultdict(list)

    for row in rows:
        track = row["track"]
        parts: Dict[str, Tuple[Optional[float], float]]
        if track == "DIRECT_SUPPLY":
            level, key, median, p25, p75, n = pick_direct_cohort(row, direct_cohorts)
            cohort_usage[level] += 1
            direct_cohort_usage[level] += 1
            cohort_examples[f"{level}:{key}"] = {
                "n": n, "median": median, "p25": p25, "p75": p75
            }
            value_score = direct_value_score(row, median)
            timing, remaining = timing_score(row)
            category_signal = (
                float(row["category_confidence"]) * 100
                if row.get("category_confidence") is not None
                else None
            )
            actionability = 85.0
            evidence = 80.0 if row.get("positive_evidence") else None
            parts = {
                "value_ratio": (value_score, 0.45),
                "timing": (timing, 0.20),
                "category_signal": (category_signal, 0.20),
                "actionability": (actionability, 0.15),
                "evidence": (evidence, 0.10),
            }
            for key_name in ("value_ratio", "timing", "category_signal", "actionability", "evidence"):
                val = parts[key_name][0]
                if val is not None:
                    direct_components[key_name].append(float(val))
        elif track == "EMBEDDED_MATERIAL":
            object_type = row.get("object_type")
            object_key = (row["category"], object_type)
            object_n = object_counts.get(object_key, 0)
            level = "object_cohort" if object_type and object_n >= MIN_N else "category"
            cohort_usage[level] += 1
            embedded_cohort_usage[level] += 1
            if object_type and object_n >= MIN_N:
                cohort_examples[f"object:{object_key}"] = {"n": object_n}
            value_score = None
            timing, remaining = timing_score(row)
            category_signal = (
                float(row["category_confidence"]) * 100
                if row.get("category_confidence") is not None
                else None
            )
            object_score = 80.0 if object_type and object_n >= MIN_N else (60.0 if object_type else None)
            evidence = embedded_evidence_score(row)
            actionability = 72.0
            parts = {
                "value_ratio": (None, 0.0),
                "object_cohort": (object_score, 0.20),
                "evidence": (evidence, 0.25),
                "timing": (timing, 0.20),
                "category_signal": (category_signal, 0.20),
                "actionability": (actionability, 0.15),
            }
            for key_name in ("object_cohort", "evidence", "timing", "category_signal", "actionability"):
                val = parts[key_name][0]
                if val is not None:
                    embedded_components[key_name].append(float(val))
        else:
            # DESIGN and other tracks: use only non-value evidence/timing/actionability.
            timing, remaining = timing_score(row)
            category_signal = (
                float(row["category_confidence"]) * 100
                if row.get("category_confidence") is not None
                else None
            )
            actionability = 78.0 if track == "DESIGN_REQUIREMENT" else 70.0
            evidence = embedded_evidence_score(row)
            parts = {
                "timing": (timing, 0.30),
                "category_signal": (category_signal, 0.25),
                "evidence": (evidence, 0.25),
                "actionability": (actionability, 0.20),
            }
            for key_name in ("timing", "category_signal", "evidence", "actionability"):
                val = parts[key_name][0]
                if val is not None:
                    embedded_components[key_name].append(float(val))

        score, missing = weighted_available(parts)
        for name in missing:
            unknown_counts[f"{track}:{name}"] += 1
        new_medal = medal_from_score(score)
        old_medal = str(row.get("old_medal") or "UNKNOWN").upper()
        transitions[(old_medal, new_medal)] += 1
        if track == "DIRECT_SUPPLY":
            direct_medals[new_medal] += 1
        elif track == "EMBEDDED_MATERIAL":
            embedded_medals[new_medal] += 1
        if score is not None:
            category_scores[row["category"]].append(float(score))

    category_medals = Counter()
    for category, scores in category_scores.items():
        median_score = percentile(scores, 0.5)
        category_medal = medal_from_score(median_score)
        category_medals[category_medal] += 1
        category_details[category] = {
            "n": len(scores),
            "median_score": median_score,
            "medal": category_medal,
        }

    return {
        "transitions": transitions,
        "direct_medals": direct_medals,
        "embedded_medals": embedded_medals,
        "category_medals": category_medals,
        "category_details": category_details,
        "unknown_counts": unknown_counts,
        "cohort_usage": cohort_usage,
        "direct_cohort_usage": direct_cohort_usage,
        "embedded_cohort_usage": embedded_cohort_usage,
        "cohort_examples": cohort_examples,
        "direct_components": direct_components,
        "embedded_components": embedded_components,
    }


def print_counter(title: str, counter: Counter) -> None:
    print(f"\n{title}")
    for key, value in sorted(counter.items(), key=lambda x: str(x[0])):
        print(f"{key}={value}")


def print_component(title: str, components: Dict[str, List[float]]) -> None:
    print(f"\n{title}")
    for key, values in sorted(components.items()):
        print(
            f"{key}|N={len(values)}|p25={percentile(values,0.25):.2f}|"
            f"median={percentile(values,0.50):.2f}|p75={percentile(values,0.75):.2f}"
        )


def main() -> int:
    conn = psycopg2.connect(**crm_dsn())
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            rows = load_rows(cur)
        result = simulate(rows)
        print("SIMULATION_MODEL=medal_v1_read_only_sim_v1")
        print(f"ROWS={len(rows)}")
        print_counter("TRANSITION_MATRIX old->new", result["transitions"])
        print_counter("CATEGORY_MEDALS", result["category_medals"])
        print_counter("DIRECT_MEDALS", result["direct_medals"])
        print_counter("EMBEDDED_MEDALS", result["embedded_medals"])
        print_counter("COHORT_USAGE", result["cohort_usage"])
        print_counter("DIRECT_COHORT_USAGE", result["direct_cohort_usage"])
        print_counter("EMBEDDED_COHORT_USAGE", result["embedded_cohort_usage"])
        print_counter("UNKNOWN_COMPONENTS", result["unknown_counts"])
        print("\nCATEGORY_DETAIL")
        for category, detail in sorted(result["category_details"].items()):
            print(f"{category}|{detail}")
        print_component("DIRECT_COMPONENTS", result["direct_components"])
        print_component("EMBEDDED_COMPONENTS", result["embedded_components"])
        print("\nCOHORT_EXAMPLES")
        for key, value in sorted(result["cohort_examples"].items())[:40]:
            print(f"{key}|{value}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
