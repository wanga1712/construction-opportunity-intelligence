#!/bin/bash
python3 << 'PYEOF'
filepath = '/opt/CRM_Streamlit/tender_documents_research/document_processor/backends/s13_results.py'

new_code = '''"""
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
        """Write a task-level summary row to document_processing_results.

        Matches the actual columns of the table in document_intelligence DB.
        """
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                # 1. Fetch actual pipeline_generation and correct crm_pid
                cur.execute("""
                    SELECT pipeline_generation, procurement_id FROM document_processing_queue
                    WHERE id = %s OR procurement_id = %s
                    ORDER BY (status = 'PROCESSING') DESC, id DESC
                    LIMIT 1
                """, (queue_id, procurement_id))
                q_row = cur.fetchone()
                pipeline_gen = q_row[0] if q_row else "S13_V2"
                crm_pid = q_row[1] if q_row else procurement_id

                # 2. Insert summary row (where file_id is NULL)
                cur.execute(
                    """
                    INSERT INTO document_processing_results (
                        queue_id,
                        procurement_id,
                        status,
                        matches_found,
                        worker_id,
                        pipeline_generation,
                        created_at,
                        completed_at
                    ) VALUES (
                        %(queue_id)s,
                        %(procurement_id)s,
                        'COMPLETED',
                        %(matches_found)s,
                        %(worker_id)s,
                        %(pipeline_generation)s,
                        NOW(),
                        NOW()
                    )
                    """,
                    {
                        "queue_id": queue_id,
                        "procurement_id": crm_pid,
                        "matches_found": match_count,
                        "worker_id": worker_id,
                        "pipeline_generation": pipeline_gen,
                    },
                )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            # Fail-soft: result store is best-effort (queue.mark_completed is the authoritative signal)
            print(f"[S13ResultStore] persist_evidence failed: {exc}", flush=True)
'''

with open(filepath, 'w') as f:
    f.write(new_code)
print("SUCCESS: s13_results.py fully updated.")
PYEOF

python3 -m py_compile /opt/CRM_Streamlit/tender_documents_research/document_processor/backends/s13_results.py && echo "SYNTAX_OK"
