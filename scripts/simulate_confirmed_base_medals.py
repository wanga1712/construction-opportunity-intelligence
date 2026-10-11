#!/usr/bin/env python3
"""READ-ONLY confirmed_base medal simulation on the new fact layer.

Value rule: only VERIFIED line_total participates in the value cohort.
INCONSISTENT_LAYOUT / UNSUPPORTED_LAYOUT -> value NOT_AVAILABLE (never 0, no
penalty as 'small value'). quantity/unit may still be used when confirmed.
Project NMCK is never used as a category value.
No writes.
"""

from __future__ import annotations

import os
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DIRECT_CATS = {"computers", "lighting", "cable_support_systems"}


def crm_dsn() -> Dict[str, Any]:
    return {"host": os.getenv("CRM_DB_HOST", "127.0.0.1"), "port": int(os.getenv("CRM_DB_PORT", "5432")),
            "dbname": os.getenv("CRM_DB_DATABASE") or os.getenv("CRM_DB_NAME") or "crm",
            "user": os.getenv("CRM_DB_USER", "crm_app"), "password": os.getenv("CRM_DB_PASSWORD", "")}


def di_dsn() -> Dict[str, Any]:
    return {"host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
            "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
            "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
            "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
            "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", "")}


def query(conn, sql: str, params: Optional[list] = None) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _pct_rank(values: List[float], v: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    below = sum(1 for x in s if x <= v)
    return 100.0 * below / len(s)


def main() -> int:
    di = psycopg2.connect(**di_dsn())
    crm = psycopg2.connect(**crm_dsn())
    try:
        opps = query(crm, """
            SELECT o.procurement_id, o.commercial_category_code AS category_code,
                   o.opportunity_track, o.commercial_state, o.candidate_initial_medal,
                   o.current_effective_medal, o.expected_category_value, o.category_value_basis,
                   p.execution_end_at, p.delivery_end_date, p.end_date
              FROM crm_procurement_category_opportunities o
              JOIN crm_procurements p ON p.id = o.procurement_id
             WHERE o.status = 'CURRENT'
        """)
        facts = query(di, """
            SELECT procurement_id, category_code,
                   count(*) AS facts,
                   count(*) FILTER (WHERE quantity_value IS NOT NULL AND unit_normalized IS NOT NULL) AS qty,
                   count(*) FILTER (WHERE line_total_value IS NOT NULL) AS verified_value_rows,
                   coalesce(sum(line_total_value), 0) AS verified_value
              FROM confirmed_category_facts
             GROUP BY 1,2
        """)
        idx = {(int(f["procurement_id"]), f["category_code"]): f for f in facts}
        # value cohorts per category (verified only)
        cohort: Dict[str, List[float]] = defaultdict(list)
        for f in facts:
            if f["verified_value_rows"]:
                cohort[f["category_code"]].append(float(f["verified_value"]))

        today = datetime.now(timezone.utc).date()
        rows = []
        for o in opps:
            pid, cat = int(o["procurement_id"]), o["category_code"]
            track = "DIRECT" if cat in DIRECT_CATS else "EMBEDDED"
            f = idx.get((pid, cat))
            has_facts = bool(f and f["facts"])
            has_qty = bool(f and f["qty"])
            has_value = bool(f and f["verified_value_rows"])
            # components (missing -> NOT_AVAILABLE, weights renormalise)
            comps: Dict[str, Optional[float]] = {}
            comps["evidence"] = 1.0 if has_value else (0.6 if has_qty else (0.3 if has_facts else 0.0))
            if has_value:
                r = _pct_rank(cohort[cat], float(f["verified_value"]))
                comps["value"] = (r / 100.0) if r is not None else None
            else:
                comps["value"] = None
            end = o.get("execution_end_at") or o.get("delivery_end_date") or o.get("end_date")
            try:
                end_d = end.date() if hasattr(end, "date") else (date.fromisoformat(str(end)) if end else None)
            except Exception:
                end_d = None
            if end_d:
                days = (end_d - today).days
                comps["timing"] = 1.0 if days >= 90 else (0.7 if days >= 30 else (0.4 if days >= 0 else 0.0))
            else:
                comps["timing"] = None
            comps["category_signal"] = {"GOLD": 1.0, "SILVER": 0.8, "BRONZE": 0.6, "WOOD": 0.3}.get(
                (o.get("candidate_initial_medal") or "").upper(), 0.5
            )
            comps["actionability"] = 1.0 if (o.get("commercial_state") or "").upper() in {"OPEN", "ACTIVE"} else 0.6

            weights = {"evidence": 0.25, "value": 0.30, "timing": 0.15,
                       "category_signal": 0.15, "actionability": 0.15} if track == "DIRECT" else \
                      {"evidence": 0.35, "value": 0.15, "timing": 0.15,
                       "category_signal": 0.20, "actionability": 0.15}
            avail = {k: v for k, v in comps.items() if v is not None}
            wsum = sum(weights[k] for k in avail) or 1.0
            score = 100.0 * sum(weights[k] * avail[k] for k in avail) / wsum
            if track == "EMBEDDED" and not has_value:
                score = min(score, 74.99)  # RESEARCH_PRIORITY cap = max SILVER
            medal = "GOLD" if score >= 85 else "SILVER" if score >= 70 else "BRONZE" if score >= 50 else "WOOD"
            rows.append({"pid": pid, "cat": cat, "track": track, "score": round(score, 2), "medal": medal,
                         "has_facts": has_facts, "has_qty": has_qty, "has_value": has_value,
                         "value": float(f["verified_value"]) if has_value else None,
                         "state": o.get("commercial_state"), "conf": comps})

        c = Counter()
        by_cat = defaultdict(Counter)
        by_track = defaultdict(Counter)
        for r in rows:
            c[f"MEDAL_{r['medal']}"] += 1
            by_cat[r["cat"]][r["medal"]] += 1
            by_track[r["track"]][r["medal"]] += 1
            if r["has_facts"]:
                c["WITH_CONFIRMED_FACTS"] += 1
            if r["has_qty"]:
                c["WITH_QUANTITY"] += 1
            if r["has_value"]:
                c["WITH_VERIFIED_VALUE"] += 1
            if r["medal"] in {"GOLD", "SILVER", "BRONZE"}:
                if r["has_value"]:
                    c["MEDALS_USING_VERIFIED_VALUE"] += 1
                else:
                    c["MEDALS_WITH_VALUE_NOT_AVAILABLE"] += 1
        print("=" * 78)
        print("CONFIRMED_BASE MEDAL SIMULATION (READ-ONLY)")
        print(f"CURRENT_OPPORTUNITIES={len(rows)}")
        print(f"WITH_CONFIRMED_FACTS={c['WITH_CONFIRMED_FACTS']}")
        print(f"WITH_QUANTITY={c['WITH_QUANTITY']}")
        print(f"WITH_VERIFIED_VALUE={c['WITH_VERIFIED_VALUE']}")
        print(f"GOLD={c['MEDAL_GOLD']}  SILVER={c['MEDAL_SILVER']}  BRONZE={c['MEDAL_BRONZE']}  WOOD={c['MEDAL_WOOD']}")
        print(f"MEDALS_USING_VERIFIED_VALUE={c['MEDALS_USING_VERIFIED_VALUE']}")
        print(f"MEDALS_WITH_VALUE_NOT_AVAILABLE={c['MEDALS_WITH_VALUE_NOT_AVAILABLE']}")
        print("PROJECT_NMCK_USED_AS_CATEGORY_VALUE=0")
        for cat in sorted(by_cat):
            print(f"BY_CATEGORY[{cat}]={dict(by_cat[cat])}")
        for tr in sorted(by_track):
            print(f"BY_TRACK[{tr}]={dict(by_track[tr])}")
        print("-" * 78)
        print("SAMPLES (GOLD/SILVER, EMBEDDED)")
        shown = [r for r in rows if r["track"] == "EMBEDDED" and r["medal"] in {"GOLD", "SILVER"}]
        for r in shown[:10]:
            print(f"  pid={r['pid']} cat={r['cat']} medal={r['medal']} score={r['score']} "
                  f"facts={r['has_facts']} qty={r['has_qty']} value={r['value']} state={r['state']} "
                  f"comps={ {k: (round(v,2) if v is not None else None) for k, v in r['conf'].items()} }")
        return 0
    finally:
        di.close()
        crm.close()


if __name__ == "__main__":
    raise SystemExit(main())
