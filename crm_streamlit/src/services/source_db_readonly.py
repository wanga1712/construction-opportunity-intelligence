"""S7 tender_monitor is READ ONLY for the CRM application.

CRM derived state (match cache, priority hints, etc.) must use crm_db.
Source collectors on S7 are out of scope; CRM must not mutate source tables.
"""
from __future__ import annotations

import os
from typing import Any, List, Optional, Tuple, Union

from loguru import logger


class SourceDbWriteRejected(RuntimeError):
    """CRM attempted a write through the source (tender_monitor) role."""


_WRITE_HINTS = (
    " insert ",
    " update ",
    " delete ",
    " truncate ",
    " alter ",
    " drop ",
    " create ",
    " copy ",
    " merge ",
    " call ",
    " do ",
    " grant ",
    " revoke ",
    " vacuum ",
    " reindex ",
    " cluster ",
    " refresh material",
)


def looks_like_write_sql(sql: str) -> bool:
    """Conservative heuristic — not a security boundary alone.

    Prefer API separation + session default_transaction_read_only.
    """
    s = f" {(sql or '').strip().lower()} "
    if s.lstrip().startswith(" select ") or s.lstrip().startswith(" with "):
        # CTE may still write; treat WITH ... INSERT/UPDATE as write.
        if any(h in s for h in (" insert ", " update ", " delete ", " truncate ")):
            return True
        return False
    if s.lstrip().startswith(" explain "):
        return False
    if s.lstrip().startswith(" show "):
        return False
    return any(h in s for h in _WRITE_HINTS)


class SourceReadOnlyDatabase:
    """Wrap TenderDatabaseManager: SELECTs allowed, CRM writes rejected."""

    role = "source_db"
    readonly = True

    def __init__(self, inner: Any, *, enforce_session_readonly: bool = True):
        self._inner = inner
        self._enforce_session_readonly = enforce_session_readonly
        self._session_readonly_applied = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _reject(self, op: str) -> None:
        raise SourceDbWriteRejected(
            f"SOURCE_DB_READONLY: CRM must not {op} via tender_monitor/source_db. "
            "Use crm_db for CRM derived state."
        )

    def _apply_session_readonly(self) -> None:
        if not self._enforce_session_readonly or self._session_readonly_applied:
            return
        try:
            conn = self._inner.get_connection()
            if conn is None:
                return
            with conn.cursor() as cur:
                cur.execute("SET SESSION default_transaction_read_only = on")
            # Do not commit a write transaction; SET SESSION is OK on read-only.
            try:
                conn.commit()
            except Exception:
                pass
            self._session_readonly_applied = True
            logger.info("SOURCE_DB_READONLY: session default_transaction_read_only=on")
        except Exception as exc:
            logger.warning("SOURCE_DB_READONLY session apply failed: %s", exc)

    def connect(self, fallback_to_offline: bool = True) -> None:
        self._inner.connect(fallback_to_offline=fallback_to_offline)
        self._apply_session_readonly()

    def get_connection(self):
        self._apply_session_readonly()
        return self._inner.get_connection()

    def execute_update(
        self,
        query: str,
        params: Optional[Union[Tuple, List, dict]] = None,
        timeout: Optional[int] = None,
    ) -> bool:
        self._reject("execute_update")
        return False  # pragma: no cover

    def execute_batch(
        self,
        query: str,
        params_list: List[Union[Tuple, List, dict]],
        timeout: Optional[int] = None,
    ) -> bool:
        self._reject("execute_batch")
        return False  # pragma: no cover

    def execute_query(
        self,
        query: str,
        params: Optional[Union[Tuple, List, dict]] = None,
        fetch_results: bool = True,
        timeout: Optional[int] = None,
    ) -> Optional[List[Tuple]]:
        # Historical bug: some callers used execute_query for UPDATE.
        if looks_like_write_sql(query) and not fetch_results:
            self._reject("execute_query(write)")
        if looks_like_write_sql(query) and fetch_results:
            # SELECT ... FOR UPDATE / WITH writes — reject mutating forms.
            s = f" {(query or '').lower()} "
            if any(h in s for h in (" insert ", " update ", " delete ", " truncate ", " for update")):
                self._reject("execute_query(mutating)")
        self._apply_session_readonly()
        return self._inner.execute_query(query, params, fetch_results, timeout)

    def execute_scalar(
        self,
        query: str,
        params: Optional[Union[Tuple, List, dict]] = None,
        timeout: Optional[int] = None,
    ) -> Optional[Any]:
        if looks_like_write_sql(query):
            self._reject("execute_scalar(write)")
        self._apply_session_readonly()
        return self._inner.execute_scalar(query, params, timeout)


def wrap_source_db_readonly(tender_db: Any) -> Any:
    """Wrap tender manager unless explicitly disabled (tests may pass already-wrapped)."""
    if tender_db is None:
        return None
    if isinstance(tender_db, SourceReadOnlyDatabase):
        return tender_db
    if os.getenv("CRM_SOURCE_DB_READONLY", "1") != "1":
        logger.warning("CRM_SOURCE_DB_READONLY disabled — source writes not guarded")
        return tender_db
    return SourceReadOnlyDatabase(tender_db, enforce_session_readonly=True)


# DDL lives in src/migrations/crm_tender_match_cache_rehome_to_crm.sql only.
# Runtime must not CREATE/ALTER.


def require_match_cache_table(crm_db) -> None:
    """Fail-closed: match cache must already exist on crm_db."""
    from src.services.schema_guard import require_relations_or_raise

    require_relations_or_raise(crm_db, ["crm_tender_match_cache"])


def ensure_match_cache_table(crm_db) -> None:
    """Deprecated alias — check only, no DDL."""
    require_match_cache_table(crm_db)
