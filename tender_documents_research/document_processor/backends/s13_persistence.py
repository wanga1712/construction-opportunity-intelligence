import logging
import psycopg2
import json
from typing import Optional

from document_processor.dto import TaskProcessResult, ProcessingOutcome
from database_work.database_connection import DatabaseManager

logger = logging.getLogger(__name__)

class S13V2TaskPersistenceService:
    """
    Transactional persistence service for S13_V2 processing results.
    Ensures that queue updates, files, results, matches, details, and evidence
    are committed atomically, avoiding partial state.
    """
    def __init__(self, db: DatabaseManager, pipeline_generation: str = "S13_V2"):
        self.db = db
        self.pipeline_generation = pipeline_generation

    def persist_task_result(self, result: TaskProcessResult):
        """
        Persist the full object graph of a TaskProcessResult atomically.
        """
        completed_files = [file_result for file_result in result.files if file_result.status == "COMPLETED"]
        if not completed_files:
            raise ValueError(f"[{self.pipeline_generation}] completion requires at least one successfully processed document")

        try:
            with self.db.get_cursor('document_intelligence') as cursor:
                # 1. Select for update to ensure we own the task and it's PROCESSING
                cursor.execute("""
                    SELECT status
                    FROM document_processing_queue
                    WHERE id = %s AND pipeline_generation = %s
                    FOR UPDATE NOWAIT
                """, (result.queue_id, self.pipeline_generation))

                row = cursor.fetchone()
                if not row:
                    logger.warning(f"Queue task {result.queue_id} not found or not {self.pipeline_generation}.")
                    return

                if row[0] not in ('PROCESSING', 'processing'):
                    logger.warning(f"Queue task {result.queue_id} is in status {row[0]}, expected PROCESSING.")
                    return

                # 2. Persist File Process Results
                for file_res in result.files:
                    file_id = self._resolve_document_file_id(cursor, result.queue_id, file_res)
                    if not file_id:
                        raise RuntimeError(
                            f"Missing document_files row for queue={result.queue_id} file={file_res.file_name}"
                        )

                    is_archive_member = bool(getattr(file_res, "archive_member_path", None))
                    if not is_archive_member:
                        cursor.execute("""
                            UPDATE document_files
                            SET download_status = %s, error_message = %s
                            WHERE id = %s AND pipeline_generation = %s
                        """, (file_res.status, file_res.error_message, file_id, self.pipeline_generation))

                    if file_id:
                        matches_found = sum(m.match_count for m in file_res.matches) if file_res.status == "COMPLETED" else 0
                        # Insert one terminal processing outcome for every discovered parser input.
                        cursor.execute("""
                            INSERT INTO document_processing_results
                            (queue_id, procurement_id, file_id, status, pages_processed, sheets_processed, rows_extracted, matches_found,
                             processed_file_name, processed_local_path, archive_member_path, is_archive_member, pipeline_generation)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                        """, (
                            result.queue_id, result.procurement_id, file_id,
                            file_res.status, file_res.pages, file_res.sheets, file_res.rows, matches_found,
                            file_res.file_name, getattr(file_res, "local_path", None), getattr(file_res, "archive_member_path", None), is_archive_member,
                            self.pipeline_generation
                        ))
                        result_id = cursor.fetchone()[0]

                        # Persist match graph only for successfully completed parser outcomes.
                        file_matches = [m for m in file_res.matches if file_res.status == "COMPLETED" and m.category_code != "processed"]
                        if file_matches:
                            total_matches = sum(m.match_count for m in file_matches)
                            max_score = max(m.score for m in file_matches)

                            cursor.execute("""
                                INSERT INTO document_matches
                                (queue_id, procurement_id, file_id, result_id, document_name, archive_member_path, match_count, score, pipeline_generation)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                RETURNING id
                            """, (
                                result.queue_id, result.procurement_id, file_id, result_id,
                                file_res.file_name, getattr(file_res, "archive_member_path", None),
                                total_matches, max_score, self.pipeline_generation
                            ))
                            match_id = cursor.fetchone()[0]

                            for match in file_matches:
                                for detail in match.details:
                                    cursor.execute("""
                                        INSERT INTO document_match_details
                                        (match_id, procurement_id, category_code, subcategory_code, matched_term, term_type, score, row_data, page_or_sheet, row_number, context_before, context_after, match_method, validation_status, validation_method, validation_reason, validated_at, validator_name, validator_version, pipeline_generation)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """, (
                                        match_id, result.procurement_id, detail.category_code, detail.subcategory_code,
                                        detail.matched_term, detail.term_type, detail.score,
                                        json.dumps(detail.row_data), detail.page_or_sheet, detail.row_number,
                                        json.dumps(detail.context_before), json.dumps(detail.context_after),
                                        getattr(detail, "match_method", "UNKNOWN") or "UNKNOWN",
                                        getattr(detail, "validation_status", "UNKNOWN") or "UNKNOWN",
                                        getattr(detail, "validation_method", None),
                                        getattr(detail, "validation_reason", None),
                                        getattr(detail, "validated_at", None),
                                        getattr(detail, "validator_name", None),
                                        getattr(detail, "validator_version", None),
                                        self.pipeline_generation
                                    ))

                # 3. Persist Evidence (Only for explicitly confirmed evidence)
                for ev in result.evidence:
                    if ev.category_code == "processed":
                        continue
                    cursor.execute("""
                        INSERT INTO document_evidence
                        (procurement_id, queue_id, category_code, evidence_score, match_count, next_stage, validation_status, validation_version, validation_method, pipeline_generation)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (procurement_id, category_code, pipeline_generation)
                        DO UPDATE SET
                            evidence_score = EXCLUDED.evidence_score,
                            match_count = EXCLUDED.match_count,
                            validation_status = EXCLUDED.validation_status,
                            validation_version = EXCLUDED.validation_version,
                            validation_method = EXCLUDED.validation_method
                            
                    """, (
                        result.procurement_id, result.queue_id, ev.category_code,
                        ev.evidence_score, ev.match_count, ev.next_stage,
                        getattr(ev, "validation_status", "CONFIRMED") or "CONFIRMED",
                        getattr(ev, "validation_version", "v1") or "v1",
                        getattr(ev, "validation_method", None),
                        self.pipeline_generation
                    ))

                cursor.execute(
                    "SELECT COUNT(*) FROM document_processing_results WHERE queue_id=%s AND pipeline_generation=%s",
                    (result.queue_id, self.pipeline_generation),
                )
                result_count = int(cursor.fetchone()[0])
                if result_count < 1:
                    raise RuntimeError(
                        f"[{self.pipeline_generation}] result graph absent for queue={result.queue_id}"
                    )

                # 4. Final step: Update queue to COMPLETED only after graph proof.
                cursor.execute("""
                    UPDATE document_processing_queue
                    SET status = 'COMPLETED', completed_at = NOW(), last_error = %s
                    WHERE id = %s
                """, (result.error_message, result.queue_id))

            logger.info(f"Task {result.queue_id} successfully persisted with outcome {result.outcome}.")
        except Exception as e:
            logger.error(f"Failed to persist task {result.queue_id}: {e}", exc_info=True)
            self.mark_failed(result.queue_id, str(e))
            raise

    def _resolve_document_file_id(self, cursor, queue_id: int, file_res) -> Optional[int]:
        """
        Resolve persisted document_files identity for a parser result.

        document_files is the source-download table. Archive-derived children are
        intentionally anchored to their parent source archive row; the child
        identity is stored in document_processing_results/document_matches.
        """
        archive_member_path = getattr(file_res, "archive_member_path", None)
        parent_local_path = getattr(file_res, "parent_local_path", None)
        parent_file_name = getattr(file_res, "parent_file_name", None)
        local_path = getattr(file_res, "local_path", None)

        if archive_member_path:
            if parent_local_path:
                cursor.execute("""
                    SELECT id FROM document_files
                    WHERE queue_id = %s
                      AND local_path = %s
                      AND pipeline_generation = %s
                    ORDER BY id DESC
                    LIMIT 1
                """, (queue_id, parent_local_path, self.pipeline_generation))
                row = cursor.fetchone()
                if row:
                    return row[0]

            if parent_file_name:
                cursor.execute("""
                    SELECT id FROM document_files
                    WHERE queue_id = %s
                      AND file_name = %s
                      AND pipeline_generation = %s
                    ORDER BY id DESC
                    LIMIT 1
                """, (queue_id, parent_file_name, self.pipeline_generation))
                row = cursor.fetchone()
                if row:
                    return row[0]

            # Never fall back to the derived child basename. That was the bug:
            # archive members do not have document_files rows.
            return None

        if local_path:
            cursor.execute("""
                SELECT id FROM document_files
                WHERE queue_id = %s
                  AND local_path = %s
                  AND pipeline_generation = %s
                ORDER BY id DESC
                LIMIT 1
            """, (queue_id, local_path, self.pipeline_generation))
            row = cursor.fetchone()
            if row:
                return row[0]

        cursor.execute("""
            SELECT id FROM document_files
            WHERE queue_id = %s
              AND file_name = %s
              AND pipeline_generation = %s
            ORDER BY id DESC
            LIMIT 1
        """, (queue_id, file_res.file_name, self.pipeline_generation))
        row = cursor.fetchone()
        return row[0] if row else None

    def mark_failed(self, queue_id: int, error_msg: str):
        try:
            with self.db.get_cursor('document_intelligence') as cursor:
                cursor.execute("""
                    UPDATE document_processing_queue
                    SET status = 'FAILED', last_error = %s
                    WHERE id = %s AND pipeline_generation = %s
                """, (error_msg, queue_id, self.pipeline_generation))
        except Exception as e:
            logger.error(f"Failed to mark queue {queue_id} as FAILED: {e}", exc_info=True)
