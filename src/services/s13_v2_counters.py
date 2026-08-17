"""
S13V2 counters: read file/match/evidence counts from document_intelligence.

Returns counts separately from legacy counters.
Never mixed/summed with legacy automatically.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import psycopg2
import psycopg2.extras

PIPELINE_GENERATION = "S13_V2"


def _doc_dsn() -> Dict[str, Any]:
    return {
        "host":     os.getenv("S13_DOCUMENT_DB_HOST", "localhost"),
        "port":     int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname":   os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user":     os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }


def get_s13_v2_counters(procurement_id: int) -> Optional[Dict[str, Any]]:
    """
    Return S13_V2 file/match/evidence counters for one procurement.
    Returns None if document_intelligence is unreachable.

    Example result:
    {
        "pipeline": "S13_V2",
        "queue_status": "COMPLETED",
        "file_count": 3,
        "match_count": 2,
        "detail_count": 147,
        "evidence_count": 1,
        "next_stage": "STRUCTURED_EXTRACTION_PENDING",
        "worker_id": 17,
        "completed_at": "2026-08-09T21:15:00+03:00"
    }
    """
    try:
        conn = psycopg2.connect(**_doc_dsn())
        conn.autocommit = True
    except Exception:
        return None

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Queue entry
            cur.execute(
                """SELECT id, status, worker_id, research_action,
                          research_depth, started_at, completed_at
                   FROM document_processing_queue
                   WHERE procurement_id = %s AND pipeline_generation = %s
                   ORDER BY id DESC LIMIT 1""",
                (procurement_id, PIPELINE_GENERATION),
            )
            q = cur.fetchone()
            if not q:
                return {
                    "pipeline": PIPELINE_GENERATION,
                    "queue_status": "NOT_QUEUED",
                    "file_count": 0,
                    "match_count": 0,
                    "detail_count": 0,
                    "evidence_count": 0,
                }

            queue_id = q["id"]

            # File count
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM document_files"
                " WHERE procurement_id=%s AND pipeline_generation=%s",
                (procurement_id, PIPELINE_GENERATION),
            )
            file_count = cur.fetchone()["cnt"]

            # Match count
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM document_matches"
                " WHERE procurement_id=%s AND pipeline_generation=%s",
                (procurement_id, PIPELINE_GENERATION),
            )
            match_count = cur.fetchone()["cnt"]

            # Detail count
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM document_match_details"
                " WHERE procurement_id=%s AND pipeline_generation=%s",
                (procurement_id, PIPELINE_GENERATION),
            )
            detail_count = cur.fetchone()["cnt"]

            # Evidence
            cur.execute(
                """SELECT COUNT(*) AS cnt,
                          MAX(next_stage) AS next_stage
                   FROM document_evidence
                   WHERE procurement_id=%s AND pipeline_generation=%s""",
                (procurement_id, PIPELINE_GENERATION),
            )
            ev = cur.fetchone()
            evidence_count = ev["cnt"]
            next_stage = ev["next_stage"]

        return {
            "pipeline":      PIPELINE_GENERATION,
            "queue_id":      queue_id,
            "queue_status":  q["status"],
            "worker_id":     q["worker_id"],
            "research_action": q["research_action"],
            "research_depth":  q["research_depth"],
            "started_at":    q["started_at"].isoformat() if q["started_at"] else None,
            "completed_at":  q["completed_at"].isoformat() if q["completed_at"] else None,
            "file_count":    int(file_count),
            "match_count":   int(match_count),
            "detail_count":  int(detail_count),
            "evidence_count":int(evidence_count),
            "next_stage":    next_stage,
        }
    finally:
        conn.close()
