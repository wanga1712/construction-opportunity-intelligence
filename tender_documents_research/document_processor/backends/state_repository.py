import logging
from typing import Optional, Tuple
from datetime import datetime

class ProcessingStateRepository:
    """Base interface for processing state tracking."""
    def get_file_status(self, procurement_id: int, table_source: str, file_name: str, url_hash: str) -> Optional[Tuple[str]]:
        raise NotImplementedError

    def mark_file_status(self, procurement_id: int, table_source: str, file_name: str, url_hash: str, status: str, worker_id: int = None):
        raise NotImplementedError

    def finalize_file_status(self, procurement_id: int, table_source: str, file_name: str, url_hash: str, success: bool, error_message: str = None):
        raise NotImplementedError

    def list_file_statuses(self, procurement_id: int, table_source: str, raise_on_error: bool = False):
        raise NotImplementedError


class LegacyStateRepository(ProcessingStateRepository):
    """Uses tender_monitor.processed_documents (Legacy S7)."""
    def __init__(self, db, db_alias: str = 'default'):
        self.db = db
        self.db_alias = db_alias
        self.logger = logging.getLogger("LegacyStateRepository")

    def get_file_status(self, procurement_id: int, table_source: str, file_name: str, url_hash: str) -> Optional[Tuple[str]]:
        # Legacy relies on tender_id (procurement_id in modern terms) and file_name
        sql = """
            SELECT status
            FROM processed_documents
            WHERE tender_id = %s AND table_source = %s AND file_name = %s
            LIMIT 1
        """
        try:
            rows = self.db.execute_query(self.db_alias, sql, (procurement_id, table_source, file_name), fetch=True) or []
            if rows:
                return (rows[0][0],)
        except Exception as e:
            self.logger.error(f"Error checking legacy processed_documents: {e}")
        return None

    def mark_file_status(self, procurement_id: int, table_source: str, file_name: str, url_hash: str, status: str, worker_id: int = None):
        sql = """
            INSERT INTO processed_documents (tender_id, table_source, file_name, status, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tender_id, table_source, file_name)
            DO UPDATE SET status = EXCLUDED.status, updated_at = EXCLUDED.updated_at
        """
        try:
            self.db.execute_query(
                self.db_alias, 
                sql, 
                (procurement_id, table_source, file_name, status, datetime.now())
            )
        except Exception as e:
            self.logger.error(f"Error marking legacy processed_documents: {e}")

    def finalize_file_status(self, procurement_id: int, table_source: str, file_name: str, url_hash: str, success: bool, error_message: str = None):
        status = 'completed' if success else 'error'
        sql = """
            INSERT INTO processed_documents (tender_id, table_source, file_name, status, error_message, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tender_id, table_source, file_name)
            DO UPDATE SET status = EXCLUDED.status, error_message = EXCLUDED.error_message, updated_at = EXCLUDED.updated_at
        """
        try:
            self.db.execute_query(
                self.db_alias, 
                sql, 
                (procurement_id, table_source, file_name, status, error_message, datetime.now())
            )
        except Exception as e:
            self.logger.error(f"Error finalizing legacy processed_documents: {e}")

    def list_file_statuses(self, procurement_id: int, table_source: str, raise_on_error: bool = False):
        sql = """
            SELECT file_name, status
            FROM processed_documents
            WHERE tender_id = %s AND table_source = %s
        """
        try:
            return self.db.execute_query(self.db_alias, sql, (procurement_id, table_source), fetch=True) or []
        except Exception as e:
            self.logger.error(f"Error listing legacy file statuses: {e}")
            if raise_on_error: raise e
            return []


class S13V2StateRepository(ProcessingStateRepository):
    """Uses local document_intelligence.document_files (S13_V2)."""
    def __init__(self, dsn: dict, pipeline_generation: str = 'S13_V2'):
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

    def get_file_status(self, procurement_id: int, table_source: str, file_name: str, url_hash: str) -> Optional[Tuple[str]]:
        if not url_hash:
            return None
            
        sql = """
            SELECT download_status
            FROM document_files
            WHERE url_hash = %s AND pipeline_generation = %s
            LIMIT 1
        """
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(sql, (url_hash, self.pipeline_generation))
                row = cur.fetchone()
                if row:
                    return (row[0],)
        except Exception as e:
            self.logger.error(f"Error checking local document_files state: {e}")
            raise e
        return None

    def mark_file_status(self, procurement_id: int, table_source: str, file_name: str, url_hash: str, status: str, worker_id: int = None):
        if not url_hash:
            return
            
        sql = """
            UPDATE document_files
            SET download_status = %s,
                worker_id = COALESCE(%s, worker_id)
            WHERE url_hash = %s AND pipeline_generation = %s
        """
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(sql, (status, worker_id, url_hash, self.pipeline_generation))
            conn.commit()
        except Exception as e:
            self.logger.error(f"Error marking local document_files state: {e}")
            raise e

    def finalize_file_status(self, procurement_id: int, table_source: str, file_name: str, url_hash: str, success: bool, error_message: str = None):
        if not url_hash:
            return
            
        status = 'COMPLETED' if success else 'FAILED'
        sql = """
            UPDATE document_files
            SET download_status = %s,
                error_message = %s,
                downloaded_at = COALESCE(downloaded_at, NOW())
            WHERE url_hash = %s AND pipeline_generation = %s
        """
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(sql, (status, error_message, url_hash, self.pipeline_generation))
            conn.commit()
        except Exception as e:
            self.logger.error(f"Error finalizing local document_files state: {e}")
            raise e

    def list_file_statuses(self, procurement_id: int, table_source: str, raise_on_error: bool = False):
        sql = """
            SELECT file_name, download_status
            FROM document_files
            WHERE procurement_id = %s AND pipeline_generation = %s
        """
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(sql, (procurement_id, self.pipeline_generation))
                rows = cur.fetchall()
                return [(r[0], r[1]) for r in rows]
        except Exception as e:
            self.logger.error(f"Error listing local document_files statuses: {e}")
            if raise_on_error: raise e
            return []
