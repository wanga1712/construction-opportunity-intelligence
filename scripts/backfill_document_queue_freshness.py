#!/usr/bin/env python3
"""Backfill source_start_date/work_tier for currently claimable queue rows."""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.commercial_routing_v3.claim_freshness import compute_work_tier

load_dotenv(ROOT / ".env")


def _doc_dsn() -> dict:
    return {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }


def _crm_dsn() -> dict:
    return {
        "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("CRM_DB_PORT", "5432")),
        "dbname": os.getenv("CRM_DB_DATABASE") or os.getenv("CRM_DB_NAME") or "crm",
        "user": os.getenv("CRM_DB_USER", "crm_app"),
        "password": os.getenv("CRM_DB_PASSWORD", ""),
    }


def main() -> int:
    doc = psycopg2.connect(**_doc_dsn())
    crm = psycopg2.connect(**_crm_dsn())
    try:
        with doc.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, procurement_id
                  FROM document_processing_queue
                 WHERE status IN ('PENDING', 'PRE_RESEARCH_WAITING')
                   AND (research_action = 'FACTUAL_FEEDER_ADMITTED'
                        OR category_context->>'AI_QUEUE_ADMISSION_GATE' = 'YES')
                   AND COALESCE(category_context->>'legacy_revalidation_status','')
                       NOT IN ('REQUIRED', 'LEGACY_HOLD')
                """
            )
            rows: List[Dict[str, Any]] = [dict(r) for r in cur.fetchall()]
        pids = sorted({int(r["procurement_id"]) for r in rows if r.get("procurement_id")})
        procs: Dict[int, Dict[str, Any]] = {}
        if pids:
            with crm.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, start_date, end_date, crm_stage, award_status
                      FROM crm_procurements
                     WHERE id = ANY(%s)
                    """,
                    (pids,),
                )
                procs = {int(r["id"]): dict(r) for r in cur.fetchall()}
        updated = 0
        with doc.cursor() as cur:
            for row in rows:
                proc = procs.get(int(row["procurement_id"])) or {}
                start = proc.get("start_date")
                tier = compute_work_tier(proc)
                cur.execute(
                    """
                    UPDATE document_processing_queue
                       SET source_start_date = %s,
                           work_tier = %s
                     WHERE id = %s
                    """,
                    (start, tier, row["id"]),
                )
                updated += cur.rowcount
        doc.commit()
        print(f"ROWS={len(rows)}")
        print(f"UPDATED={updated}")
        print(f"TIER_0={sum(1 for r in rows if compute_work_tier(procs.get(int(r['procurement_id'])) or {}) == 0)}")
        print(f"TIER_1={sum(1 for r in rows if compute_work_tier(procs.get(int(r['procurement_id'])) or {}) == 1)}")
        print(f"TIER_2={sum(1 for r in rows if compute_work_tier(procs.get(int(r['procurement_id'])) or {}) == 2)}")
    finally:
        doc.close()
        crm.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
