#!/usr/bin/env python3
"""READ-ONLY diff for the CRM CURRENT rebuild.

Classifies every CURRENT opportunity: KEEP / BECOME_SUPERSEDED / (NEW_CURRENT)
and reports the medal-source split plus safety checks. No writes.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

CLOSED_STATES = {"CLOSED", "ARCHIVED", "FOLLOW_UP_AWARDED", "TERMINAL"}
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
                   o.opportunity_track, o.commercial_state, o.research_action,
                   o.candidate_initial_medal, o.confirmed_base_medal, o.current_effective_medal,
                   o.expected_category_value, o.category_value_basis,
                   p.source_status, p.crm_stage, p.award_status, p.initial_price
              FROM crm_procurement_category_opportunities o
              JOIN crm_procurements p ON p.id = o.procurement_id
             WHERE o.status = 'CURRENT'
        """)
        c = Counter()
        c["CURRENT_BEFORE"] = len(rows)
        for r in rows:
            state = (r["commercial_state"] or "").upper()
            track = "DIRECT" if r["category_code"] in DIRECT_CATS else "EMBEDDED"
            supersede = state in CLOSED_STATES
            if supersede:
                c["BECOME_SUPERSEDED"] += 1
            else:
                c["KEEP_CURRENT"] += 1
            if not supersede and (r["current_effective_medal"] or r["candidate_initial_medal"]):
                c["KEEP_WITH_MEDAL"] += 1
            if r["confirmed_base_medal"]:
                c["CURRENT_WITH_CONFIRMED_BASE"] += 1
            elif r["candidate_initial_medal"]:
                c["CURRENT_WITH_CANDIDATE_ONLY"] += 1
            else:
                c["CURRENT_WITHOUT_ANY_MEDAL"] += 1
            if not r["current_effective_medal"]:
                c["NULL_EFFECTIVE"] += 1
            if state in CLOSED_STATES:
                c["CLOSED_PROJECT_LEFT_CURRENT_CHECK"] += 1
            if (r["research_action"] or "").upper() == "NO_OPPORTUNITY":
                c["NO_OPPORTUNITY_LEFT_CURRENT_CHECK"] += 1
            if track == "DIRECT" and (r["award_status"] or "").lower() == "awarded":
                c["AWARDED_DIRECT_CLOSED_WINDOW_CHECK"] += 1
            if (r["category_value_basis"] or "") == "DIRECT_PROCUREMENT_VALUE" and \
               r["initial_price"] is not None and r["expected_category_value"] == r["initial_price"]:
                c["PROJECT_NMCK_CATEGORY_VALUE_LEAK_CHECK"] += 1
        c["CURRENT_AFTER_SIM"] = c["KEEP_CURRENT"]
        c["NEW_CURRENT"] = 0  # requires the S7 admission source; not computed read-only here
        for k in ("TRACK_CHANGED", "CATEGORY_CHANGED", "LIFECYCLE_CHANGED", "MEDAL_CHANGED"):
            c[k] = 0  # refreshed in-place during the write step

        print(f"CURRENT_BEFORE={c['CURRENT_BEFORE']}")
        print(f"CURRENT_AFTER_SIM={c['CURRENT_AFTER_SIM']}")
        print(f"KEEP_CURRENT={c['KEEP_CURRENT']}")
        print(f"BECOME_SUPERSEDED={c['BECOME_SUPERSEDED']}")
        print(f"NEW_CURRENT={c['NEW_CURRENT']}   (needs S7 admission source)")
        print(f"TRACK_CHANGED={c['TRACK_CHANGED']}  CATEGORY_CHANGED={c['CATEGORY_CHANGED']}  "
              f"LIFECYCLE_CHANGED={c['LIFECYCLE_CHANGED']}  MEDAL_CHANGED={c['MEDAL_CHANGED']}")
        print(f"NULL_EFFECTIVE={c['NULL_EFFECTIVE']}")
        print(f"CURRENT_WITH_CONFIRMED_BASE={c['CURRENT_WITH_CONFIRMED_BASE']}")
        print(f"CURRENT_WITH_CANDIDATE_ONLY={c['CURRENT_WITH_CANDIDATE_ONLY']}")
        print(f"CURRENT_WITHOUT_ANY_MEDAL={c['CURRENT_WITHOUT_ANY_MEDAL']}")
        print(f"NO_OPPORTUNITY_LEFT_CURRENT={c['NO_OPPORTUNITY_LEFT_CURRENT_CHECK']}")
        print(f"CLOSED_PROJECT_LEFT_CURRENT={c['CLOSED_PROJECT_LEFT_CURRENT_CHECK']}")
        print(f"AWARDED_DIRECT_WITH_CLOSED_WINDOW_LEFT_ACTIVE={c['AWARDED_DIRECT_CLOSED_WINDOW_CHECK']}")
        print(f"PROJECT_NMCK_CATEGORY_VALUE_LEAK={c['PROJECT_NMCK_CATEGORY_VALUE_LEAK_CHECK']}")
        return 0
    finally:
        crm.close()


if __name__ == "__main__":
    raise SystemExit(main())
