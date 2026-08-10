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
    def __init__(self, local_db_pool):
        self.db_pool = local_db_pool

    def persist_task_result(self, result: TaskProcessResult):
        """
        Persist the full object graph of a TaskProcessResult atomically.
        """
        conn = self.db_pool.getconn()
        try:
            with conn.cursor() as cursor:
                # 1. Select for update to ensure we own the task and it's PROCESSING
                cursor.execute("""
                    SELECT status
                    FROM document_processing_queue
                    WHERE id = %s AND pipeline_generation = 'S13_V2'
                    FOR UPDATE NOWAIT
                """, (result.queue_id,))

                row = cursor.fetchone()
                if not row:
                    logger.warning(f"Queue task {result.queue_id} not found or not S13_V2.")
                    conn.rollback()
                    return

                if row[0] != 'PROCESSING':
                    logger.warning(f"Queue task {result.queue_id} is in status {row[0]}, expected PROCESSING.")
                    conn.rollback()
                    return

                # 2. Persist File Process Results
                for file_res in result.files:
                    cursor.execute("""
                        UPDATE document_files
                        SET download_status = %s, error_message = %s
                        WHERE queue_id = %s AND file_name = %s AND pipeline_generation = 'S13_V2'
                        RETURNING id
                    """, (file_res.status, file_res.error_message, result.queue_id, file_res.file_name))

                    file_row = cursor.fetchone()
                    if not file_row:
                        pass

                    file_id = file_row[0] if file_row else None

                    if file_id and file_res.status == "COMPLETED":
                        # Insert document_processing_results
                        cursor.execute("""
                            INSERT INTO document_processing_results
                            (queue_id, procurement_id, file_id, parser_type, status, extracted_pages, extracted_sheets, extracted_rows, pipeline_generation)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'S13_V2')
                            RETURNING id
                        """, (
                            result.queue_id, result.procurement_id, file_id,
                            'S13_V2_PARSER', 'SUCCESS', file_res.pages, file_res.sheets, file_res.rows
                        ))
                        result_id = cursor.fetchone()[0]

                        # Persist matches and details
                        for match in file_res.matches:
                            cursor.execute("""
                                INSERT INTO document_matches
                                (queue_id, procurement_id, file_id, result_id, category_code, match_count, score, pipeline_generation)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, 'S13_V2')
                                RETURNING id
                            """, (
                                result.queue_id, result.procurement_id, file_id, result_id,
                                match.category_code, match.match_count, match.score
                            ))
                            match_id = cursor.fetchone()[0]

                            for detail in match.details:
                                cursor.execute("""
                                    INSERT INTO document_match_details
                                    (match_id, procurement_id, category_code, subcategory_code, matched_term, term_type, score, row_data, page_or_sheet, row_number, context_before, context_after, pipeline_generation)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'S13_V2')
                                """, (
                                    match_id, result.procurement_id, detail.category_code, detail.subcategory_code,
                                    detail.matched_term, detail.term_type, detail.score,
                                    json.dumps(detail.row_data), detail.page_or_sheet, detail.row_number,
                                    json.dumps(detail.context_before), json.dumps(detail.context_after)
                                ))

                # 3. Persist Evidence
                for ev in result.evidence:
                    cursor.execute("""
                        INSERT INTO document_evidence
                        (procurement_id, queue_id, match_id, category_code, evidence_score, match_count, next_stage, pipeline_generation)
                        VALUES (%s, %s, NULL, %s, %s, %s, %s, 'S13_V2')
                        ON CONFLICT (procurement_id, category_code, pipeline_generation)
                        DO UPDATE SET
                            evidence_score = EXCLUDED.evidence_score,
                            match_count = EXCLUDED.match_count,
                            updated_at = NOW()
                    """, (
                        result.procurement_id, result.queue_id, ev.category_code,
                        ev.evidence_score, ev.match_count, ev.next_stage
                    ))

                # 4. Final step: Update queue to COMPLETED
                cursor.execute("""
                    UPDATE document_processing_queue
                    SET status = %s, completed_at = NOW(), last_error = %s
                    WHERE id = %s
                """, (result.outcome.value, result.error_message, result.queue_id))

            conn.commit()
            logger.info(f"Task {result.queue_id} successfully persisted with outcome {result.outcome.value}.")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to persist task {result.queue_id}: {e}", exc_info=True)
            self.mark_failed(result.queue_id, str(e))
            raise
        finally:
            self.db_pool.putconn(conn)

    def mark_failed(self, queue_id: int, error_msg: str):
        fail_conn = self.db_pool.getconn()
        try:
            with fail_conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE document_processing_queue
                    SET status = 'FAILED', last_error = %s
                    WHERE id = %s AND pipeline_generation = 'S13_V2'
                """, (error_msg, queue_id))
            fail_conn.commit()
        except Exception as e:
            fail_conn.rollback()
            logger.error(f"Failed to mark queue {queue_id} as FAILED: {e}", exc_info=True)
        finally:
            self.db_pool.putconn(fail_conn)
