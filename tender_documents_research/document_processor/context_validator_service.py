"""Asynchronous worker service for document match context validation.

Claims raw candidate matches, validates them with ContextValidator, updates
validation status in document_match_details, and rebuilds document_evidence
for affected procurements.

Fail-closed:
- Only CONFIRMED details can produce positive document_evidence.
- Qwen outages do not break document processing (candidates remain UNKNOWN).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from document_processor.context_validator import ContextValidator

load_dotenv("/opt/CRM_Streamlit/.env")

logger = logging.getLogger("document_processor.context_validator_service")
PIPELINE_GENERATION = "S13_V4_EXHAUSTIVE_CONTEXT"


def get_doc_db_connection():
    return psycopg2.connect(
        host=os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    )


def claim_unvalidated_candidates(
    conn,
    *,
    batch_size: int = 50,
    target_procurement_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Claims a batch of candidates for validation."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        query = """
            SELECT d.id, d.id as detail_id, d.match_id, d.procurement_id, d.category_code, d.subcategory_code,
                   d.matched_term, d.term_type, d.score, d.row_data, d.page_or_sheet, d.row_number,
                   d.context_before, d.context_after, d.match_method,
                   m.document_name, m.archive_member_path
            FROM document_match_details d
            JOIN document_matches m ON d.match_id = m.id
            WHERE d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR d.validation_status IS NULL
              AND d.pipeline_generation = %s
        """
        params: List[Any] = [PIPELINE_GENERATION]
        if target_procurement_ids:
            query += " AND d.procurement_id = ANY(%s)"
            params.append(target_procurement_ids)

        query += " ORDER BY d.id ASC LIMIT %s FOR UPDATE OF d SKIP LOCKED"
        params.append(batch_size)

        cur.execute(query, tuple(params))
        return cur.fetchall()


def update_candidate_validations(conn, results: List[Dict[str, Any]]) -> Set[Tuple[int, str]]:
    """Updates document_match_details with validation outcomes."""
    affected: Set[Tuple[int, str]] = set()
    if not results:
        return affected

    with conn.cursor() as cur:
        for r in results:
            detail_id = r["detail_id"]
            status = r["decision"]
            method = r.get("validation_method", "QWEN_CONTEXT_V1")
            reason = f"[{r.get('reason_code', 'UNSPECIFIED')}] {r.get('reason', '')}"
            val_name = r.get("validator_name", "context_validator")
            val_ver = r.get("validator_version", "v1")

            cur.execute("""
                UPDATE document_match_details
                SET validation_status = %s,
                    validation_method = %s,
                    validation_reason = %s,
                    validated_at = NOW(),
                    validator_name = %s,
                    validator_version = %s
                WHERE id = %s
            """, (status, method, reason, val_name, val_ver, detail_id))

            affected.add((r["procurement_id"], r["category_code"]))

    conn.commit()
    return affected


def rebuild_affected_evidence(conn, affected: Set[Tuple[int, str]]) -> None:
    """Rebuilds document_evidence ONLY for affected procurement/category pairs."""
    if not affected:
        return

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for pid, cat in affected:
            # Query all CONFIRMED details for this procurement & category
            cur.execute("""
                SELECT d.score, m.queue_id
                FROM document_match_details d
                JOIN document_matches m ON d.match_id = m.id
                WHERE d.procurement_id = %s
                  AND d.category_code = %s
                  AND d.pipeline_generation = %s
                  AND d.validation_status = 'CONFIRMED'
            """, (pid, cat, PIPELINE_GENERATION))
            confirmed_rows = cur.fetchall()

            if confirmed_rows:
                max_score = max(float(r["score"]) for r in confirmed_rows)
                match_count = len(confirmed_rows)
                queue_id = confirmed_rows[0]["queue_id"]

                cur.execute("""
                    INSERT INTO document_evidence
                    (procurement_id, queue_id, category_code, evidence_score, match_count, next_stage, validation_status, validation_version, validation_method, pipeline_generation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (procurement_id, category_code, pipeline_generation)
                    DO UPDATE SET
                        evidence_score = EXCLUDED.evidence_score,
                        match_count = EXCLUDED.match_count,
                        validation_status = 'CONFIRMED',
                        validation_version = 'v1',
                        validation_method = 'QWEN_CONTEXT_V1'
                """, (
                    pid, queue_id, cat, max_score, match_count,
                    "STRUCTURED_EXTRACTION_PENDING", "CONFIRMED", "v1", "QWEN_CONTEXT_V1",
                    PIPELINE_GENERATION
                ))
            else:
                # No confirmed details exist -> demote or delete evidence
                cur.execute("""
                    DELETE FROM document_evidence
                    WHERE procurement_id = %s
                      AND category_code = %s
                      AND pipeline_generation = %s
                """, (pid, cat, PIPELINE_GENERATION))

    conn.commit()


def process_batch(
    conn,
    validator: ContextValidator,
    *,
    batch_size: int = 50,
    target_procurement_ids: Optional[List[int]] = None,
) -> int:
    """Processes a single batch of unvalidated candidates."""
    candidates = claim_unvalidated_candidates(
        conn, batch_size=batch_size, target_procurement_ids=target_procurement_ids
    )
    if not candidates:
        return 0

    results = validator.validate_candidates(candidates)
    affected = update_candidate_validations(conn, results)
    rebuild_affected_evidence(conn, affected)
    return len(results)


def main():
    """Main daemon entrypoint."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger.info("Starting CRM V3 Context Validator Daemon...")

    validator = ContextValidator()
    conn = get_doc_db_connection()

    while True:
        try:
            count = process_batch(conn, validator, batch_size=20)
            if count == 0:
                time.sleep(3.0)
            else:
                logger.info("Validated batch of %d candidates", count)
        except Exception as exc:
            logger.error("Error in validator daemon loop: %s", exc)
            time.sleep(5.0)


if __name__ == "__main__":
    main()
