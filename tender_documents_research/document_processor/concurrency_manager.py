import contextvars
import os
import time
from contextlib import contextmanager
from typing import Generator

import psycopg2

from utils.logger_config import get_logger

from .eis_rate_limit_guard import get_eis_guard


_CURRENT_EIS_CONCURRENCY = contextvars.ContextVar(
    "current_eis_concurrency", default=0
)


def get_current_eis_concurrency() -> int:
    return int(_CURRENT_EIS_CONCURRENCY.get() or 0)


class DownloadCoordinator:
    """Server-wide EIS request start throttle and concurrency gate."""

    def __init__(self, db_alias: str = "tender_monitor"):
        self.logger = get_logger()
        self.db_alias = db_alias
        self.max_downloads = int(os.getenv("MAX_ACTIVE_DOWNLOADS", "2"))
        self.stagger_interval = (
            float(os.getenv("DOWNLOAD_STAGGER_INTERVAL_MS", "5000")) / 1000.0
        )
        self.guard = get_eis_guard()

    def _get_connection(self):
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
            port=port,
        )

    @contextmanager
    def acquire_slot(self) -> Generator[None, None, None]:
        """Acquire one global concurrency slot and enforce the shared stagger."""
        conn = None
        acquired_slot = None
        global_queue_locked = False
        try:
            conn = self._get_connection()
            conn.autocommit = True
            with conn.cursor() as cur:
                self.logger.debug(
                    "DownloadCoordinator: waiting in global queue (lock 13000)..."
                )
                cur.execute("SELECT pg_advisory_lock(13000)")
                global_queue_locked = True
                while acquired_slot is None:
                    for slot in range(13001, 13001 + self.max_downloads):
                        cur.execute("SELECT pg_try_advisory_lock(%s)", (slot,))
                        if cur.fetchone()[0]:
                            acquired_slot = slot
                            break
                    if acquired_slot is None:
                        time.sleep(0.5)
                cur.execute("SELECT pg_advisory_unlock(13000)")
                global_queue_locked = False
                self._throttle(cur)
            yield
        finally:
            if conn:
                try:
                    with conn.cursor() as cur:
                        if global_queue_locked:
                            cur.execute("SELECT pg_advisory_unlock(13000)")
                        if acquired_slot:
                            cur.execute(
                                "SELECT pg_advisory_unlock(%s)", (acquired_slot,)
                            )
                except Exception as exc:
                    self.logger.error(f"Error releasing advisory lock: {exc}")
                finally:
                    conn.close()

    @contextmanager
    def request_slot(self, request_type: str = "DOWNLOAD") -> Generator[None, None, None]:
        """Guard -> global throttle -> concurrency slot -> HTTP request."""
        self.guard.ensure_request_allowed(request_type)
        with self.acquire_slot():
            # A 429 may have arrived while this worker was waiting for a slot.
            self.guard.ensure_request_allowed(request_type)
            token = _CURRENT_EIS_CONCURRENCY.set(self.active_slots_count())
            try:
                yield
            finally:
                _CURRENT_EIS_CONCURRENCY.reset(token)

    def active_slots_count(self) -> int:
        try:
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT count(*)
                          FROM pg_locks
                         WHERE locktype = 'advisory'
                           AND objid >= 13001
                           AND objid < 13001 + %s
                           AND granted = true
                        """,
                        (self.max_downloads,),
                    )
                    return int(cur.fetchone()[0] or 0)
            finally:
                conn.close()
        except Exception as exc:
            self.logger.error(f"Error checking active download slots: {exc}")
            return 0

    def is_download_subsystem_busy(self) -> bool:
        return self.active_slots_count() >= self.max_downloads

    def is_eis_blocked(self) -> bool:
        return self.guard.is_blocked()

    def _throttle(self, cur):
        """Enforce one server-wide request start interval."""
        cur.execute("BEGIN")
        cur.execute(
            "SELECT last_start_at FROM download_throttle WHERE id = 1 FOR UPDATE"
        )
        row = cur.fetchone()
        if row:
            cur.execute("SELECT EXTRACT(EPOCH FROM (NOW() - %s))", (row[0],))
            elapsed = float(cur.fetchone()[0])
            if elapsed < self.stagger_interval:
                time.sleep(self.stagger_interval - elapsed)
        cur.execute("UPDATE download_throttle SET last_start_at = NOW() WHERE id = 1")
        cur.execute("COMMIT")
