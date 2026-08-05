import json
from typing import Any, Dict, List, Optional

import psycopg2

from database_work.database_connection import DatabaseManager
from utils.logger_config import get_logger
from document_processor.crm_observation_store import CrmObservationStore


class MatchRepository:
    """
    Отвечает за сохранение результатов поиска (совпадений) и ошибок в базу данных.
    """
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.logger = get_logger()
        self.observation_store = CrmObservationStore()

    def _detect_detail_schema(self) -> set[str]:
        """Определяет актуальную схему таблицы tender_document_match_details."""
        query = """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'tender_document_match_details'
        """
        try:
            rows = self.db.execute_query("tender_monitor", query, fetch=True) or []
            return {str(r[0]) for r in rows if r and r[0]}
        except Exception as exc:
            self.logger.error(f"Ошибка чтения схемы tender_document_match_details: {exc}", exc_info=True)
            return set()

    def save_matches(
        self,
        tender_id: int,
        registry_type: str,
        file_name: str,
        matches: List[Dict[str, Any]],
        yandex_path: Optional[str] = None,
        worker_id: int = 0,
        processing_time_seconds: float = 0.0,
        total_files_processed: int = 0,
        total_size_bytes: int = 0,
        folder_name: Optional[str] = None,
        status: str = "completed",
        merge_existing: bool = False,
    ) -> None:
        if not matches:
            return
        
        detail_schema_columns = self._detect_detail_schema()

        try:
            match_count = len(matches)
            is_interesting = True
            sql_header = """
                INSERT INTO tender_document_matches (
                    tender_id, registry_type, file_name,
                    match_count, is_interesting, yandex_path,
                    worker_id, processing_time_seconds,
                    total_files_processed, total_size_bytes,
                    processed_at, has_error, status, folder_name
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), false, %s, %s)
                ON CONFLICT (tender_id, registry_type, file_name)
                DO UPDATE SET
                    match_count = CASE
                        WHEN %s THEN tender_document_matches.match_count
                        ELSE EXCLUDED.match_count
                    END,
                    is_interesting = EXCLUDED.is_interesting,
                    yandex_path = COALESCE(EXCLUDED.yandex_path, tender_document_matches.yandex_path),
                    worker_id = EXCLUDED.worker_id,
                    processing_time_seconds = EXCLUDED.processing_time_seconds,
                    total_files_processed = EXCLUDED.total_files_processed,
                    total_size_bytes = EXCLUDED.total_size_bytes,
                    processed_at = NOW(),
                    has_error = false,
                    status = EXCLUDED.status,
                    folder_name = EXCLUDED.folder_name,
                    updated_at = NOW()
                RETURNING id
            """
            rows = self.db.execute_query(
                "tender_monitor",
                sql_header,
                (
                    tender_id, registry_type, file_name,
                    match_count, is_interesting, yandex_path,
                    worker_id, processing_time_seconds,
                    total_files_processed, total_size_bytes,
                    status, folder_name,
                    merge_existing,
                ),
                fetch=True,
            ) or []
            if not rows:
                return
            match_id = rows[0][0]
        except Exception as exc:
            self.logger.error(f"save_matches: ошибка сохранения заголовка для {file_name}: {exc}", exc_info=True)
            return

        if not merge_existing:
            try:
                self.db.execute_query(
                    "tender_monitor",
                    "DELETE FROM tender_document_match_details WHERE match_id = %s",
                    (match_id,),
                )
            except Exception:
                pass

        # Внутрибатчевая семантическая дедупликация:
        # один уникальный (keyword, display_text) на match — одна запись.
        # Устраняет тысячи строк с одинаковым текстом ячейки из больших смет,
        # где keyword встречается в каждой строке одного раздела.
        seen_in_batch: set[tuple[str, str]] = set()

        for m in matches:
            try:
                matched_line_text = m.get("matched_line") or ""
                matched_cell_text = m.get("matched_summary") or m.get("matched_cell_text") or matched_line_text
                score = m.get("score") or 0
                keyword = m.get("keyword") or ""
                line_number = m.get("line_number") or -1

                # Дедупликация: один keyword на одной строке таблицы — одна запись.
                # Раньше dedup шёл только по matched_text и схлопывал одинаковые
                # позиции из разных разделов сметы (эталон 0172200002525000537).
                dedup_text = matched_cell_text or matched_line_text
                batch_key = (keyword, dedup_text)
                if batch_key in seen_in_batch:
                    self.logger.debug(
                        f"save_matches: batch dedup skip '{keyword}' (same text) in {file_name}"
                    )
                    continue
                seen_in_batch.add(batch_key)
                if keyword and line_number > 0:
                    try:
                        existing = self.db.execute_query(
                            "tender_monitor",
                            """
                            SELECT d.score
                            FROM tender_document_match_details d
                            JOIN tender_document_matches m ON m.id = d.match_id
                            WHERE m.tender_id = %s
                              AND d.product_name = %s
                              AND d.line_number = %s
                              AND d.score >= %s
                            LIMIT 1
                            """,
                            (tender_id, keyword, line_number, score),
                            fetch=True,
                        ) or []
                        if existing:
                            self.logger.debug(
                                f"save_matches: dedup skip '{keyword}' line={line_number} "
                                f"score={score} (existing score={existing[0][0]}) in {file_name}"
                            )
                            continue
                    except Exception:
                        pass  # При ошибке проверки — записываем как обычно
                elif dedup_text and keyword:
                    try:
                        existing = self.db.execute_query(
                            "tender_monitor",
                            """
                            SELECT d.score
                            FROM tender_document_match_details d
                            JOIN tender_document_matches m ON m.id = d.match_id
                            WHERE m.tender_id = %s
                              AND d.product_name = %s
                              AND d.matched_text = %s
                              AND d.score >= %s
                            LIMIT 1
                            """,
                            (tender_id, keyword, dedup_text, score),
                            fetch=True,
                        ) or []
                        if existing:
                            self.logger.debug(
                                f"save_matches: dedup skip '{keyword}' score={score} "
                                f"(existing score={existing[0][0]}) in {file_name}"
                            )
                            continue
                    except Exception:
                        pass
                
                cols: list[str] = ["match_id", "product_name"]
                vals: list[object] = [match_id, keyword]
                
                if "matched_display_text" in detail_schema_columns:
                    cols.append("matched_display_text")
                    vals.append(m.get("matched_display_text") or matched_line_text)
                if "matched_text" in detail_schema_columns:
                    cols.append("matched_text")
                    vals.append(matched_cell_text)
                if "row_data" in detail_schema_columns and m.get("row_data") is not None:
                    cols.append("row_data")
                    vals.append(json.dumps(m.get("row_data"), ensure_ascii=False))

                cols.append("score")
                vals.append(score)
                cols.append("matched_keywords")
                vals.append([keyword])
                
                if "line_number" in detail_schema_columns:
                    cols.append("line_number")
                    vals.append(line_number)
                if "source_file" in detail_schema_columns:
                    cols.append("source_file")
                    vals.append(file_name)
                if "sheet_name" in detail_schema_columns:
                    cols.append("sheet_name")
                    vals.append(m.get("sheet_name"))
                if "row_index" in detail_schema_columns:
                    cols.append("row_index")
                    vals.append(m.get("row_index"))
                if "column_letter" in detail_schema_columns:
                    cols.append("column_letter")
                    vals.append(m.get("column_letter"))
                if "cell_address" in detail_schema_columns:
                    cols.append("cell_address")
                    vals.append(m.get("cell_address"))
                    
                placeholders = ", ".join(["%s"] * len(vals))
                col_list = ", ".join(cols)
                sql_detail = f"""
                    INSERT INTO tender_document_match_details (
                        {col_list}
                    )
                    VALUES ({placeholders})
                """
                self.db.execute_query("tender_monitor", sql_detail, tuple(vals))
            except Exception as exc:
                self.logger.error(f"save_matches: ошибка INSERT details ({keyword}): {exc}", exc_info=True)

        self._refresh_match_count(match_id)
        try:
            self.observation_store.record_matches(
                tender_id=tender_id,
                registry_type=registry_type,
                match_id=match_id,
                file_name=file_name,
                matches=matches,
            )
        except Exception as exc:
            self.logger.error(f"save_matches: observation store error for {file_name}: {exc}", exc_info=True)

    def _refresh_match_count(self, match_id: int) -> None:
        try:
            self.db.execute_query(
                "tender_monitor",
                """
                UPDATE tender_document_matches m
                SET match_count = (
                    SELECT COUNT(*) FROM tender_document_match_details d
                    WHERE d.match_id = m.id
                ),
                is_interesting = (
                    SELECT COUNT(*) > 0 FROM tender_document_match_details d
                    WHERE d.match_id = m.id
                ),
                updated_at = NOW()
                WHERE m.id = %s
                """,
                (match_id,),
            )
        except Exception as exc:
            self.logger.error(f"_refresh_match_count error: {exc}", exc_info=True)

    def save_file_error(
        self,
        tender_id: int,
        registry_type: str,
        file_name: str,
        error_reason: str,
        worker_id: int = 0,
        folder_name: Optional[str] = None,
    ) -> None:
        """Сохраняет запись об ошибке парсинга файла в БД."""
        sql = """
            INSERT INTO tender_document_matches (
                tender_id, registry_type, file_name,
                match_count, is_interesting,
                status, worker_id, processed_at, has_error, error_reason, folder_name
            )
            VALUES (%s, %s, %s, 0, false, 'error', %s, NOW(), true, %s, %s)
            ON CONFLICT (tender_id, registry_type, file_name)
            DO UPDATE SET
                has_error = true,
                error_reason = EXCLUDED.error_reason,
                status = 'error',
                worker_id = EXCLUDED.worker_id,
                processed_at = EXCLUDED.processed_at,
                folder_name = EXCLUDED.folder_name,
                updated_at = NOW()
        """
        try:
            self.db.execute_query(
                "tender_monitor",
                sql,
                (tender_id, registry_type, file_name, worker_id, error_reason, folder_name),
            )
        except Exception as exc:
            self.logger.error(f"save_file_error: ошибка записи ошибки для {file_name}: {exc}", exc_info=True)
