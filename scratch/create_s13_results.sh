#!/bin/bash
cat > /opt/CRM_Streamlit/tender_documents_research/document_processor/backends/s13_results.py << 'PYEOF'
"""
document_processor/backends/s13_results.py

S13 V2 result store: persists processed evidence records to
document_processing_results table in document_intelligence DB.

PIPELINE_GENERATION = S13_V3_EXHAUSTIVE_CONTEXT (or S13_V2 for legacy queue items).
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import psycopg2
import psycopg2.extras


class S13V2ResultStore:
    """Persist document processing results to document_intelligence DB."""

    def __init__(self, dsn: Dict[str, Any]) -> None:
        self._dsn = dsn
        self._conn: Optional[Any] = None

    def _get_conn(self) -> Any:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self._dsn)
        return self._conn

    def persist_evidence(
        self,
        *,
        procurement_id: int,
        queue_id: int,
        match_id: int,
        category_code: str,
        evidence_score: float,
        match_count: int,
        worker_id: int,
        next_stage: str = "STRUCTURED_EXTRACTION_PENDING",
    ) -> None:
        """Write a document processing result row to document_processing_results.

        If the table doesn't exist, logs warning and returns (fail-soft).
        """
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO document_processing_results (
                        queue_id,
                        procurement_id,
                        match_id,
                        category_code,
                        evidence_score,
                        match_count,
                        worker_id,
                        next_stage,
                        processed_at
                    ) VALUES (
                        %(queue_id)s,
                        %(procurement_id)s,
                        %(match_id)s,
                        %(category_code)s,
                        %(evidence_score)s,
                        %(match_count)s,
                        %(worker_id)s,
                        %(next_stage)s,
                        NOW()
                    )
                    ON CONFLICT (queue_id) DO UPDATE SET
                        evidence_score = EXCLUDED.evidence_score,
                        match_count = EXCLUDED.match_count,
                        next_stage = EXCLUDED.next_stage,
                        processed_at = NOW()
                    """,
                    {
                        "queue_id": queue_id,
                        "procurement_id": procurement_id,
                        "match_id": match_id,
                        "category_code": category_code,
                        "evidence_score": evidence_score,
                        "match_count": match_count,
                        "worker_id": worker_id,
                        "next_stage": next_stage,
                    },
                )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            # Fail-soft: result store is best-effort (queue.mark_completed is the authoritative signal)
            print(f"[S13ResultStore] persist_evidence failed: {exc}", flush=True)
PYEOF

echo "CREATED s13_results.py"
python3 -m py_compile /opt/CRM_Streamlit/tender_documents_research/document_processor/backends/s13_results.py && echo "SYNTAX_OK"
