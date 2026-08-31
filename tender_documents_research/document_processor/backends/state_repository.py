"""Backend-neutral processing and download state adapters."""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from typing import Optional, Tuple

from document_processor.processed_registry import ProcessedRegistry

StatusRow = Tuple[str]


class ProcessingStateRepository(ABC):
    """Small state boundary used by downloader, pipeline and PDF parser."""

    @abstractmethod
    def ensure_download_file(self, queue_id, procurement_id, table_source, url, url_hash, file_name, source_id=None): ...

    @abstractmethod
    def get_file_status(self, procurement_id, table_source, file_name, url_hash): ...

    @abstractmethod
    def mark_file_status(self, procurement_id, table_source, file_name, url_hash, status, worker_id=None): ...

    @abstractmethod
    def finalize_download_status(self, procurement_id, table_source, file_name, url_hash, success, error_message=None, local_path=None): ...

    def record_download_attempt(self, queue_id, procurement_id, source_url, url_hash, attempt_number, result, error_class=None, http_status=None, bytes_received=None, duration_ms=None):
        return None

    @abstractmethod
    def get_processed_status(self, procurement_id, table_source, file_name): ...

    @abstractmethod
    def finalize_processing_status(self, procurement_id, table_source, file_name, is_interesting, error_message=None): ...

    @abstractmethod
    def list_file_statuses(self, procurement_id, table_source, raise_on_error=False): ...

    @abstractmethod
    def get_progress_cursor(self, procurement_id, table_source, file_name): ...

    @abstractmethod
    def set_progress_cursor(self, procurement_id, table_source, file_name, cursor): ...

    @abstractmethod
    def mark_pending_resume(self, procurement_id, table_source, file_name, progress_cursor, error_message=None): ...

    @abstractmethod
    def mark_error_memory(self, procurement_id, table_source, file_name, error_message): ...

    @abstractmethod
    def reset_stale(self, worker_id): ...


class LegacyStateRepository(ProcessingStateRepository):
    """Compatibility adapter around the established S7 ProcessedRegistry."""

    def __init__(self, db, db_alias: str = "tender_monitor"):
        self.logger = logging.getLogger("LegacyStateRepository")
        self.registry = ProcessedRegistry(db, db_alias, self.logger)

    def ensure_download_file(self, queue_id, procurement_id, table_source, url, url_hash, file_name, source_id=None):
        del queue_id, procurement_id, table_source, url, url_hash, file_name, source_id

    def get_file_status(self, procurement_id, table_source, file_name, url_hash):
        del url_hash
        return self.registry.get_processed_status(procurement_id, table_source, file_name)

    def mark_file_status(self, procurement_id, table_source, file_name, url_hash, status, worker_id=None):
        del url_hash, worker_id
        return self.registry.mark_file_status(procurement_id, table_source, file_name, status.lower())

    def finalize_download_status(self, procurement_id, table_source, file_name, url_hash, success, error_message=None, local_path=None):
        del url_hash, local_path
        return self.registry.finalize_file_status(procurement_id, table_source, file_name, success, error_message)

    def get_processed_status(self, procurement_id, table_source, file_name):
        return self.registry.get_processed_status(procurement_id, table_source, file_name)

    def finalize_processing_status(self, procurement_id, table_source, file_name, is_interesting, error_message=None):
        return self.registry.finalize_file_status(procurement_id, table_source, file_name, is_interesting, error_message)

    def list_file_statuses(self, procurement_id, table_source, raise_on_error=False):
        return self.registry.list_file_statuses(procurement_id, table_source, raise_on_error=raise_on_error)

    def get_progress_cursor(self, procurement_id, table_source, file_name):
        return self.registry.get_progress_cursor(procurement_id, table_source, file_name)

    def set_progress_cursor(self, procurement_id, table_source, file_name, cursor):
        return self.registry.set_progress_cursor(procurement_id, table_source, file_name, cursor)

    def mark_pending_resume(self, procurement_id, table_source, file_name, progress_cursor, error_message=None):
        return self.registry.mark_pending_resume(procurement_id, table_source, file_name, progress_cursor, error_message)

    def mark_error_memory(self, procurement_id, table_source, file_name, error_message):
        return self.registry.mark_error_memory(procurement_id, table_source, file_name, error_message)

    def reset_stale(self, worker_id):
        del worker_id
        self.registry.db.execute_query(
            self.registry.db_alias,
            "DELETE FROM processed_documents WHERE status = 'processing'",
        )
        return 0


class S13V2StateRepository(ProcessingStateRepository):
    """Local-only S13_V2 state backed by document_intelligence.document_files."""

    def __init__(self, dsn: dict, pipeline_generation: str = "S13_V2"):
        self._dsn = dsn
        self.pipeline_generation = pipeline_generation
        self.logger = logging.getLogger("S13V2StateRepository")
        self._local = threading.local()
        self._conn = None  # test/backward-compatible single-connection override

    def _get_conn(self):
        import psycopg2

        if self._conn is not None:
            return self._conn
        conn = getattr(self._local, "conn", None)
        if conn is None or conn.closed:
            conn = psycopg2.connect(**self._dsn)
            conn.autocommit = False
            self._local.conn = conn
        return conn

    def _one(self, sql, params):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def ensure_download_file(self, queue_id, procurement_id, table_source, url, url_hash, file_name, source_id=None,
                             canonical_source_document_id=None, physical_download_key=None):
        if procurement_id is None:
            raise RuntimeError("S13 V2/V4 requires a resolved procurement_id before download")
        conn = self._get_conn()
        with conn.cursor() as cur:
            # Check by canonical_source_document_id first
            row = None
            if canonical_source_document_id is not None:
                cur.execute(
                    "SELECT id FROM document_files WHERE canonical_source_document_id=%s AND pipeline_generation=%s LIMIT 1",
                    (canonical_source_document_id, self.pipeline_generation)
                )
                row = cur.fetchone()
            
            # If not found, check by url_hash
            if row is None and url_hash:
                cur.execute(
                    "SELECT id FROM document_files WHERE url_hash=%s AND pipeline_generation=%s LIMIT 1",
                    (url_hash, self.pipeline_generation)
                )
                row = cur.fetchone()

            if row is not None:
                # Update existing row
                cur.execute(
                    """UPDATE document_files SET
                         queue_id=%s,
                         procurement_id=%s,
                         source_table=%s,
                         source_id=COALESCE(source_id, %s),
                         file_name=COALESCE(file_name, %s),
                         url=%s,
                         url_hash=%s,
                         canonical_source_document_id=COALESCE(canonical_source_document_id, %s),
                         physical_download_key=COALESCE(physical_download_key, %s)
                       WHERE id=%s
                    """,
                    (queue_id, procurement_id, table_source, source_id, file_name, url, url_hash, canonical_source_document_id, physical_download_key, row[0])
                )
            else:
                # Insert new row
                cur.execute(
                    """INSERT INTO document_files
                       (queue_id, procurement_id, source_table, source_id, url, url_hash, file_name,
                        download_status, pipeline_generation, canonical_source_document_id, physical_download_key)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,'PENDING',%s,%s,%s)
                    """,
                    (queue_id, procurement_id, table_source, source_id, url, url_hash, file_name, self.pipeline_generation, canonical_source_document_id, physical_download_key)
                )
        conn.commit()

    def get_file_status(self, procurement_id, table_source, file_name, url_hash):
        del procurement_id, table_source, file_name
        if not url_hash:
            return None
        row = self._one(
            "SELECT download_status, local_path FROM document_files WHERE url_hash=%s AND pipeline_generation=%s LIMIT 1",
            (url_hash, self.pipeline_generation),
        )
        return (row[0], row[1]) if row else None

    def mark_file_status(self, procurement_id, table_source, file_name, url_hash, status, worker_id=None):
        del procurement_id, table_source, file_name
        if not url_hash:
            return
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE document_files SET download_status=%s, worker_id=COALESCE(%s, worker_id) WHERE url_hash=%s AND pipeline_generation=%s",
                (status.upper(), worker_id, url_hash, self.pipeline_generation),
            )
            if cur.rowcount != 1:
                conn.rollback()
                raise RuntimeError(f"S13 document_files row missing for url_hash={url_hash}")
        conn.commit()

    def finalize_download_status(self, procurement_id, table_source, file_name, url_hash, success, error_message=None, local_path=None):
        path_obj = None
        if local_path:
            from pathlib import Path as _Path
            path_obj = _Path(local_path)
        file_size = path_obj.stat().st_size if path_obj and path_obj.exists() else None
        conn = self._get_conn()
        with conn.cursor() as cur:
            if url_hash:
                cur.execute(
                    """UPDATE document_files SET download_status=%s, error_message=%s,
                              local_path=COALESCE(%s,local_path), file_size_bytes=COALESCE(%s,file_size_bytes),
                              downloaded_at=CASE WHEN %s THEN COALESCE(downloaded_at,NOW()) ELSE downloaded_at END
                       WHERE url_hash=%s AND pipeline_generation=%s""",
                    ("COMPLETED" if success else "FAILED", error_message, str(local_path) if local_path else None, file_size, success, url_hash, self.pipeline_generation),
                )
            else:
                cur.execute(
                    """UPDATE document_files SET download_status=%s, error_message=%s,
                              local_path=COALESCE(%s,local_path), file_size_bytes=COALESCE(%s,file_size_bytes),
                              downloaded_at=CASE WHEN %s THEN COALESCE(downloaded_at,NOW()) ELSE downloaded_at END
                       WHERE procurement_id=%s AND file_name=%s AND pipeline_generation=%s""",
                    ("COMPLETED" if success else "FAILED", error_message, str(local_path) if local_path else None, file_size, success, procurement_id, file_name, self.pipeline_generation),
                )
            if cur.rowcount < 1:
                self.logger.warning(f"S13 document_files row missing for url_hash={url_hash} or file_name={file_name}")
        conn.commit()

    def record_download_attempt(self, queue_id, procurement_id, source_url, url_hash, attempt_number, result, error_class=None, http_status=None, bytes_received=None, duration_ms=None):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM document_files WHERE url_hash=%s AND pipeline_generation=%s LIMIT 1",
                (url_hash, self.pipeline_generation),
            )
            row = cur.fetchone()
            file_id = row[0] if row else None
            cur.execute(
                """INSERT INTO download_attempts
                   (queue_id, procurement_id, file_id, source_url, url_hash, attempt_number,
                    started_at, finished_at, http_status, error_class, bytes, latency, result,
                    duration_ms, bytes_received, pipeline_generation)
                   VALUES (%s,%s,%s,%s,%s,%s,NOW(),NOW(),%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    queue_id,
                    procurement_id,
                    file_id,
                    source_url,
                    url_hash,
                    attempt_number,
                    http_status,
                    error_class,
                    bytes_received,
                    (duration_ms / 1000.0) if duration_ms is not None else None,
                    result,
                    duration_ms,
                    bytes_received,
                    self.pipeline_generation,
                ),
            )
        conn.commit()

    def get_processed_status(self, procurement_id, table_source, file_name):
        del table_source
        row = self._one(
            "SELECT download_status FROM document_files WHERE procurement_id=%s AND file_name=%s AND pipeline_generation=%s ORDER BY id DESC LIMIT 1",
            (procurement_id, file_name, self.pipeline_generation),
        )
        return (row[0],) if row else None

    def finalize_processing_status(self, procurement_id, table_source, file_name, is_interesting, error_message=None):
        del table_source, is_interesting
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE document_files SET download_status=%s, error_message=%s WHERE procurement_id=%s AND file_name=%s AND pipeline_generation=%s",
                ("FAILED" if error_message else "COMPLETED", error_message, procurement_id, file_name, self.pipeline_generation),
            )
            if cur.rowcount < 1:
                conn.rollback()
                raise RuntimeError(f"S13 document_files row missing for procurement={procurement_id} file={file_name}")
        conn.commit()

    def list_file_statuses(self, procurement_id, table_source, raise_on_error=False):
        del table_source
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT file_name, download_status FROM document_files WHERE procurement_id=%s AND pipeline_generation=%s",
                    (procurement_id, self.pipeline_generation),
                )
                return [(str(r[0]), str(r[1]).lower()) for r in cur.fetchall()]
        except Exception:
            if raise_on_error:
                raise
            return []

    @staticmethod
    def _resume_not_supported():
        raise RuntimeError("S13_V2 incremental PDF resume requires local durable cursor state")

    def get_progress_cursor(self, procurement_id, table_source, file_name):
        del procurement_id, table_source, file_name
        return 0

    def set_progress_cursor(self, procurement_id, table_source, file_name, cursor):
        pass

    def mark_pending_resume(self, procurement_id, table_source, file_name, progress_cursor, error_message=None):
        pass

    def mark_error_memory(self, procurement_id, table_source, file_name, error_message):
        return self.finalize_processing_status(procurement_id, table_source, file_name, False, error_message)

    def reset_stale(self, worker_id):
        del worker_id
        return 0
