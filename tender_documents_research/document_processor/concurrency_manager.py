import time
import os
import psycopg2
from typing import Generator
from contextlib import contextmanager
from utils.logger_config import get_logger

class DownloadCoordinator:
    def __init__(self, db_alias: str = "tender_monitor"):
        self.logger = get_logger()
        self.db_alias = db_alias
        self.max_downloads = int(os.getenv("MAX_ACTIVE_DOWNLOADS", "6"))
        self.stagger_interval = float(os.getenv("DOWNLOAD_STAGGER_INTERVAL_MS", "2500")) / 1000.0
        # For advisory lock we need a direct psycopg2 connection since we might need to block.
        # Alternatively, we just open a fresh connection here for the duration of the download.
        self._conn = None

    def _get_connection(self):
        # We parse the DB config from env as it's the simplest way to get an independent connection
        # to the same DB that holds the lock.
        # document_intelligence
        if os.getenv("PROCESSING_BACKEND") in ("S13_V2", "S13_V4"):
            host = os.getenv("S13_DOCUMENT_DB_HOST", "localhost")
            dbname = os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence")
            user = os.getenv("S13_DOCUMENT_DB_USER", "doc_worker")
            password = os.getenv("S13_DOCUMENT_DB_PASSWORD", "")
            port = os.getenv("S13_DOCUMENT_DB_PORT", "5432")
        else:
            host = os.getenv("DB_HOST_TENDER", "localhost")
            dbname = os.getenv("DB_DATABASE_TENDER", "document_intelligence")
            user = os.getenv("DB_USER_TENDER", "postgres")
            password = os.getenv("DB_PASSWORD_TENDER", "")
            port = os.getenv("DB_PORT_TENDER", "5432")
        
        return psycopg2.connect(
            host=host,
            dbname=dbname,
            user=user,
            password=password,
            port=port
        )

    @contextmanager
    def acquire_slot(self) -> Generator[None, None, None]:
        """
        1. Enters global queue (advisory lock 13000)
        2. Tries to acquire one of the MAX_ACTIVE_DOWNLOADS slots (13001-1300X)
        3. Releases global queue
        4. Throttle (staggered start)
        5. Yield to allow HTTP request
        6. Finally releases slot (13001-1300X)
        """
        conn = None
        acquired_slot = None
        global_queue_locked = False
        
        try:
            conn = self._get_connection()
            conn.autocommit = True
            with conn.cursor() as cur:
                # 1. Join the queue to ensure fairness (FIFO via postgres lock)
                self.logger.debug("DownloadCoordinator: waiting in global queue (lock 13000)...")
                cur.execute("SELECT pg_advisory_lock(13000)")
                global_queue_locked = True
                self.logger.debug("DownloadCoordinator: entered global queue.")

                # 2. Wait for a free slot
                while acquired_slot is None:
                    for slot in range(13001, 13001 + self.max_downloads):
                        cur.execute("SELECT pg_try_advisory_lock(%s)", (slot,))
                        if cur.fetchone()[0]:
                            acquired_slot = slot
                            break
                    if acquired_slot is None:
                        # All slots busy, wait a bit
                        time.sleep(0.5)

                self.logger.debug(f"DownloadCoordinator: acquired slot {acquired_slot}")
                
                # 3. Leave the queue
                cur.execute("SELECT pg_advisory_unlock(13000)")
                global_queue_locked = False

                # 4. Enforce staggered start
                self._throttle(cur)
            
            yield
        finally:
            # 6. Release slot
            if conn:
                try:
                    with conn.cursor() as cur:
                        if global_queue_locked:
                            cur.execute("SELECT pg_advisory_unlock(13000)")
                        if acquired_slot:
                            cur.execute("SELECT pg_advisory_unlock(%s)", (acquired_slot,))
                except Exception as e:
                    self.logger.error(f"Error releasing advisory lock: {e}")
                finally:
                    conn.close()

    def is_download_subsystem_busy(self) -> bool:
        """
        Returns True if all slots are currently taken by other workers.
        This allows the daemon to pause before claiming a new task.
        """
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT count(*)
                    FROM pg_locks
                    WHERE locktype = 'advisory'
                      AND objid >= 13001
                      AND objid < 13001 + %s
                      AND granted = true;
                """, (self.max_downloads,))
                active = cur.fetchone()[0]
                return active >= self.max_downloads
        except Exception as e:
            self.logger.error(f"Error checking download subsystem: {e}")
            return False
        finally:
            if 'conn' in locals() and conn:
                conn.close()

    def _throttle(self, cur):
        """Enforces the global interval between downloads."""
        # We need a transaction to lock the row for update
        cur.execute("BEGIN")
        cur.execute("SELECT last_start_at FROM download_throttle WHERE id = 1 FOR UPDATE")
        row = cur.fetchone()
        if row:
            last_start = row[0]
            # Calculate how much time passed since last start
            cur.execute("SELECT EXTRACT(EPOCH FROM (NOW() - %s))", (last_start,))
            elapsed = float(cur.fetchone()[0])
            
            if elapsed < self.stagger_interval:
                sleep_time = self.stagger_interval - elapsed
                self.logger.debug(f"DownloadCoordinator: throttling for {sleep_time:.2f}s")
                time.sleep(sleep_time)
            
        cur.execute("UPDATE download_throttle SET last_start_at = NOW() WHERE id = 1")
        cur.execute("COMMIT")
