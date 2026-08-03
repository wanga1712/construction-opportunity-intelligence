"""Переобработка уже распарсенных закупок без удаления результатов."""

from __future__ import annotations

from typing import Dict, List, Optional

from database_work.database_connection import DatabaseManager
from utils.logger_config import get_logger


class ReparseQueueManager:
    """Возвращает задачи в очередь и сбрасывает курсоры OCR для полного перепарса."""

    REPARSE_STATUSES = ("completed", "error")

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or DatabaseManager()
        self.logger = get_logger()

    def requeue_for_reparse(self, include_no_links: bool = False) -> Dict[str, int]:
        """
        Переводит обработанные задачи обратно в pending.
        Данные tender_document_matches НЕ удаляются — при повторном парсе
        save_matches делает UPSERT и обновляет details.
        """
        statuses: List[str] = list(self.REPARSE_STATUSES)
        if include_no_links:
            statuses.append("no_links")

        stats = {"queue_requeued": 0, "files_reset": 0}

        try:
            rows = self.db.execute_query(
                "tender_monitor",
                """
                WITH upd AS (
                    UPDATE document_processing_queue
                    SET status = 'pending',
                        worker_id = NULL,
                        started_at = NULL,
                        completed_at = NULL,
                        error_message = NULL
                    WHERE status = ANY(%s)
                    RETURNING id
                )
                SELECT COUNT(*) FROM upd
                """,
                (statuses,),
                fetch=True,
            ) or []
            stats["queue_requeued"] = int(rows[0][0]) if rows else 0
        except Exception as exc:
            self.logger.error(f"requeue_for_reparse queue error: {exc}", exc_info=True)
            raise

        try:
            rows = self.db.execute_query(
                "tender_monitor",
                """
                UPDATE processed_documents
                SET status = 'pending',
                    progress_cursor = 0,
                    started_at = NULL,
                    finished_at = NULL,
                    error_message = NULL
                WHERE status IN ('completed', 'error', 'processing')
                RETURNING id
                """,
                fetch=True,
            ) or []
            stats["files_reset"] = len(rows)
        except Exception as exc:
            self.logger.error(f"requeue_for_reparse files error: {exc}", exc_info=True)

        self.logger.info(
            f"requeue_for_reparse: queue={stats['queue_requeued']}, "
            f"files_reset={stats['files_reset']}"
        )
        return stats

    def close(self) -> None:
        self.db.close()
