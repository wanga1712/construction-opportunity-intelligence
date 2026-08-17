"""
ResultRepository abstraction for document processing pipeline.

Two backends:
  LegacyResultRepository  → tender_monitor (SERVER 7)
  S13V2ResultRepository   → document_intelligence (SERVER 13 local)

All connection strings read from env — no hardcoded hosts.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

PIPELINE_S13V2 = "S13_V2"
PIPELINE_LEGACY = "LEGACY"


# ──────────────────────────────────────────────────────────────────────────────
# Data transfer objects (shared between backends)
# ──────────────────────────────────────────────────────────────────────────────

class FileRecord:
    __slots__ = (
        "queue_id", "procurement_id", "source_table", "source_id",
        "url", "url_hash", "file_name", "local_path",
        "file_size_bytes", "content_type", "worker_id",
    )
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class MatchRecord:
    __slots__ = (
        "queue_id", "file_id", "result_id", "procurement_id",
        "source_table", "source_id", "document_name",
        "match_count", "score", "worker_id",
    )
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class DetailRecord:
    __slots__ = (
        "match_id", "procurement_id",
        "category_code", "subcategory_code",
        "matched_term", "term_type", "score",
        "row_data",                     # dict → JSONB
        "page_or_sheet", "row_number",
        "context_before", "context_after",
        "worker_id",
    )
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class EvidenceRecord:
    __slots__ = (
        "procurement_id", "queue_id", "match_id",
        "category_code", "subcategory_code",
        "evidence_score", "match_count",
        "next_stage", "worker_id",
    )
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


# ──────────────────────────────────────────────────────────────────────────────
# Abstract base
# ──────────────────────────────────────────────────────────────────────────────

class ResultRepository(ABC):
    """Interface for persisting document processing results."""

    @abstractmethod
    def persist_file(self, rec: FileRecord) -> int:
        """Upsert file record. Returns file_id."""

    @abstractmethod
    def update_file_downloaded(self, file_id: int, local_path: str,
                               size_bytes: int, content_type: str) -> None:
        """Mark file as downloaded."""

    @abstractmethod
    def persist_result(
        self, queue_id: int, file_id: int, procurement_id: int,
        worker_id: int,
    ) -> int:
        """Create processing result record. Returns result_id."""

    @abstractmethod
    def update_result(
        self, result_id: int, pages: int, sheets: int,
        rows: int, matches: int,
    ) -> None:
        """Update result stats after parse/match."""

    @abstractmethod
    def persist_match(self, rec: MatchRecord) -> int:
        """Insert match record. Returns match_id."""

    @abstractmethod
    def persist_details(self, details: List[DetailRecord]) -> int:
        """Bulk insert detail records. Returns count inserted."""

    @abstractmethod
    def persist_evidence(self, recs: List[EvidenceRecord]) -> int:
        """Upsert evidence records. Returns count upserted."""

    @abstractmethod
    def pipeline_generation(self) -> str:
        """Return pipeline_generation token."""


# ──────────────────────────────────────────────────────────────────────────────
# Legacy backend (tender_monitor + crm on S7)
# ──────────────────────────────────────────────────────────────────────────────

class LegacyResultRepository(ResultRepository):
    """Wraps existing match_repository + crm_observation_store."""

    def __init__(self, db) -> None:
        self._db = db  # DatabaseManager

    def pipeline_generation(self) -> str:
        return PIPELINE_LEGACY

    def persist_file(self, rec: FileRecord) -> int:
        raise NotImplementedError("legacy uses tender_document_matches directly")

    def update_file_downloaded(self, file_id: int, local_path: str,
                               size_bytes: int, content_type: str) -> None:
        raise NotImplementedError("legacy does not track files separately")

    def persist_result(self, queue_id, file_id, procurement_id, worker_id) -> int:
        raise NotImplementedError("legacy uses tender_document_matches directly")

    def update_result(self, result_id, pages, sheets, rows, matches) -> None:
        raise NotImplementedError("legacy uses tender_document_matches directly")

    def persist_match(self, rec: MatchRecord) -> int:
        raise NotImplementedError("use existing match_repository for legacy")

    def persist_details(self, details: List[DetailRecord]) -> int:
        raise NotImplementedError("use existing match_repository for legacy")

    def persist_evidence(self, recs: List[EvidenceRecord]) -> int:
        raise NotImplementedError("use existing crm_observation_store for legacy")


# ──────────────────────────────────────────────────────────────────────────────
# S13_V2 backend (document_intelligence on SERVER 13 local)
# ──────────────────────────────────────────────────────────────────────────────

class S13V2ResultRepository(ResultRepository):
    """Persists all results to local document_intelligence DB on SERVER 13."""

    def __init__(self, dsn: Dict[str, Any]) -> None:
        self._dsn = dsn
        self._conn: Optional[psycopg2.extensions.connection] = None

    def _get_conn(self) -> psycopg2.extensions.connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self._dsn)
            self._conn.autocommit = False
        return self._conn

    def _cur(self):
        return self._get_conn().cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def _commit(self):
        self._get_conn().commit()

    def pipeline_generation(self) -> str:
        return PIPELINE_S13V2

    # ── files ────────────────────────────────────────────────────────────────

    def persist_file(self, rec: FileRecord) -> int:
        sql = """
            INSERT INTO document_files
                (queue_id, procurement_id, source_table, source_id,
                 url, url_hash, file_name, worker_id,
                 download_status, pipeline_generation)
            VALUES (%s,%s,%s,%s, %s,%s,%s,%s, 'PENDING','S13_V2')
            ON CONFLICT (url_hash, pipeline_generation)
            DO UPDATE SET queue_id=EXCLUDED.queue_id,
                          procurement_id=EXCLUDED.procurement_id
            RETURNING id
        """
        with self._cur() as cur:
            cur.execute(sql, (
                rec.queue_id, rec.procurement_id,
                getattr(rec, 'source_table', None),
                getattr(rec, 'source_id', None),
                rec.url, rec.url_hash,
                getattr(rec, 'file_name', None),
                getattr(rec, 'worker_id', None),
            ))
            row = cur.fetchone()
        self._commit()
        return row['id']

    def update_file_downloaded(self, file_id: int, local_path: str,
                               size_bytes: int, content_type: str) -> None:
        with self._cur() as cur:
            cur.execute(
                """UPDATE document_files
                      SET download_status='COMPLETED', local_path=%s,
                          file_size_bytes=%s, content_type=%s,
                          downloaded_at=NOW()
                    WHERE id=%s""",
                (local_path, size_bytes, content_type, file_id),
            )
        self._commit()

    # ── results ──────────────────────────────────────────────────────────────

    def persist_result(self, queue_id: int, file_id: int,
                       procurement_id: int, worker_id: int) -> int:
        with self._cur() as cur:
            cur.execute(
                """INSERT INTO document_processing_results
                       (queue_id, file_id, procurement_id, worker_id,
                        status, pipeline_generation)
                   VALUES (%s,%s,%s,%s,'PENDING','S13_V2')
                   RETURNING id""",
                (queue_id, file_id, procurement_id, worker_id),
            )
            row = cur.fetchone()
        self._commit()
        return row['id']

    def update_result(self, result_id: int, pages: int, sheets: int,
                      rows: int, matches: int) -> None:
        with self._cur() as cur:
            cur.execute(
                """UPDATE document_processing_results
                      SET status='COMPLETED', pages_processed=%s,
                          sheets_processed=%s, rows_extracted=%s,
                          matches_found=%s, completed_at=NOW()
                    WHERE id=%s""",
                (pages, sheets, rows, matches, result_id),
            )
        self._commit()

    # ── matches ───────────────────────────────────────────────────────────────

    def persist_match(self, rec: MatchRecord) -> int:
        with self._cur() as cur:
            cur.execute(
                """INSERT INTO document_matches
                       (queue_id, file_id, result_id, procurement_id,
                        source_table, source_id, document_name,
                        match_count, score, worker_id, pipeline_generation)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'S13_V2')
                   RETURNING id""",
                (
                    rec.queue_id, rec.file_id,
                    getattr(rec, 'result_id', None),
                    rec.procurement_id,
                    getattr(rec, 'source_table', None),
                    getattr(rec, 'source_id', None),
                    getattr(rec, 'document_name', None),
                    rec.match_count,
                    getattr(rec, 'score', None),
                    getattr(rec, 'worker_id', None),
                ),
            )
            row = cur.fetchone()
        self._commit()
        return row['id']

    # ── details (bulk) ────────────────────────────────────────────────────────

    def persist_details(self, details: List[DetailRecord]) -> int:
        if not details:
            return 0
        rows = [
            (
                d.match_id, d.procurement_id,
                getattr(d, 'category_code', None),
                getattr(d, 'subcategory_code', None),
                getattr(d, 'matched_term', None),
                getattr(d, 'term_type', None),
                getattr(d, 'score', None),
                psycopg2.extras.Json(d.row_data) if getattr(d, 'row_data', None) else None,
                getattr(d, 'page_or_sheet', None),
                getattr(d, 'row_number', None),
                psycopg2.extras.Json(d.context_before) if getattr(d, 'context_before', None) else None,
                psycopg2.extras.Json(d.context_after) if getattr(d, 'context_after', None) else None,
                getattr(d, 'worker_id', None),
            )
            for d in details
        ]
        sql = """
            INSERT INTO document_match_details
                (match_id, procurement_id,
                 category_code, subcategory_code,
                 matched_term, term_type, score,
                 row_data, page_or_sheet, row_number,
                 context_before, context_after,
                 worker_id, pipeline_generation)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'S13_V2')
        """
        with self._cur() as cur:
            psycopg2.extras.execute_batch(cur, sql, rows, page_size=200)
        self._commit()
        return len(rows)

    # ── evidence ──────────────────────────────────────────────────────────────

    def persist_evidence(self, recs: List[EvidenceRecord]) -> int:
        if not recs:
            return 0
        count = 0
        sql = """
            INSERT INTO document_evidence
                (procurement_id, queue_id, match_id,
                 category_code, subcategory_code,
                 evidence_score, match_count,
                 next_stage, worker_id, pipeline_generation)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'S13_V2')
            ON CONFLICT (procurement_id, category_code, pipeline_generation)
            DO UPDATE SET
                evidence_score = GREATEST(EXCLUDED.evidence_score,
                                          document_evidence.evidence_score),
                match_count    = document_evidence.match_count + EXCLUDED.match_count,
                next_stage     = EXCLUDED.next_stage,
                worker_id      = EXCLUDED.worker_id
        """
        with self._cur() as cur:
            for r in recs:
                cur.execute(sql, (
                    r.procurement_id,
                    getattr(r, 'queue_id', None),
                    getattr(r, 'match_id', None),
                    r.category_code,
                    getattr(r, 'subcategory_code', None),
                    getattr(r, 'evidence_score', None),
                    getattr(r, 'match_count', 0),
                    getattr(r, 'next_stage', 'STRUCTURED_EXTRACTION_PENDING'),
                    getattr(r, 'worker_id', None),
                ))
                count += 1
        self._commit()
        return count


# ──────────────────────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────────────────────

def build_result_repository(backend: str, db) -> ResultRepository:
    """
    backend: 'S13_V2' or 'LEGACY'.
    db: DatabaseManager (used only for legacy).
    """
    if backend == PIPELINE_S13V2:
        dsn = {
            "host":     os.getenv("S13_DOCUMENT_DB_HOST", "localhost"),
            "port":     int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
            "dbname":   os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
            "user":     os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
            "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
        }
        return S13V2ResultRepository(dsn)
    return LegacyResultRepository(db)
