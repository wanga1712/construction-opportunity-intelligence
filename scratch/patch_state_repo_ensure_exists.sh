#!/bin/bash
python3 << 'PYEOF'
filepath = '/opt/CRM_Streamlit/tender_documents_research/document_processor/backends/state_repository.py'
with open(filepath, 'r') as f:
    content = f.read()

# Locate S13V2StateRepository class block
start_idx = content.find('class S13V2StateRepository(ProcessingStateRepository):')
if start_idx == -1:
    print("S13V2StateRepository class not found!")
    exit(1)

# We want to replace everything from class S13V2StateRepository(ProcessingStateRepository): to the end of the file
header = content[:start_idx]

replacement = '''class S13V2StateRepository(ProcessingStateRepository):
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

    def _get_actual_generation(self, procurement_id: int) -> str:
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT pipeline_generation FROM document_processing_queue
                    WHERE procurement_id = %s
                    ORDER BY (status = 'PROCESSING') DESC, id DESC
                    LIMIT 1
                """, (procurement_id,))
                row = cur.fetchone()
                if row:
                    return row[0]
        except Exception:
            pass
        return self.pipeline_generation

    def _ensure_file_exists(self, procurement_id: int, table_source: str, file_name: str, url_hash: Optional[str] = None) -> str:
        import hashlib
        if not url_hash:
            url_hash = hashlib.sha256(f"{procurement_id}_{file_name}".encode('utf-8')).hexdigest()
            
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                # 1. Query actual generation and queue details
                cur.execute("""
                    SELECT id, source_id, pipeline_generation FROM document_processing_queue
                    WHERE procurement_id = %s
                    ORDER BY (status = 'PROCESSING') DESC, id DESC
                    LIMIT 1
                """, (procurement_id,))
                q_row = cur.fetchone()
                queue_id = q_row[0] if q_row else None
                source_id = q_row[1] if q_row else None
                actual_gen = q_row[2] if q_row else self.pipeline_generation

                # 2. Check if file already exists
                cur.execute("""
                    SELECT id FROM document_files
                    WHERE url_hash = %s AND pipeline_generation = %s
                    LIMIT 1
                """, (url_hash, actual_gen))
                row = cur.fetchone()
                if row:
                    return actual_gen

                # 3. Insert if missing
                sql = """
                    INSERT INTO document_files (
                        queue_id, procurement_id, source_table, source_id,
                        url, url_hash, file_name, download_status, pipeline_generation,
                        created_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, 'PENDING', %s,
                        NOW()
                    )
                    ON CONFLICT (url_hash, pipeline_generation) DO UPDATE SET
                        queue_id = EXCLUDED.queue_id,
                        procurement_id = EXCLUDED.procurement_id
                """
                url = f"https://zakupki.gov.ru/dummy/{url_hash}"
                cur.execute(sql, (
                    queue_id, procurement_id, table_source, source_id,
                    url, url_hash, file_name, actual_gen
                ))
            conn.commit()
            return actual_gen
        except Exception as e:
            try:
                self._get_conn().rollback()
            except Exception:
                pass
            self.logger.error(f"Error ensuring file exists: {e}")
            return self.pipeline_generation

    def get_file_status(self, procurement_id: int, table_source: str, file_name: str, url_hash: str) -> Optional[Tuple[str]]:
        import hashlib
        if not url_hash:
            url_hash = hashlib.sha256(f"{procurement_id}_{file_name}".encode('utf-8')).hexdigest()
            
        actual_gen = self._get_actual_generation(procurement_id)
        sql = """
            SELECT download_status
            FROM document_files
            WHERE url_hash = %s AND pipeline_generation = %s
            LIMIT 1
        """
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(sql, (url_hash, actual_gen))
                row = cur.fetchone()
                if row:
                    return (row[0],)
        except Exception as e:
            self.logger.error(f"Error checking local document_files state: {e}")
            raise e
        return None

    def mark_file_status(self, procurement_id: int, table_source: str, file_name: str, url_hash: str, status: str, worker_id: int = None):
        import hashlib
        if not url_hash:
            url_hash = hashlib.sha256(f"{procurement_id}_{file_name}".encode('utf-8')).hexdigest()
            
        # Normalize status to match check constraint
        status = status.upper() if status else 'PENDING'
        if status not in ('PENDING', 'COMPLETED', 'FAILED', 'SKIPPED'):
            status = 'PENDING'
            
        actual_gen = self._ensure_file_exists(procurement_id, table_source, file_name, url_hash)
        
        sql = """
            UPDATE document_files
            SET download_status = %s,
                worker_id = COALESCE(%s, worker_id)
            WHERE url_hash = %s AND pipeline_generation = %s
        """
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(sql, (status, worker_id, url_hash, actual_gen))
            conn.commit()
        except Exception as e:
            self.logger.error(f"Error marking local document_files state: {e}")
            raise e

    def finalize_file_status(self, procurement_id: int, table_source: str, file_name: str, *args, **kwargs):
        url_hash = None
        success = True
        error_message = None
        
        if len(args) == 2:
            success = args[0]
            error_message = args[1]
        elif len(args) >= 3:
            url_hash = args[0]
            success = args[1]
            error_message = args[2]
        else:
            url_hash = kwargs.get('url_hash')
            success = kwargs.get('success', True)
            error_message = kwargs.get('error_message')

        import hashlib
        if not url_hash:
            url_hash = hashlib.sha256(f"{procurement_id}_{file_name}".encode('utf-8')).hexdigest()
            
        actual_gen = self._ensure_file_exists(procurement_id, table_source, file_name, url_hash)
        
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
                cur.execute(sql, (status, error_message, url_hash, actual_gen))
            conn.commit()
        except Exception as e:
            self.logger.error(f"Error finalizing local document_files state: {e}")
            raise e

    # ─── Resumable download stubs (S13_V2 clean-slate: no resume logic needed) ─
    def get_progress_cursor(self, tender_id: int, table_source: str, file_name: str):
        return None

    def get_processed_status(self, tender_id: int, table_source: str, file_name: str):
        return None

    def mark_pending_resume(self, tender_id: int, table_source: str, file_name: str, cursor, error_message: str = None) -> int:
        return 0

    def mark_error_memory(self, tender_id: int, table_source: str, file_name: str, error_message: str):
        pass
    # ─────────────────────────────────────────────────────────────────────────

    def list_file_statuses(self, procurement_id: int, table_source: str, raise_on_error: bool = False):
        actual_gen = self._get_actual_generation(procurement_id)
        sql = """
            SELECT file_name, download_status
            FROM document_files
            WHERE procurement_id = %s AND pipeline_generation = %s
        """
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(sql, (procurement_id, actual_gen))
                rows = cur.fetchall()
                return [(r[0], r[1]) for r in rows]
        except Exception as e:
            self.logger.error(f"Error listing local document_files statuses: {e}")
            if raise_on_error: raise e
            return []

    def reset_stale(self, worker_id: int) -> int:
        return 0
'''

new_content = header + replacement
with open(filepath, 'w') as f:
    f.write(new_content)
print("SUCCESS: State Repository fully patched and updated.")
PYEOF

python3 -m py_compile /opt/CRM_Streamlit/tender_documents_research/document_processor/backends/state_repository.py && echo "SYNTAX_OK"
