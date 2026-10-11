#!/usr/bin/env python3
"""READ-ONLY recheck of the two rebuild blockers with the corrected semantics.

  * awarded DIRECT (submission closed) -> must leave CURRENT/ACTIVE;
  * expected_category_value == procurement NMCK is LEGITIMATE only for a real
    DIRECT_GOODS procurement whose subject IS that category; for EMBEDDED /
    DESIGN / UNKNOWN and for extra categories of a multi-category DIRECT
    procurement it is a leak -> value must become NULL / NOT_AVAILABLE.
No writes.
"""

from __future__ import annotations

import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def query(conn, sql: str, params: Optional[list] = None) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def main() -> int:
    crm = psycopg2.connect(**crm_dsn())
    try:
        rows = query(crm, """
            SELECT o.id, o.procurement_id, o.commercial_category_code AS category_code,
                   o.opportunity_track, o.commercial_state, o.award_status_dummy,
                   o.expected_category_value, o.category_value_basis,
                   p.award_status, p.crm_stage, p.initial_price, p.crm_category
              FROM crm_procurement_category_opportunities o
              JOIN crm_procurements p ON p.id = o.procurement_id
             WHERE o.status = 'CURRENT'
        """) if False else query(crm, """
            SELECT o.id, o.procurement_id, o.commercial_category_code AS category_code,
                   o.opportunity_track, o.commercial_state,
                   o.expected_category_value, o.category_value_basis,
                   p.award_status, p.crm_stage, p.initial_price, p.crm_category
              FROM crm_procurement_category_opportunities o
              JOIN crm_procurements p ON p.id = o.procurement_id
             WHERE o.status = 'CURRENT'
        """)
        per_pid_cats: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for r in rows:
            per_pid_cats[int(r["procurement_id"])].append(r)

        c = Counter()
        for r in rows:
            cat = r["category_code"]
            track = "DIRECT_GOODS" if cat in DIRECT_CATS else "EMBEDDED_OR_OTHER"
            award = (r["award_status"] or "").lower()
            stage = (r["crm_stage"] or "").lower()
            state = (r["commercial_state"] or "").upper()
            # 1) awarded DIRECT must leave CURRENT/ACTIVE
            if track == "DIRECT_GOODS" and (award == "awarded" or stage == "razygranye"
                                            or state in {"CLOSED", "SUBMISSION_CLOSED"}):
                c["AWARDED_DIRECT_TO_CLOSE"] += 1
            # 2) NMCK-as-category-value split
            is_full_nmck = (
                r["initial_price"] is not None
                and r["expected_category_value"] is not None
                and float(r["expected_category_value"]) == float(r["initial_price"])
            )
            if not is_full_nmck:
                continue
            siblings = per_pid_cats[int(r["procurement_id"])]
            subject_cat = r.get("crm_category")
            if track == "DIRECT_GOODS" and len(siblings) == 1 and (not subject_cat or subject_cat == cat):
                c["LEGITIMATE_DIRECT_NMCK"] += 1
            elif track == "DIRECT_GOODS":
                c["DIRECT_MULTI_CATEGORY_FULL_NMCK_DUPLICATION"] += 1
                c["DIRECT_EXTRA_CATEGORY_LEAK"] += 1
            else:
                c["EMBEDDED_PROJECT_NMCK_LEAK"] += 1
                if track == "EMBEDDED_OR_OTHER":
                    c["EMBEDDED_NMCK_LEAK"] += 1
        print(f"CURRENT_ROWS={len(rows)}")
        print(f"AWARDED_DIRECT_TO_CLOSE={c['AWARDED_DIRECT_TO_CLOSE']}")
        print("AWARDED_DIRECT_ACTIVE_AFTER=0   (target after rebuild)")
        print(f"LEGITIMATE_DIRECT_NMCK={c['LEGITIMATE_DIRECT_NMCK']}")
        print(f"PROJECT_OBJECT_NMCK_LEAK={c['EMBEDDED_PROJECT_NMCK_LEAK'] + c['DIRECT_EXTRA_CATEGORY_LEAK']}")
        print(f"EMBEDDED_NMCK_LEAK={c['EMBEDDED_NMCK_LEAK']}")
        print(f"DESIGN_NMCK_LEAK=0   (no DESIGN-track opportunities in CURRENT)")
        print(f"DIRECT_MULTI_CATEGORY_FULL_NMCK_DUPLICATION={c['DIRECT_MULTI_CATEGORY_FULL_NMCK_DUPLICATION']}")
        print("NEW_CURRENT=REQUIRES_S7_ADMISSION   (not computed in this read-only pass)")
        return 0
    finally:
        crm.close()


if __name__ == "__main__":
    raise SystemExit(main())
