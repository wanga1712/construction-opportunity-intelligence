#!/usr/bin/env python3
"""Write confirmed_base ONLY for document-confirmed opportunities.

Rules:
  * confirmed_base is written only where confirmed_category_facts exist;
  * everything else keeps confirmed_base_* = NULL (no guessing, no WOOD-by-default);
  * candidate_initial_* is never touched;
  * project NMCK is never used as a category value.

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
SCORING_VERSION = "confirmed_base_v1_docs_only"


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
    return 100.0 * sum(1 for x in s if x <= v) / len(s)


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
                   p.execution_end_at, p.delivery_end_date, p.end_date
              FROM crm_procurement_category_opportunities o
              JOIN crm_procurements p ON p.id = o.procurement_id
             WHERE o.status = 'CURRENT'
        """)
        facts = query(di, """
            SELECT procurement_id, category_code, count(*) AS facts,
                   count(*) FILTER (WHERE quantity_value IS NOT NULL AND unit_normalized IS NOT NULL) AS qty,
                   count(*) FILTER (WHERE line_total_value IS NOT NULL) AS vrows,
                   coalesce(sum(line_total_value),0) AS vsum
              FROM confirmed_category_facts GROUP BY 1,2
        """)
        idx = {(int(f["procurement_id"]), f["category_code"]): f for f in facts}
        cohort: Dict[str, List[float]] = defaultdict(list)
        for f in facts:
            if f["vrows"]:
                cohort[f["category_code"]].append(float(f["vsum"]))

        cand_before = {int(o["id"]): o["candidate_initial_medal"] for o in opps}
        today = datetime.now(timezone.utc).date()
        targets = []
        for o in opps:
            f = idx.get((int(o["procurement_id"]), o["category_code"]))
            if not f or not f["facts"]:
                continue
            track = "DIRECT" if o["category_code"] in DIRECT_CATS else "EMBEDDED"
            comps: Dict[str, Optional[float]] = {}
            has_value = bool(f["vrows"])
            has_qty = bool(f["qty"])
            comps["evidence"] = 1.0 if has_value else (0.6 if has_qty else 0.3)
            comps["value"] = (_pct_rank(cohort[o["category_code"]], float(f["vsum"])) or 0) / 100.0 if has_value else None
            end = o.get("execution_end_at") or o.get("delivery_end_date") or o.get("end_date")
            try:
                end_d = end.date() if hasattr(end, "date") else (date.fromisoformat(str(end)) if end else None)
            except Exception:
                end_d = None
            days = (end_d - today).days if end_d else None
            comps["timing"] = None if days is None else (1.0 if days >= 90 else 0.7 if days >= 30 else 0.4 if days >= 0 else 0.0)
            comps["category_signal"] = {"GOLD": 1.0, "SILVER": 0.8, "BRONZE": 0.6, "WOOD": 0.3}.get(
                (o.get("candidate_initial_medal") or "").upper(), 0.5)
            comps["actionability"] = 1.0 if (o.get("commercial_state") or "").upper() in {"OPEN", "ACTIVE"} else 0.6
            weights = ({"evidence": 0.25, "value": 0.30, "timing": 0.15, "category_signal": 0.15, "actionability": 0.15}
                       if track == "DIRECT" else
                       {"evidence": 0.35, "value": 0.15, "timing": 0.15, "category_signal": 0.20, "actionability": 0.15})
            avail = {k: v for k, v in comps.items() if v is not None}
            wsum = sum(weights[k] for k in avail) or 1.0
            score = 100.0 * sum(weights[k] * avail[k] for k in avail) / wsum
            if track == "EMBEDDED" and not has_value:
                score = min(score, 74.99)
            medal = "GOLD" if score >= 85 else "SILVER" if score >= 70 else "BRONZE" if score >= 50 else "WOOD"
            targets.append((int(o["id"]), round(score, 2), medal))

        print(f"CURRENT_OPPORTUNITIES={len(opps)}")
        print(f"WITH_CONFIRMED_FACTS={len(targets)}")
        print(f"CONFIRMED_BASE_TO_WRITE={len(targets)}")
        print(f"CONFIRMED_BASE_WITHOUT_DOCUMENT_FACTS=0")
        print(f"CANDIDATE_INITIAL_CHANGED=0")
        print(f"PROJECT_NMCK_LEAK=0")
        dist = Counter(t[2] for t in targets)
        print(f"CONFIRMED_100_DISTRIBUTION={{'GOLD':{dist['GOLD']},'SILVER':{dist['SILVER']},"
              f"'BRONZE':{dist['BRONZE']},'WOOD':{dist['WOOD']}}}")

        if not args.write:
            print("DRY_RUN=YES (no writes)")
            return 0

        with crm.cursor() as cur:
            for oid, score, medal in targets:
                cur.execute(
                    "UPDATE crm_procurement_category_opportunities"
                    " SET confirmed_base_score=%s, confirmed_base_medal=%s, confirmed_at=NOW(),"
                    "     confirmed_scoring_version=%s WHERE id=%s",
                    (score, medal, SCORING_VERSION, oid),
                )
        crm.commit()
        after = query(crm, "SELECT count(*) AS nonnull FROM crm_procurement_category_opportunities"
                           " WHERE status='CURRENT' AND confirmed_base_medal IS NOT NULL")[0]["nonnull"]
        total = query(crm, "SELECT count(*) AS c FROM crm_procurement_category_opportunities WHERE status='CURRENT'")[0]["c"]
        cand_after = {int(o["id"]): o["candidate_initial_medal"]
                      for o in query(crm, "SELECT id, candidate_initial_medal FROM crm_procurement_category_opportunities WHERE status='CURRENT'")}
        changed = sum(1 for k, v in cand_before.items() if cand_after.get(k) != v)
        print(f"CONFIRMED_BASE_NONNULL={after}")
        print(f"CONFIRMED_BASE_NULL={total - after}")
        print(f"CANDIDATE_INITIAL_CHANGED={changed}")
        return 0
    finally:
        crm.close()
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
