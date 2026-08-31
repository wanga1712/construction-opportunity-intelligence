"""
document_processor/backends/s13_results.py

S13V2 result backend: persist parse/match/evidence to document_intelligence.
All credentials from env (S13_DOCUMENT_DB_* vars).
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
import psycopg2.extensions

PIPELINE_S13V2 = "S13_V2"


class S13V2ResultStore:
    """Write document processing artifacts to document_intelligence DB."""

    def __init__(self, dsn: Dict[str, Any], pipeline_generation: str = "S13_V2") -> None:
        self._dsn = dsn
        self._conn: Optional[psycopg2.extensions.connection] = None
        self.pipeline_generation = pipeline_generation

    def _get_conn(self) -> psycopg2.extensions.connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self._dsn)
            self._conn.autocommit = False
        return self._conn

    def _commit(self) -> None:
        self._get_conn().commit()

    def persist_file(self, *, queue_id: int, procurement_id: int,
                     source_table: str, url: str, file_name: str,
                     worker_id: int) -> int:
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:64]
        sql = """
            INSERT INTO document_files
                (queue_id, procurement_id, source_table, url, url_hash,
                 file_name, download_status, pipeline_generation, worker_id)
            VALUES (%s, %s, %s, %s, %s, %s, 'PENDING', %s, %s)
            ON CONFLICT (url_hash, pipeline_generation)
                DO UPDATE SET queue_id=EXCLUDED.queue_id,
                              procurement_id=EXCLUDED.procurement_id
            RETURNING id
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(sql, (queue_id, procurement_id, source_table,
                               url, url_hash, file_name, self.pipeline_generation, worker_id))
            row = cur.fetchone()
        self._commit()
        return row[0]

    def update_file_downloaded(self, file_id: int, local_path: str,
                                size_bytes: int, content_type: str = "") -> None:
        sql = """
            UPDATE document_files
               SET download_status='COMPLETED', local_path=%s,
                   file_size_bytes=%s, content_type=%s, downloaded_at=NOW()
             WHERE id=%s
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(sql, (local_path, size_bytes, content_type, file_id))
        self._commit()

    def persist_result(self, *, queue_id: int, file_id: int,
                       procurement_id: int, worker_id: int) -> int:
        sql = """
            INSERT INTO document_processing_results
                (queue_id, file_id, procurement_id, worker_id,
                 status, pipeline_generation)
            VALUES (%s, %s, %s, %s, 'PENDING', %s)
            RETURNING id
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(sql, (queue_id, file_id, procurement_id, worker_id, self.pipeline_generation))
            row = cur.fetchone()
        self._commit()
        return row[0]

    def update_result(self, result_id: int, *, pages: int = 0, sheets: int = 0,
                      rows: int = 0, matches: int = 0) -> None:
        sql = """
            UPDATE document_processing_results
               SET status='COMPLETED', pages_processed=%s, sheets_processed=%s,
                   rows_extracted=%s, matches_found=%s, completed_at=NOW()
             WHERE id=%s
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(sql, (pages, sheets, rows, matches, result_id))
        self._commit()

    def persist_match(self, *, queue_id: int, file_id: int, result_id: int,
                      procurement_id: int, source_table: str, document_name: str,
                      match_count: int, score: float, worker_id: int) -> int:
        sql = """
            INSERT INTO document_matches
                (queue_id, file_id, result_id, procurement_id, source_table,
                 document_name, match_count, score, worker_id, pipeline_generation)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(sql, (queue_id, file_id, result_id, procurement_id,
                               source_table, document_name, match_count,
                               score, worker_id, self.pipeline_generation))
            row = cur.fetchone()
        self._commit()
        return row[0]

    def persist_details(self, match_id: int, details: List[Dict[str, Any]]) -> int:
        if not details:
            return 0
        sql = """
            INSERT INTO document_match_details
                (match_id, procurement_id, category_code, subcategory_code,
                 matched_term, term_type, score, row_data,
                 page_or_sheet, row_number, worker_id, pipeline_generation)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        rows = [
            (match_id, d.get("procurement_id"),
             d.get("category_code", ""), d.get("subcategory_code", ""),
             d.get("matched_term", ""), d.get("term_type", "keyword"),
             d.get("score", 0.0), psycopg2.extras.Json(d.get("row_data") or {}),
             d.get("page_or_sheet", ""), d.get("row_number", 0),
             d.get("worker_id", 0), self.pipeline_generation)
            for d in details
        ]
        conn = self._get_conn()
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, sql, rows, page_size=200)
        self._commit()
        return len(rows)

    def persist_evidence(self, *, procurement_id: int, queue_id: int,
                         match_id: int, category_code: str, evidence_score: float,
                         match_count: int, worker_id: int,
                         next_stage: str = "STRUCTURED_EXTRACTION_PENDING") -> None:
        sql = """
            INSERT INTO document_evidence
                (procurement_id, queue_id, match_id, category_code,
                 evidence_score, match_count, next_stage, worker_id,
                 pipeline_generation)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (procurement_id, category_code, pipeline_generation)
                DO UPDATE SET
                    evidence_score = GREATEST(EXCLUDED.evidence_score,
                                              document_evidence.evidence_score),
                    match_count = document_evidence.match_count + EXCLUDED.match_count,
                    next_stage  = EXCLUDED.next_stage,
                    worker_id   = EXCLUDED.worker_id
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(sql, (procurement_id, queue_id, match_id, category_code,
                               evidence_score, match_count, next_stage,
                               worker_id, self.pipeline_generation))
        self._commit()
