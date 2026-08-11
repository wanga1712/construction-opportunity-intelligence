"""Backend-neutral processing and download state adapters."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional, Tuple

from document_processor.processed_registry import ProcessedRegistry

StatusRow = Tuple[str]


class ProcessingStateRepository(ABC):
    """Small state boundary used by downloader, pipeline and PDF parser."""

    @abstractmethod
    def ensure_download_file(self, queue_id, procurement_id, table_source, url, url_hash, file_name): ...

    @abstractmethod
    def get_file_status(self, procurement_id, table_source, file_name, url_hash): ...

    @abstractmethod
    def mark_file_status(self, procurement_id, table_source, file_name, url_hash, status, worker_id=None): ...

    @abstractmethod
    def finalize_download_status(self, procurement_id, table_source, file_name, url_hash, success, error_message=None): ...

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

    def ensure_download_file(self, queue_id, procurement_id, table_source, url, url_hash, file_name):
        del queue_id, procurement_id, table_source, url, url_hash, file_name

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
        self._conn = None

    def _get_conn(self):
        import psycopg2

        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self._dsn)
            self._conn.autocommit = False
        return self._conn

    def _one(self, sql, params):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def ensure_download_file(self, queue_id, procurement_id, table_source, url, url_hash, file_name):
        if procurement_id is None:
            raise RuntimeError("S13_V2 requires a resolved procurement_id before download")
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO document_files
                   (queue_id, procurement_id, source_table, url, url_hash, file_name,
                    download_status, pipeline_generation)
                   VALUES (%s,%s,%s,%s,%s,%s,'PENDING',%s)
                   ON CONFLICT (url_hash,pipeline_generation) DO UPDATE SET
                     queue_id=EXCLUDED.queue_id,
                     procurement_id=EXCLUDED.procurement_id,
                     source_table=EXCLUDED.source_table,
                     file_name=COALESCE(document_files.file_name,EXCLUDED.file_name)
                """,
                (queue_id, procurement_id, table_source, url, url_hash, file_name, self.pipeline_generation),
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
        del procurement_id, table_source, file_name
        if not url_hash:
            return
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE document_files SET download_status=%s, error_message=%s, local_path=COALESCE(%s,local_path), downloaded_at=CASE WHEN %s THEN COALESCE(downloaded_at,NOW()) ELSE downloaded_at END WHERE url_hash=%s AND pipeline_generation=%s",
                ("COMPLETED" if success else "FAILED", error_message, str(local_path) if local_path else None, success, url_hash, self.pipeline_generation),
            )
            if cur.rowcount != 1:
                conn.rollback()
                raise RuntimeError(f"S13 document_files row missing for url_hash={url_hash}")
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
        del procurement_id, table_source, file_name, cursor
        self._resume_not_supported()

    def mark_pending_resume(self, procurement_id, table_source, file_name, progress_cursor, error_message=None):
        del procurement_id, table_source, file_name, progress_cursor, error_message
        self._resume_not_supported()

    def mark_error_memory(self, procurement_id, table_source, file_name, error_message):
        return self.finalize_processing_status(procurement_id, table_source, file_name, False, error_message)

    def reset_stale(self, worker_id):
        del worker_id
        return 0
