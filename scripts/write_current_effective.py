#!/usr/bin/env python3
"""Compute/write current_effective from confirmed_base (fallback candidate_initial).

base = confirmed_base_medal if present else candidate_initial_medal
then only actual factors apply: lifecycle/timing, research-priority cap,
current commercial state. Missing confirmed_base is NOT WOOD; missing documents
are NOT "confirmed". candidate_initial is immutable; confirmed_base is not
recomputed here.

Default: dry-run. Use --write to apply.
"""

from __future__ import annotations

import argparse
import os
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DIRECT_CATS = {"computers", "lighting", "cable_support_systems"}
ORDER = ["WOOD", "BRONZE", "SILVER", "GOLD"]
SCORING_VERSION = "current_effective_v1"


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


def _down(medal: str, steps: int) -> str:
    if medal not in ORDER or steps <= 0:
        return medal
    return ORDER[max(0, ORDER.index(medal) - steps)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    crm = psycopg2.connect(**crm_dsn())
    di = psycopg2.connect(**di_dsn())
    try:
        opps = query(crm, """
            SELECT o.id, o.procurement_id, o.commercial_category_code AS category_code,
                   o.opportunity_track, o.commercial_state, o.candidate_initial_medal,
                   o.confirmed_base_medal,
                   p.execution_end_at, p.delivery_end_date, p.end_date
              FROM crm_procurement_category_opportunities o
              JOIN crm_procurements p ON p.id = o.procurement_id
             WHERE o.status = 'CURRENT'
        """)
        facts = query(di, """
            SELECT procurement_id, category_code, count(*) AS vrows
              FROM confirmed_category_facts GROUP BY 1,2
        """)
        has_value = {(int(f["procurement_id"]), f["category_code"]) for f in facts if f["vrows"]}
        before = {int(o["id"]): (o["candidate_initial_medal"], o["confirmed_base_medal"]) for o in opps}
        today = datetime.now(timezone.utc).date()

        c = Counter()
        by = defaultdict(Counter)
        examples = []
        plan = []
        for o in opps:
            oid = int(o["id"])
            cat = o["category_code"]
            track = "DIRECT" if cat in DIRECT_CATS else "EMBEDDED"
            cand = (o["candidate_initial_medal"] or "").upper() or None
            conf = (o["confirmed_base_medal"] or "").upper() or None
            base = conf or cand
            using = "CONFIRMED_BASE" if conf else ("CANDIDATE_INITIAL" if cand else None)
            if using == "CONFIRMED_BASE":
                c["USING_CONFIRMED_BASE"] += 1
            elif using == "CANDIDATE_INITIAL":
                c["USING_CANDIDATE_INITIAL"] += 1
            if base is None:
                c["CURRENT_EFFECTIVE_NULL"] += 1
                continue
            reason = []
            medal = base
            # research cap: EMBEDDED without verified value cannot exceed SILVER
            if track == "EMBEDDED" and (int(o["procurement_id"]), cat) not in has_value and ORDER.index(medal) > ORDER.index("SILVER"):
                medal = "SILVER"
                c["RESEARCH_CAP_APPLIED"] += 1
                reason.append("RESEARCH_CAP_SILVER")
            # timing / lifecycle downgrade
            end = o.get("execution_end_at") or o.get("delivery_end_date") or o.get("end_date")
            try:
                end_d = end.date() if hasattr(end, "date") else (date.fromisoformat(str(end)) if end else None)
            except Exception:
                end_d = None
            terminal = (o.get("commercial_state") or "").upper() in {"CLOSED", "ARCHIVED", "FOLLOW_UP_AWARDED", "TERMINAL"}
            overdue = bool(end_d and end_d < today)
            steps = 1 if (terminal or overdue) else 0
            if steps:
                new_medal = _down(medal, steps)
                if new_medal != medal:
                    c["TIMING_DOWNGRADES"] += 1
                    reason.append("TIMING_OR_LIFECYCLE_DOWNGRADE")
                    medal = new_medal
            if conf and medal != conf:
                c["CONFIRMED_BASE_OVERRIDES"] += 1
            c[f"EFF_{medal}"] += 1
            by[track][medal] += 1
            plan.append((oid, medal, "|".join(reason) or "BASE"))
            if len(examples) < 15 and (conf or cand in {"GOLD", "SILVER"}):
                examples.append((oid, o["procurement_id"], cat, track, cand, conf, medal, "|".join(reason) or "BASE"))

        print(f"CURRENT_TOTAL={len(opps)}")
        print(f"USING_CONFIRMED_BASE={c['USING_CONFIRMED_BASE']}")
        print(f"USING_CANDIDATE_INITIAL={c['USING_CANDIDATE_INITIAL']}")
        print(f"CURRENT_EFFECTIVE_GOLD={c['EFF_GOLD']}")
        print(f"CURRENT_EFFECTIVE_SILVER={c['EFF_SILVER']}")
        print(f"CURRENT_EFFECTIVE_BRONZE={c['EFF_BRONZE']}")
        print(f"CURRENT_EFFECTIVE_WOOD={c['EFF_WOOD']}")
        print(f"CURRENT_EFFECTIVE_NULL={c['CURRENT_EFFECTIVE_NULL']}")
        print(f"CONFIRMED_BASE_OVERRIDES={c['CONFIRMED_BASE_OVERRIDES']}")
        print(f"TIMING_DOWNGRADES={c['TIMING_DOWNGRADES']}")
        print(f"RESEARCH_CAP_APPLIED={c['RESEARCH_CAP_APPLIED']}")
        for tr in sorted(by):
            print(f"BY_TRACK[{tr}]={dict(by[tr])}")
        print("-" * 78)
        print("TRANSITIONS candidate_initial -> confirmed_base -> current_effective")
        for oid, pid, cat, track, cand, conf, medal, reason in examples:
            print(f"  id={oid} pid={pid} {cat} [{track}] {cand} -> {conf or 'NULL'} -> {medal} ({reason})")

        if not args.write:
            print("DRY_RUN=YES (no writes)")
            return 0
        with crm.cursor() as cur:
            for oid, medal, reason in plan:
                cur.execute(
                    "UPDATE crm_procurement_category_opportunities"
                    " SET current_effective_medal=%s, current_effective_at=NOW(),"
                    "     current_effective_reason=%s WHERE id=%s",
                    (medal, f"{SCORING_VERSION}:{reason}", oid),
                )
        crm.commit()
        after = {int(o["id"]): (o["candidate_initial_medal"], o["confirmed_base_medal"])
                 for o in query(crm, "SELECT id, candidate_initial_medal, confirmed_base_medal"
                                     " FROM crm_procurement_category_opportunities WHERE status='CURRENT'")}
        print(f"CANDIDATE_INITIAL_CHANGED={sum(1 for k, v in before.items() if after.get(k, (None,))[0] != v[0])}")
        print(f"CONFIRMED_BASE_CHANGED={sum(1 for k, v in before.items() if after.get(k, (None, None))[1] != v[1])}")
        return 0
    finally:
        crm.close()
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
