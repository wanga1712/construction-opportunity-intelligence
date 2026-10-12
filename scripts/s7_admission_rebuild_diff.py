#!/usr/bin/env python3
"""READ-ONLY admission/lifecycle rebuild diff (canonical authority).

Uses the canonical pure function `compute_opportunity_lifecycle_updates`, which
derives the source lifecycle from `crm_procurements` (the S7-mirrored table) - so
the rebuild is computed on the actual source truth, not on a parallel rule set.

Reports KEEP / BECOME_SUPERSEDED / NEW_CURRENT candidates and the post-rebuild
target checks. No writes.
"""

from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.services.commercial_routing_v3.opportunity_lifecycle_sync import (  # noqa: E402
    compute_opportunity_lifecycle_updates,
)

INACTIVE_STATES = {"CLOSED", "ARCHIVED", "STALE_SOURCE", "SUPPRESSED", "TERMINAL"}
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
        opp_rows = query(crm, """
            SELECT id, procurement_id, commercial_category_code, commercial_subcategory_code,
                   opportunity_track, commercial_state, last_source_event, source_sync_status,
                   source_missing_since, expected_category_value, category_value_basis
              FROM crm_procurement_category_opportunities
             WHERE status = 'CURRENT' ORDER BY id
        """)
        pids = sorted({int(r["procurement_id"]) for r in opp_rows})
        src_rows = query(crm, """
            SELECT id AS procurement_id, source_table, source_id, contract_number,
                   crm_stage, award_status, source_status, auction_name, okpd_code, okpd_name,
                   initial_price, crm_category
              FROM crm_procurements WHERE id = ANY(%s)
        """, (pids,))
        updated, audit = compute_opportunity_lifecycle_updates(
            source_procurements=src_rows, opportunities=opp_rows,
        )
        src_by_pid = {int(r["procurement_id"]): r for r in src_rows}
        c = Counter()
        c["CURRENT_BEFORE"] = len(opp_rows)
        per_pid_cats: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for r in opp_rows:
            per_pid_cats[int(r["procurement_id"])].append(r)
        for before, after in zip(opp_rows, updated):
            st = (after.get("commercial_state") or "").upper()
            if st in INACTIVE_STATES:
                c["BECOME_SUPERSEDED"] += 1
            else:
                c["KEEP_CURRENT"] += 1
        c["CURRENT_AFTER"] = c["KEEP_CURRENT"]

        # post-rebuild checks
        for r in opp_rows:
            src = src_by_pid.get(int(r["procurement_id"]), {})
            cat = r["commercial_category_code"]
            track = "DIRECT" if cat in DIRECT_CATS else "EMBEDDED"
            award = (src.get("award_status") or "").lower()
            stage = (src.get("crm_stage") or "").lower()
            state_after = next((a.get("commercial_state") for a in updated if a.get("id") == r["id"]), None)
            if track == "DIRECT" and (award == "awarded" or stage == "razygranye") \
               and (state_after or "").upper() not in INACTIVE_STATES:
                c["AWARDED_DIRECT_ACTIVE_AFTER"] += 1
            ip, ev = src.get("initial_price"), r.get("expected_category_value")
            if ip is not None and ev is not None and float(ev) == float(ip):
                siblings = per_pid_cats[int(r["procurement_id"])]
                subject = src.get("crm_category")
                if track == "DIRECT" and len(siblings) == 1 and (not subject or subject == cat):
                    c["LEGITIMATE_DIRECT_NMCK"] += 1
                elif track == "DIRECT":
                    c["DIRECT_MULTI_CATEGORY_FULL_NMCK_DUPLICATION"] += 1
                    c["PROJECT_OBJECT_NMCK_LEAK"] += 1
                else:
                    c["EMBEDDED_NMCK_LEAK"] += 1
                    c["PROJECT_OBJECT_NMCK_LEAK"] += 1
        # NEW_CURRENT candidates: source procurements that look actionable but have
        # no CURRENT opportunity (materialising them needs the admission producer).
        cand = query(crm, """
            SELECT count(*) AS c FROM crm_procurements p
             WHERE NOT EXISTS (SELECT 1 FROM crm_procurement_category_opportunities o
                                WHERE o.procurement_id = p.id AND o.status = 'CURRENT')
               AND lower(coalesce(p.award_status,'')) NOT IN ('awarded')
               AND lower(coalesce(p.crm_stage,'')) NOT IN ('razygranye','commission')
        """)[0]["c"]
        c["NEW_CURRENT_CANDIDATES"] = cand

        print(f"CURRENT_BEFORE={c['CURRENT_BEFORE']}")
        print(f"KEEP_CURRENT={c['KEEP_CURRENT']}")
        print(f"BECOME_SUPERSEDED={c['BECOME_SUPERSEDED']}")
        print(f"NEW_CURRENT={c['NEW_CURRENT_CANDIDATES']}   (candidate source rows; materialisation = admission producer)")
        print(f"CURRENT_AFTER={c['CURRENT_AFTER']}")
        print(f"AWARDED_DIRECT_ACTIVE_AFTER={c['AWARDED_DIRECT_ACTIVE_AFTER']}")
        print(f"PROJECT_OBJECT_NMCK_LEAK={c['PROJECT_OBJECT_NMCK_LEAK']}")
        print(f"EMBEDDED_NMCK_LEAK={c['EMBEDDED_NMCK_LEAK']}")
        print(f"DIRECT_MULTI_CATEGORY_FULL_NMCK_DUPLICATION={c['DIRECT_MULTI_CATEGORY_FULL_NMCK_DUPLICATION']}")
        print(f"LEGITIMATE_DIRECT_NMCK={c['LEGITIMATE_DIRECT_NMCK']}")
        print(f"LIFECYCLE_TRANSITIONS={len(audit)}")
        return 0
    finally:
        crm.close()


if __name__ == "__main__":
    raise SystemExit(main())
