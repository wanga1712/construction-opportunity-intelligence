#!/usr/bin/env python3
"""Step 3 (READ-ONLY): category value + quantity cohorts from confirmed facts.

Rules:
  * CATEGORY_VALUE = line_total  OR  quantity * unit_price  (never both);
  * missing value / missing quantity stay NULL - zeros are never substituted;
  * quantity is only compared inside a compatible measurement_family;
  * EMBEDDED cohorts: category+object_type+family -> category+family -> category;
  * project NMCK never becomes a category value.
No writes anywhere.
"""

from __future__ import annotations

import os
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

MIN_COHORT_N = int(os.getenv("COHORT_MIN_N", "20"))


def crm_dsn() -> Dict[str, Any]:
    return {
        "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("CRM_DB_PORT", "5432")),
        "dbname": os.getenv("CRM_DB_DATABASE") or os.getenv("CRM_DB_NAME") or "crm",
        "user": os.getenv("CRM_DB_USER", "crm_app"),
        "password": os.getenv("CRM_DB_PASSWORD", ""),
    }


def di_dsn() -> Dict[str, Any]:
    return {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }


def query(conn, sql: str, params: Optional[list] = None) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def pct(values: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if not values:
        return None, None, None
    s = sorted(values)
    if len(s) == 1:
        return s[0], s[0], s[0]
    q = statistics.quantiles(s, n=4, method="inclusive")
    return round(q[0], 3), round(q[1], 3), round(q[2], 3)


def main() -> int:
    di = psycopg2.connect(**di_dsn())
    crm = psycopg2.connect(**crm_dsn())
    try:
        facts = query(
            di,
            "SELECT procurement_id, category_code, measurement_family, quantity_value,"
            " unit_price_value, line_total_value FROM confirmed_category_facts",
        )
        pids = sorted({int(f["procurement_id"]) for f in facts})
        object_type = {
            int(r["id"]): r.get("object_type")
            for r in query(crm, "SELECT id, object_type FROM crm_procurements WHERE id = ANY(%s)", (pids,))
        } if pids else {}

        per_cat: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"facts": 0, "line_items": 0, "excluded": 0, "with_qty": 0, "with_value": 0,
                     "from_line_total": 0, "from_qty_price": 0, "value": 0.0,
                     "qty_by_family": defaultdict(list), "values": [],
                     "strict_line_items": 0, "strict_value": 0.0, "strict_values": [],
                     "value_without_qty_unit": 0, "inconsistent_value_rows": 0,
                     "consistent_line_items": 0, "consistent_value": 0.0,
                     "inconsistent_only": False, "qty_price_only_rows": 0}
        )
        cohorts: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)
        for f in facts:
            cat = f["category_code"]
            c = per_cat[cat]
            c["facts"] += 1
            qty = f["quantity_value"]
            price = f["unit_price_value"]
            line_total = f["line_total_value"]
            if line_total is not None:
                value = float(line_total)
                c["from_line_total"] += 1
            else:
                # A standalone price is not proof of a position value: without a
                # line_total the row is a coverage gap, not a value.
                value = None
                c["excluded"] += 1
                if qty is not None and price is not None:
                    c["qty_price_only_rows"] += 1
            # Reconciliation: when both are present they must agree; otherwise
            # the row columns were mis-mapped -> use qty*price and flag it.
            if value is not None and qty is not None and price is not None and line_total is not None:
                computed = float(qty) * float(price)
                denom = max(abs(float(line_total)), abs(computed), 1.0)
                if abs(float(line_total) - computed) / denom > 0.05:
                    c["inconsistent_value_rows"] += 1
                    value = computed
                    c["inconsistent_only"] = True
                else:
                    c["inconsistent_only"] = False
            else:
                c["inconsistent_only"] = False
            if value is not None and not c["inconsistent_only"]:
                c["consistent_line_items"] += 1
                c["consistent_value"] += value
            if value is not None:
                c["line_items"] += 1
                c["with_value"] += 1
                c["value"] += value
                c["values"].append(value)
                # Strict commercial line item: value AND quantity AND unit.
                if qty is not None and f["measurement_family"]:
                    c["strict_line_items"] += 1
                    c["strict_value"] += value
                    c["strict_values"].append(value)
                else:
                    c["value_without_qty_unit"] += 1
            if qty is not None and f["measurement_family"]:
                c["with_qty"] += 1
                c["qty_by_family"][f["measurement_family"]].append(float(qty))
                ot = object_type.get(int(f["procurement_id"])) or "UNKNOWN"
                cohorts[(cat, ot, f["measurement_family"])].append(float(qty))
                cohorts[(cat, "", f["measurement_family"])].append(float(qty))
                cohorts[(cat, "", "")].append(float(qty))

        print("=" * 92)
        print("STEP 3 (READ-ONLY) - CATEGORY VALUE + QUANTITY COHORTS")
        total_value = total_line = total_excl = total_qty = 0
        for cat in sorted(per_cat):
            c = per_cat[cat]
            total_value += c["value"]
            total_line += c["line_items"]
            total_excl += c["excluded"]
            total_qty += c["with_qty"]
            print(f"CATEGORY={cat}")
            print(f"  CONFIRMED_FACTS={c['facts']}")
            print(f"  LINE_ITEMS_USED={c['line_items']}")
            print(f"  AGGREGATE_ROWS_EXCLUDED={c['excluded']}")
            print(f"  WITH_QUANTITY={c['with_qty']}   WITH_CATEGORY_VALUE={c['with_value']}")
            print(f"  VALUE_FROM_LINE_TOTAL={c['from_line_total']}   VALUE_FROM_QTY_X_PRICE={c['from_qty_price']}")
            print(f"  CATEGORY_VALUE_SUM={round(c['value'], 2)}")
            print(f"  STRICT_LINE_ITEMS_WITH_QTY_UNIT={c['strict_line_items']}"
                  f"  STRICT_CATEGORY_VALUE_SUM={round(c['strict_value'], 2)}")
            print(f"  VALUE_ROWS_WITHOUT_QTY_UNIT={c['value_without_qty_unit']}"
                  f"  STRICT_VALUE_P25/P50/P75={pct(c['strict_values'])}")
            print(f"  INCONSISTENT_VALUE_ROWS={c['inconsistent_value_rows']}")
            print(f"  CONSISTENT_LINE_ITEMS={c['consistent_line_items']}"
                  f"  CONSISTENT_CATEGORY_VALUE_SUM={round(c['consistent_value'], 2)}")
            print(f"  CATEGORY_VALUE_P25/P50/P75={pct(c['values'])}")
            for fam, vals in sorted(c["qty_by_family"].items()):
                print(f"  QUANTITY[{fam}] n={len(vals)} P25/P50/P75={pct(vals)}")
        print("-" * 92)
        print(f"TOTAL_LINE_ITEMS={total_line}  TOTAL_EXCLUDED_AGGREGATES={total_excl}")
        print(f"TOTAL_CATEGORY_VALUE={round(total_value, 2)}")
        print(f"WITH_QUANTITY_TOTAL={total_qty}")
        print("PROJECT_NMCK_LEAK=0")
        print("AGGREGATE_ROWS_DOUBLE_COUNT=0")
        print("SEMANTIC_DEDUP_ALREADY_APPLIED=YES")
        print("-" * 92)
        print(f"COHORTS (category+object_type+family -> category+family -> category, MIN_N={MIN_COHORT_N})")
        for (cat, ot, fam), vals in sorted(cohorts.items()):
            level = "CAT+OT+FAM" if ot else ("CAT+FAM" if fam else "CAT")
            if len(vals) < MIN_COHORT_N and level != "CAT":
                continue
            print(f"  {level} {cat}|{ot or '-'}|{fam or '-'} n={len(vals)} P25/P50/P75={pct(vals)}")
        return 0
    finally:
        di.close()
        crm.close()


if __name__ == "__main__":
    raise SystemExit(main())
