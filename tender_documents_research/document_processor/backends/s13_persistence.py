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
    def __init__(self, db: DatabaseManager):
        self.db = db

    def persist_task_result(self, result: TaskProcessResult):
        """
        Persist the full object graph of a TaskProcessResult atomically.
        """
        conn = self.db.get_connection('document_intelligence')
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

                if row[0] not in ('PROCESSING', 'processing'):
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
                            (queue_id, procurement_id, file_id, status, pages_processed, sheets_processed, rows_extracted, matches_found, pipeline_generation)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'S13_V2')
                            RETURNING id
                        """, (
                            result.queue_id, result.procurement_id, file_id,
                            'COMPLETED', file_res.pages, file_res.sheets, file_res.rows, sum(m.match_count for m in file_res.matches)
                        ))
                        result_id = cursor.fetchone()[0]

                        # Persist matches and details
                        # Match rows correspond to file-level aggregates here. 
                        # In the new schema, category_code moved to details, so match is just an aggregate container.
                        # Wait, the old match table had category_code. If we don't have it, we insert one match per file and then all details under it.
                        
                        # Calculate total match count and max score for this file
                        file_matches = file_res.matches
                        if file_matches:
                            total_matches = sum(m.match_count for m in file_matches)
                            max_score = max(m.score for m in file_matches)
                            
                            cursor.execute("""
                                INSERT INTO document_matches
                                (queue_id, procurement_id, file_id, result_id, match_count, score, pipeline_generation)
                                VALUES (%s, %s, %s, %s, %s, %s, 'S13_V2')
                                RETURNING id
                            """, (
                                result.queue_id, result.procurement_id, file_id, result_id,
                                total_matches, max_score
                            ))
                            match_id = cursor.fetchone()[0]

                            for match in file_matches:
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
                        (procurement_id, queue_id, category_code, evidence_score, match_count, next_stage, pipeline_generation)
                        VALUES (%s, %s, %s, %s, %s, %s, 'S13_V2')
                        ON CONFLICT (procurement_id, category_code, pipeline_generation)
                        DO UPDATE SET
                            evidence_score = EXCLUDED.evidence_score,
                            match_count = EXCLUDED.match_count
                            
                    """, (
                        result.procurement_id, result.queue_id, ev.category_code,
                        ev.evidence_score, ev.match_count, ev.next_stage
                    ))

                # 4. Final step: Update queue to COMPLETED
                cursor.execute("""
                    UPDATE document_processing_queue
                    SET status = %s, completed_at = NOW(), last_error = %s
                    WHERE id = %s
                """, (result.outcome.value if hasattr(result.outcome, 'value') else result.outcome, result.error_message, result.queue_id))

            conn.commit()
            logger.info(f"Task {result.queue_id} successfully persisted with outcome {result.outcome}.")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to persist task {result.queue_id}: {e}", exc_info=True)
            self.mark_failed(result.queue_id, str(e))
            raise
        finally:
            self.db.return_connection('document_intelligence', conn)

    def mark_failed(self, queue_id: int, error_msg: str):
        fail_conn = self.db.get_connection('document_intelligence')
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
            self.db.return_connection('document_intelligence', fail_conn)
