import os
import socket
from typing import List, Optional, Tuple

from database_work.database_connection import DatabaseManager

from .resume_constants import (
    STATUS_COMPLETED,
    STATUS_ERROR_MEMORY,
    STATUS_PENDING_RESUME,
    STATUS_PROCESSING,
    STATUS_SKIPPED,
    max_resume_attempts,
)
from .registry_contract_locator import RegistryContractLocator


class ProcessedRegistry:
    """
    Управляет таблицей processed_documents:
    - Регистрация статусов файлов (pending, processing, completed, error)
    - Курсор OCR
    - Путь загрузки на Яндекс.Диск
    """
    def __init__(self, db: DatabaseManager, db_alias: str, logger):
        self.db = db
        self.db_alias = db_alias
        self.logger = logger
        self.contract_locator = RegistryContractLocator(db, db_alias, logger)
        self._ensure_processed_table()

    def _ensure_processed_table(self) -> None:
        sql = """
        CREATE TABLE IF NOT EXISTS processed_documents (
            id BIGSERIAL PRIMARY KEY,
            tender_id BIGINT NOT NULL,
            table_source TEXT NOT NULL,
            file_name TEXT NOT NULL,
            status TEXT NOT NULL,
            is_interesting BOOLEAN,
            worker_id INT,
            worker_host TEXT,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            error_message TEXT,
            UNIQUE(tender_id, table_source, file_name)
        )
        """
        try:
            self.db.execute_query(self.db_alias, sql)
        except Exception:
            pass
        for ddl in (
            "ALTER TABLE processed_documents ADD COLUMN IF NOT EXISTS progress_cursor INT DEFAULT 0",
            "ALTER TABLE processed_documents ADD COLUMN IF NOT EXISTS resume_attempts INT DEFAULT 0",
            "ALTER TABLE processed_documents ADD COLUMN IF NOT EXISTS last_resume_cursor INT",
        ):
            try:
                self.db.execute_query(self.db_alias, ddl)
            except Exception:
                pass

    def __resolve_tender_id_by_table(self, table_source: str, contract_number: str) -> Optional[int]:
        return self.contract_locator.resolve_tender_id(contract_number, table_source)

    def get_processed_status(self, tender_id: int, table_source: str, file_name: str) -> Optional[Tuple[str]]:
        sql = """
            SELECT status
            FROM processed_documents
            WHERE tender_id = %s AND table_source = %s AND file_name = %s
            LIMIT 1
        """
        try:
            rows = self.db.execute_query(self.db_alias, sql, (tender_id, table_source, file_name), fetch=True) or []
            if rows:
                return (rows[0][0],)
        except Exception:
            return None
        return None

    def mark_file_status(self, tender_id: int, table_source: str, file_name: str, status: str) -> None:
        host = os.getenv("HOSTNAME") or socket.gethostname()
        sql = """
            INSERT INTO processed_documents (tender_id, table_source, file_name, status, worker_id, worker_host, started_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tender_id, table_source, file_name)
            DO UPDATE SET status = EXCLUDED.status,
                          worker_id = EXCLUDED.worker_id,
                          worker_host = EXCLUDED.worker_host,
                          started_at = EXCLUDED.started_at
        """
        try:
            wid = int(os.getenv("WORKER_ID", "0"))
        except Exception:
            wid = 0
        try:
            self.db.execute_query(self.db_alias, sql, (tender_id, table_source, file_name, status, wid, host))
            self.logger.info(f"processed_documents: {file_name} → {status}")
        except Exception as e:
            self.logger.error(f"Error in mark_file_status for {file_name}: {e}")

    def list_file_statuses(
        self,
        tender_id: int,
        table_source: str,
        *,
        raise_on_error: bool = False,
    ) -> List[Tuple[str, str]]:
        sql = """
            SELECT file_name, status
            FROM processed_documents
            WHERE tender_id = %s AND table_source = %s
        """
        try:
            rows = self.db.execute_query(
                self.db_alias, sql, (tender_id, table_source), fetch=True
            ) or []
            return [(str(r[0]), str(r[1])) for r in rows]
        except Exception as e:
            self.logger.error(f"list_file_statuses error: {e}")
            if raise_on_error:
                raise
            return []

    def mark_pending_resume(
        self,
        tender_id: int,
        table_source: str,
        file_name: str,
        progress_cursor: int,
        error_message: Optional[str] = None,
    ) -> int:
        """Переводит файл в pending_resume, увеличивает счётчик попыток на том же курсоре."""
        host = os.getenv("HOSTNAME") or socket.gethostname()
        try:
            wid = int(os.getenv("WORKER_ID", "0"))
        except Exception:
            wid = 0

        rows = self.db.execute_query(
            self.db_alias,
            """
            SELECT resume_attempts, last_resume_cursor
            FROM processed_documents
            WHERE tender_id = %s AND table_source = %s AND file_name = %s
            LIMIT 1
            """,
            (tender_id, table_source, file_name),
            fetch=True,
        ) or []
        attempts = 0
        last_cursor = None
        if rows:
            attempts = int(rows[0][0] or 0)
            last_cursor = rows[0][1]

        if last_cursor is not None and int(last_cursor) == int(progress_cursor):
            attempts += 1
        else:
            attempts = 1

        sql = """
            INSERT INTO processed_documents (
                tender_id, table_source, file_name, status,
                progress_cursor, resume_attempts, last_resume_cursor,
                worker_id, worker_host, started_at, error_message
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
            ON CONFLICT (tender_id, table_source, file_name)
            DO UPDATE SET
                status = EXCLUDED.status,
                progress_cursor = EXCLUDED.progress_cursor,
                resume_attempts = EXCLUDED.resume_attempts,
                last_resume_cursor = EXCLUDED.last_resume_cursor,
                worker_id = EXCLUDED.worker_id,
                worker_host = EXCLUDED.worker_host,
                error_message = EXCLUDED.error_message
        """
        self.db.execute_query(
            self.db_alias,
            sql,
            (
                tender_id,
                table_source,
                file_name,
                STATUS_PENDING_RESUME,
                progress_cursor,
                attempts,
                progress_cursor,
                wid,
                host,
                error_message,
            ),
        )
        self.logger.info(
            f"processed_documents: {file_name} → pending_resume "
            f"(cursor={progress_cursor}, attempts={attempts})"
        )
        return attempts

    def mark_error_memory(
        self,
        tender_id: int,
        table_source: str,
        file_name: str,
        error_message: str,
    ) -> None:
        host = os.getenv("HOSTNAME") or socket.gethostname()
        try:
            wid = int(os.getenv("WORKER_ID", "0"))
        except Exception:
            wid = 0
        sql = """
            INSERT INTO processed_documents (
                tender_id, table_source, file_name, status,
                is_interesting, error_message, worker_id, worker_host,
                started_at, finished_at
            )
            VALUES (%s, %s, %s, %s, false, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (tender_id, table_source, file_name)
            DO UPDATE SET
                status = EXCLUDED.status,
                is_interesting = false,
                error_message = EXCLUDED.error_message,
                finished_at = NOW()
        """
        self.db.execute_query(
            self.db_alias,
            sql,
            (
                tender_id,
                table_source,
                file_name,
                STATUS_ERROR_MEMORY,
                error_message,
                wid,
                host,
            ),
        )
        self.logger.error(
            f"processed_documents: {file_name} → error_memory ({error_message})"
        )

    def clear_resume_state_on_complete(
        self, tender_id: int, table_source: str, file_name: str
    ) -> None:
        try:
            self.db.execute_query(
                self.db_alias,
                """
                UPDATE processed_documents
                SET resume_attempts = 0,
                    last_resume_cursor = NULL,
                    progress_cursor = 0,
                    error_message = NULL
                WHERE tender_id = %s AND table_source = %s AND file_name = %s
                """,
                (tender_id, table_source, file_name),
            )
        except Exception:
            pass

    def finalize_file_status(self, tender_id: int, table_source: str, file_name: str, is_interesting: bool, error_message: Optional[str] = None) -> None:
        # Используем UPSERT (INSERT ... ON CONFLICT UPDATE) чтобы гарантировать наличие записи
        host = os.getenv("HOSTNAME") or socket.gethostname()
        try:
            wid = int(os.getenv("WORKER_ID", "0"))
        except Exception:
            wid = 0
            
        sql = """
            INSERT INTO processed_documents (tender_id, table_source, file_name, status, is_interesting, error_message, worker_id, worker_host, started_at, finished_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (tender_id, table_source, file_name)
            DO UPDATE SET status = EXCLUDED.status,
                          is_interesting = EXCLUDED.is_interesting,
                          error_message = EXCLUDED.error_message,
                          finished_at = NOW()
        """
        
        status = 'error' if error_message else 'completed'
        
        try:
            self.db.execute_query(self.db_alias, sql, (tender_id, table_source, file_name, status, is_interesting, error_message, wid, host))
            if status == STATUS_COMPLETED and not error_message:
                self.clear_resume_state_on_complete(tender_id, table_source, file_name)
            log_status = f"error: {error_message}" if error_message else f"completed (is_interesting={is_interesting})"
            self.logger.info(f"processed_documents finalize: {file_name} → {log_status}")
        except Exception as e:
            self.logger.error(f"Error in finalize_file_status for {file_name}: {e}")

    def mark_nonblocking_error(
        self,
        tender_id: int,
        table_source: str,
        file_name: str,
        error_message: str,
    ) -> None:
        host = os.getenv("HOSTNAME") or socket.gethostname()
        try:
            wid = int(os.getenv("WORKER_ID", "0"))
        except Exception:
            wid = 0

        sql = """
            INSERT INTO processed_documents (tender_id, table_source, file_name, status, is_interesting, error_message, worker_id, worker_host, started_at, finished_at)
            VALUES (%s, %s, %s, %s, false, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (tender_id, table_source, file_name)
            DO UPDATE SET status = EXCLUDED.status,
                          is_interesting = EXCLUDED.is_interesting,
                          error_message = EXCLUDED.error_message,
                          finished_at = NOW()
        """
        try:
            self.db.execute_query(
                self.db_alias,
                sql,
                (tender_id, table_source, file_name, STATUS_SKIPPED, error_message, wid, host),
            )
            self.logger.info(f"processed_documents finalize: {file_name} ? skipped ({error_message})")
        except Exception as e:
            self.logger.error(f"Error in mark_nonblocking_error for {file_name}: {e}")

    def get_progress_cursor(self, tender_id: int, table_source: str, file_name: str) -> int:
        sql = """
            SELECT progress_cursor
            FROM processed_documents
            WHERE tender_id = %s AND table_source = %s AND file_name = %s
            LIMIT 1
        """
        try:
            rows = self.db.execute_query(self.db_alias, sql, (tender_id, table_source, file_name), fetch=True) or []
            if rows:
                val = rows[0][0]
                try:
                    return int(val or 0)
                except Exception:
                    return 0
        except Exception:
            return 0
        return 0

    def set_progress_cursor(self, tender_id: int, table_source: str, file_name: str, cursor: int) -> None:
        sql = """
            UPDATE processed_documents
            SET progress_cursor = %s
            WHERE tender_id = %s AND table_source = %s AND file_name = %s
        """
        try:
            self.db.execute_query(self.db_alias, sql, (cursor, tender_id, table_source, file_name))
        except Exception:
            pass

    def set_processed_yandex_path(self, tender_id: int, table_source: str, file_name: str, yandex_path: str) -> None:
        try:
            self.db.execute_query(
                self.db_alias,
                "ALTER TABLE processed_documents ADD COLUMN IF NOT EXISTS yandex_path TEXT"
            )
        except Exception:
            pass
        try:
            self.db.execute_query(
                self.db_alias,
                "UPDATE processed_documents SET yandex_path=%s WHERE tender_id=%s AND table_source=%s AND file_name=%s",
                (yandex_path, tender_id, table_source, file_name),
            )
            try:
                self.logger.info(f"processed_documents: yandex_path сохранён для {file_name}: {yandex_path}")
            except Exception:
                pass
        except Exception:
            pass
