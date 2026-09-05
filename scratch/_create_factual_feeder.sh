"""Factual Feeder V3 — Headless research pipeline feeder based on factual procurement state.

Admission authority is FACTUAL PROCUREMENT DATA (crm_procurements + canonical documents),
not old AI assessment.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras

from src.services.commercial_routing_v3.document_links import (
    count_document_links,
    resolve_document_links,
)

logger = logging.getLogger("commercial_routing_v3.factual_feeder")

PIPELINE_GENERATION = "S13_V2"
LOW_WATERMARK = 50
HIGH_WATERMARK = 200
FEED_BATCH_SIZE = 25


def _get_doc_db_conn():
    dsn = {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }
    return psycopg2.connect(**dsn)


def compute_md5(data: Any) -> str:
    s = json.dumps(data, sort_keys=True, default=str)
    return hashlib.md5(s.encode("utf-8")).hexdigest()


class FactualFeeder:
    """Headless feeder that admits procurements into document_processing_queue based on factual procurement data."""

    def __init__(self, crm_db: Any) -> None:
        self.crm_db = crm_db

    def get_queue_depth(self) -> int:
        """Get count of active (PENDING / RUNNING / RETRY) tasks in document_processing_queue."""
        conn = _get_doc_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM document_processing_queue WHERE pipeline_generation = %s AND status IN ('PENDING', 'RUNNING', 'RETRY')",
                    (PIPELINE_GENERATION,),
                )
                res = cur.fetchone()
                return int(res[0]) if res else 0
        finally:
            conn.close()

    def load_factual_candidates(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch candidate procurements directly from crm_procurements (44-ФЗ and 223-ФЗ) based on factual state."""
        sql = """
            SELECT DISTINCT ON (p.id) p.id, p.source_table, p.source_id, p.contract_number, p.updated_at
            FROM crm_procurements p
            WHERE p.source_table IN ('reestr_contract_44_fz', 'reestr_contract_223_fz')
            ORDER BY p.id DESC, p.updated_at DESC NULLS LAST
            LIMIT %s
        """
        rows = self.crm_db.execute_query(sql, (limit,)) or []
        return [dict(r) for r in rows]

    def admit_procurement(self, proc: Dict[str, Any]) -> Dict[str, Any]:
        """Check factual admission and enqueue into document_processing_queue if canonical documents exist."""
        procurement_id = proc["id"]
        source_table = proc.get("source_table") or ""
        source_id = proc.get("source_id")
        contract_number = proc.get("contract_number")

        # Resolve canonical document links
        doc_res = resolve_document_links(
            source_table=source_table,
            source_id=source_id,
            contract_number=contract_number,
        )
        links = doc_res.get("links") or []

        if not links:
            return {
                "procurement_id": procurement_id,
                "admitted": False,
                "reason": "NO_CANONICAL_DOCUMENTS",
                "doc_count": 0,
            }

        conn = _get_doc_db_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Check existing queue task
                cur.execute(
                    """
                    SELECT id, status, pipeline_generation
                    FROM document_processing_queue
                    WHERE procurement_id = %s AND pipeline_generation = %s
                    ORDER BY id DESC LIMIT 1
                    """,
                    (procurement_id, PIPELINE_GENERATION),
                )
                row = cur.fetchone()
                if row:
                    st = row.get("status")
                    if st in ("PENDING", "RUNNING", "RETRY", "COMPLETED"):
                        return {
                            "procurement_id": procurement_id,
                            "admitted": False,
                            "reason": f"ALREADY_IN_QUEUE_STATUS_{st}",
                            "doc_count": len(links),
                        }

                # Enqueue factual task
                cur.execute(
                    """
                    INSERT INTO document_processing_queue (
                        procurement_id, source_table, source_id, contract_number,
                        research_action, queue_lane, priority_score, status,
                        pipeline_generation, created_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        'FACTUAL_FEEDER_ADMITTED', 'open_active', 50, 'PENDING',
                        %s, NOW()
                    )
                    RETURNING id
                    """,
                    (
                        procurement_id,
                        source_table,
                        source_id,
                        contract_number,
                        PIPELINE_GENERATION,
                    ),
                )
                new_id = cur.fetchone()["id"]
                conn.commit()

                return {
                    "procurement_id": procurement_id,
                    "admitted": True,
                    "queue_task_id": new_id,
                    "doc_count": len(links),
                }
        finally:
            conn.close()

    def run_feeder_cycle(self) -> Dict[str, Any]:
        """Execute one bounded feeder cycle with watermark checks."""
        current_depth = self.get_queue_depth()
        if current_depth >= HIGH_WATERMARK:
            return {
                "status": "HIGH_WATERMARK_REACHED",
                "queue_depth": current_depth,
                "admitted_count": 0,
            }

        candidates = self.load_factual_candidates(limit=FEED_BATCH_SIZE * 2)
        admitted = 0
        results = []

        for cand in candidates:
            if current_depth + admitted >= HIGH_WATERMARK:
                break
            res = self.admit_procurement(cand)
            if res.get("admitted"):
                admitted += 1
            results.append(res)

        return {
            "status": "CYCLE_COMPLETED",
            "queue_depth_before": current_depth,
            "admitted_count": admitted,
            "queue_depth_after": self.get_queue_depth(),
            "results": results,
        }
