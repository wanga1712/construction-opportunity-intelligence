"""Persistence and telemetry for the global EIS rate-limit guard."""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import psycopg2
import psycopg2.extras

EIS_HOST = "zakupki.gov.ru"
EIS_RECOVERY_PROBE_LOCK = 13010


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_document_dsn() -> dict:
    """Resolve the document DB from the same env used by the worker backend."""
    return {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "localhost"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }


class MemoryEisStateStore:
    """Small in-memory implementation used by targeted tests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._probe_lock = threading.Lock()
        self._states: Dict[str, Dict[str, Any]] = {}
        self._requests: list[Dict[str, Any]] = []
        self._files: list[Dict[str, Any]] = []
        self._incidents: list[Dict[str, Any]] = []
        self._next_request_id = 1

    def _state(self, host: str) -> Dict[str, Any]:
        return self._states.setdefault(
            host,
            {
                "host": host,
                "blocked_until": None,
                "blocked_since": None,
                "last_429_at": None,
                "last_429_xid": None,
                "last_retry_after": None,
                "last_probe_at": None,
                "last_probe_status": None,
                "consecutive_blocks": 0,
                "updated_at": None,
            },
        )

    def fetch_state(self, host: str) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state(host))

    def apply_429(
        self,
        host: str,
        now: datetime,
        retry_after: Optional[int],
        xid: Optional[str],
        snapshot: Dict[str, Any],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        with self._lock:
            state = self._state(host)
            cooldown = max(3600, int(retry_after or 0))
            state.update(
                blocked_since=state.get("blocked_since") or now,
                blocked_until=now + timedelta(seconds=cooldown),
                last_429_at=now,
                last_429_xid=xid,
                last_retry_after=retry_after,
                consecutive_blocks=int(state.get("consecutive_blocks") or 0) + 1,
                updated_at=now,
            )
            open_incident = next(
                (row for row in reversed(self._incidents) if row["block_ended_at"] is None),
                None,
            )
            if open_incident is None:
                open_incident = {
                    "incident_id": len(self._incidents) + 1,
                    "host": host,
                    "first_429_at": now,
                    "xid": xid,
                    "retry_after": retry_after,
                    "block_started_at": state["blocked_since"],
                    "block_ended_at": None,
                    "created_at": now,
                }
                self._incidents.append(open_incident)
            open_incident.update(snapshot)
            open_incident.update(config)
            open_incident["probe_at"] = None
            open_incident["probe_result"] = None
            return dict(state)

    def apply_probe_started(self, host: str, now: datetime) -> None:
        with self._lock:
            state = self._state(host)
            state["last_probe_at"] = now
            state["last_probe_status"] = "IN_PROGRESS"
            state["updated_at"] = now
            incident = next(
                (row for row in reversed(self._incidents) if row["block_ended_at"] is None),
                None,
            )
            if incident is not None:
                incident["probe_at"] = now
                incident["probe_result"] = "IN_PROGRESS"

    def apply_probe_success(self, host: str, now: datetime) -> Dict[str, Any]:
        with self._lock:
            state = self._state(host)
            state.update(
                blocked_until=None,
                blocked_since=None,
                last_probe_at=now,
                last_probe_status="SUCCESS",
                updated_at=now,
            )
            incident = next(
                (row for row in reversed(self._incidents) if row["block_ended_at"] is None),
                None,
            )
            if incident is not None:
                started = incident.get("block_started_at") or now
                incident.update(
                    block_ended_at=now,
                    block_duration_minutes=round((now - started).total_seconds() / 60.0, 2),
                    probe_result="SUCCESS",
                )
            return dict(state)

    def apply_probe_status(self, host: str, now: datetime, status: str) -> None:
        with self._lock:
            state = self._state(host)
            state["last_probe_at"] = now
            state["last_probe_status"] = status
            state["updated_at"] = now
            incident = next(
                (row for row in reversed(self._incidents) if row["block_ended_at"] is None),
                None,
            )
            if incident is not None:
                incident["probe_at"] = now
                incident["probe_result"] = status

    def apply_probe_error(
        self, host: str, now: datetime, status: str, retry_seconds: int
    ) -> None:
        with self._lock:
            state = self._state(host)
            state["last_probe_at"] = now
            state["last_probe_status"] = status
            state["blocked_until"] = now + timedelta(seconds=max(1, retry_seconds))
            state["updated_at"] = now
            incident = next(
                (row for row in reversed(self._incidents) if row["block_ended_at"] is None),
                None,
            )
            if incident is not None:
                incident["probe_at"] = now
                incident["probe_result"] = status

    def record_request_start(
        self, host: str, request_type: str, url: str, concurrency: int, now: datetime
    ) -> int:
        with self._lock:
            event_id = self._next_request_id
            self._next_request_id += 1
            self._requests.append(
                {
                    "id": event_id,
                    "host": host,
                    "request_type": request_type,
                    "requested_at": now,
                    "finished_at": None,
                    "http_status": None,
                    "bytes_received": None,
                    "duration_ms": None,
                    "url": url,
                    "xid": None,
                    "retry_after": None,
                    "concurrency_at_start": concurrency,
                    "error_class": None,
                }
            )
            return event_id

    def record_request_finish(
        self,
        event_id: int,
        status: Optional[int],
        bytes_received: Optional[int],
        duration_ms: Optional[int],
        xid: Optional[str] = None,
        retry_after: Optional[int] = None,
        error_class: Optional[str] = None,
    ) -> None:
        with self._lock:
            for row in self._requests:
                if row["id"] == event_id:
                    row.update(
                        finished_at=_utcnow(),
                        http_status=status,
                        bytes_received=bytes_received,
                        duration_ms=duration_ms,
                        xid=xid,
                        retry_after=retry_after,
                        error_class=error_class,
                    )
                    return

    def record_file_event(self, **event: Any) -> None:
        with self._lock:
            event.setdefault("requested_at", _utcnow())
            self._files.append(event)

    def _window_counts(self, rows: list[Dict[str, Any]], now: datetime) -> Dict[str, int]:
        cutoffs = {
            "1m": now - timedelta(minutes=1),
            "5m": now - timedelta(minutes=5),
            "15m": now - timedelta(minutes=15),
            "60m": now - timedelta(minutes=60),
        }
        return {
            key: sum(1 for row in rows if row["requested_at"] >= cutoff)
            for key, cutoff in cutoffs.items()
        }

    def telemetry_snapshot(self, host: str, now: datetime) -> Dict[str, Any]:
        with self._lock:
            requests = self._window_counts(self._requests, now)
            attempted = [row for row in self._files if row.get("result") == "ATTEMPTED"]
            files = self._window_counts(attempted, now)
            bytes_last_60m = sum(
                int(row.get("bytes_received") or 0)
                for row in self._files
                if row["result"] == "DOWNLOADED"
                and row["requested_at"] >= now - timedelta(minutes=60)
            )
            return {
                "requests_last_1m": requests["1m"],
                "requests_last_5m": requests["5m"],
                "requests_last_15m": requests["15m"],
                "requests_last_60m": requests["60m"],
                "files_last_1m": files["1m"],
                "files_last_5m": files["5m"],
                "files_last_60m": files["60m"],
                "bytes_last_60m": bytes_last_60m,
            }

    def operational_snapshot(self, host: str, now: datetime) -> Dict[str, Any]:
        with self._lock:
            recent = [r for r in self._requests if r["requested_at"] >= now - timedelta(minutes=5)]
            files = [r for r in self._files if r["requested_at"] >= now - timedelta(minutes=5)]
            return {
                "requests_5m": len(recent),
                "files_5m": sum(1 for r in files if r["result"] == "DOWNLOADED"),
                "bytes_5m": sum(int(r.get("bytes_received") or 0) for r in files),
                "429_5m": sum(1 for r in recent if r.get("http_status") == 429),
                "requests_since_block": 0,
            }

    @contextmanager
    def try_probe_lock(self):
        acquired = self._probe_lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                self._probe_lock.release()


class _PostgresProbeLock:
    def __init__(self, store: "PostgresEisStateStore") -> None:
        self.store = store
        self.conn = None
        self.acquired = False

    def __enter__(self) -> bool:
        self.conn = self.store._new_connection()
        self.conn.autocommit = True
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (EIS_RECOVERY_PROBE_LOCK,))
                self.acquired = bool(cur.fetchone()[0])
        except Exception:
            self.conn.close()
            self.conn = None
            raise
        if not self.acquired:
            self.conn.close()
            self.conn = None
        return self.acquired

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.conn is not None:
            try:
                if self.acquired:
                    with self.conn.cursor() as cur:
                        cur.execute("SELECT pg_advisory_unlock(%s)", (EIS_RECOVERY_PROBE_LOCK,))
            finally:
                self.conn.close()


class PostgresEisStateStore:
    """PostgreSQL-backed authority for EIS rate-limit state and telemetry."""

    def __init__(self, dsn: Optional[dict] = None) -> None:
        self._dsn = dsn or load_document_dsn()
        self._local = threading.local()

    def _new_connection(self):
        conn = psycopg2.connect(**self._dsn)
        conn.autocommit = False
        return conn

    def _conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is None or conn.closed:
            conn = self._new_connection()
            self._local.conn = conn
        return conn

    @contextmanager
    def _tx(self):
        conn = self._conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    @staticmethod
    def _as_dict(row) -> Optional[Dict[str, Any]]:
        return dict(row) if row else None

    def fetch_state(self, host: str) -> Dict[str, Any]:
        with self._tx() as cur:
            cur.execute("SELECT * FROM eis_rate_limit_state WHERE host=%s", (host,))
            return self._as_dict(cur.fetchone()) or {"host": host}

    def apply_429(
        self,
        host: str,
        now: datetime,
        retry_after: Optional[int],
        xid: Optional[str],
        snapshot: Dict[str, Any],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        cooldown = max(3600, int(retry_after or 0))
        with self._tx() as cur:
            cur.execute(
                "SELECT * FROM eis_rate_limit_state WHERE host=%s FOR UPDATE", (host,)
            )
            current = self._as_dict(cur.fetchone())
            if current is None:
                cur.execute(
                    "INSERT INTO eis_rate_limit_state (host) VALUES (%s) "
                    "ON CONFLICT (host) DO NOTHING",
                    (host,),
                )
                cur.execute(
                    "SELECT * FROM eis_rate_limit_state WHERE host=%s FOR UPDATE", (host,)
                )
                current = self._as_dict(cur.fetchone())
            blocked_since = current.get("blocked_since") or now
            cur.execute(
                """
                UPDATE eis_rate_limit_state
                   SET blocked_since=%s,
                       blocked_until=%s,
                       last_429_at=%s,
                       last_429_xid=%s,
                       last_retry_after=%s,
                       consecutive_blocks=consecutive_blocks+1,
                       updated_at=%s
                 WHERE host=%s
             RETURNING *
                """,
                (
                    blocked_since,
                    now + timedelta(seconds=cooldown),
                    now,
                    xid,
                    retry_after,
                    now,
                    host,
                ),
            )
            state = self._as_dict(cur.fetchone())
            cur.execute(
                """
                SELECT incident_id FROM eis_rate_limit_incidents
                 WHERE host=%s AND block_ended_at IS NULL
                 ORDER BY incident_id DESC LIMIT 1
                 FOR UPDATE
                """,
                (host,),
            )
            incident = cur.fetchone()
            if incident:
                cur.execute(
                    """
                    UPDATE eis_rate_limit_incidents
                       SET xid=%s,
                           retry_after=%s,
                           requests_last_1m=%s,
                           requests_last_5m=%s,
                           requests_last_15m=%s,
                           requests_last_60m=%s,
                           files_last_1m=%s,
                           files_last_5m=%s,
                           files_last_60m=%s,
                           bytes_last_60m=%s,
                           active_downloads_at_429=%s,
                           configured_max_downloads=%s,
                           configured_stagger_ms=%s,
                           probe_at=NULL,
                           probe_result=NULL
                     WHERE incident_id=%s
                    """,
                    (
                        xid,
                        retry_after,
                        snapshot["requests_last_1m"],
                        snapshot["requests_last_5m"],
                        snapshot["requests_last_15m"],
                        snapshot["requests_last_60m"],
                        snapshot["files_last_1m"],
                        snapshot["files_last_5m"],
                        snapshot["files_last_60m"],
                        snapshot["bytes_last_60m"],
                        config["active_downloads_at_429"],
                        config["configured_max_downloads"],
                        config["configured_stagger_ms"],
                        incident["incident_id"],
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO eis_rate_limit_incidents (
                        host, first_429_at, xid, retry_after,
                        requests_last_1m, requests_last_5m, requests_last_15m,
                        requests_last_60m, files_last_1m, files_last_5m,
                        files_last_60m, bytes_last_60m, active_downloads_at_429,
                        configured_max_downloads, configured_stagger_ms,
                        block_started_at
                    ) VALUES (
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                    )
                    """,
                    (
                        host,
                        now,
                        xid,
                        retry_after,
                        snapshot["requests_last_1m"],
                        snapshot["requests_last_5m"],
                        snapshot["requests_last_15m"],
                        snapshot["requests_last_60m"],
                        snapshot["files_last_1m"],
                        snapshot["files_last_5m"],
                        snapshot["files_last_60m"],
                        snapshot["bytes_last_60m"],
                        config["active_downloads_at_429"],
                        config["configured_max_downloads"],
                        config["configured_stagger_ms"],
                        blocked_since,
                    ),
                )
            return state

    def apply_probe_started(self, host: str, now: datetime) -> None:
        with self._tx() as cur:
            cur.execute(
                "UPDATE eis_rate_limit_state SET last_probe_at=%s, "
                "last_probe_status='IN_PROGRESS', updated_at=%s WHERE host=%s",
                (now, now, host),
            )
            cur.execute(
                "UPDATE eis_rate_limit_incidents SET probe_at=%s, probe_result='IN_PROGRESS' "
                "WHERE host=%s AND block_ended_at IS NULL",
                (now, host),
            )

    def apply_probe_success(self, host: str, now: datetime) -> Dict[str, Any]:
        with self._tx() as cur:
            cur.execute(
                """
                UPDATE eis_rate_limit_state
                   SET blocked_until=NULL, blocked_since=NULL,
                       last_probe_at=%s, last_probe_status='SUCCESS', updated_at=%s
                 WHERE host=%s RETURNING *
                """,
                (now, now, host),
            )
            state = self._as_dict(cur.fetchone()) or {"host": host}
            cur.execute(
                """
                UPDATE eis_rate_limit_incidents
                   SET block_ended_at=%s,
                       block_duration_minutes=ROUND(
                           EXTRACT(EPOCH FROM (%s - COALESCE(block_started_at, first_429_at))) / 60.0,
                           2
                       ),
                       probe_result='SUCCESS'
                 WHERE host=%s AND block_ended_at IS NULL
                """,
                (now, now, host),
            )
            return state

    def apply_probe_status(self, host: str, now: datetime, status: str) -> None:
        with self._tx() as cur:
            cur.execute(
                "UPDATE eis_rate_limit_state SET last_probe_at=%s, last_probe_status=%s, "
                "updated_at=%s WHERE host=%s",
                (now, status, now, host),
            )
            cur.execute(
                "UPDATE eis_rate_limit_incidents SET probe_at=%s, probe_result=%s "
                "WHERE host=%s AND block_ended_at IS NULL",
                (now, status, host),
            )

    def apply_probe_error(
        self, host: str, now: datetime, status: str, retry_seconds: int
    ) -> None:
        with self._tx() as cur:
            cur.execute(
                "UPDATE eis_rate_limit_state SET last_probe_at=%s, last_probe_status=%s, "
                "blocked_until=%s, updated_at=%s WHERE host=%s",
                (now, status, now + timedelta(seconds=max(1, retry_seconds)), now, host),
            )
            cur.execute(
                "UPDATE eis_rate_limit_incidents SET probe_at=%s, probe_result=%s "
                "WHERE host=%s AND block_ended_at IS NULL",
                (now, status, host),
            )

    def record_request_start(
        self, host: str, request_type: str, url: str, concurrency: int, now: datetime
    ) -> int:
        with self._tx() as cur:
            cur.execute(
                """
                INSERT INTO eis_request_events
                    (host, request_type, requested_at, url, concurrency_at_start)
                VALUES (%s,%s,%s,%s,%s) RETURNING id
                """,
                (host, request_type, now, url, concurrency),
            )
            return int(cur.fetchone()["id"])

    def record_request_finish(
        self,
        event_id: int,
        status: Optional[int],
        bytes_received: Optional[int],
        duration_ms: Optional[int],
        xid: Optional[str] = None,
        retry_after: Optional[int] = None,
        error_class: Optional[str] = None,
    ) -> None:
        with self._tx() as cur:
            cur.execute(
                """
                UPDATE eis_request_events
                   SET finished_at=NOW(), http_status=%s, bytes_received=%s,
                       duration_ms=%s, xid=%s, retry_after=%s, error_class=%s
                 WHERE id=%s
                """,
                (status, bytes_received, duration_ms, xid, retry_after, error_class, event_id),
            )

    def record_file_event(self, **event: Any) -> None:
        with self._tx() as cur:
            cur.execute(
                """
                INSERT INTO eis_file_events (
                    host, result, source_url, url_hash, file_name, bytes_received,
                    error_class, http_status, retry_after, xid, duration_ms
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    event.get("host", EIS_HOST),
                    event.get("result"),
                    event.get("source_url"),
                    event.get("url_hash"),
                    event.get("file_name"),
                    event.get("bytes_received"),
                    event.get("error_class"),
                    event.get("http_status"),
                    event.get("retry_after"),
                    event.get("xid"),
                    event.get("duration_ms"),
                ),
            )

    def telemetry_snapshot(self, host: str, now: datetime) -> Dict[str, Any]:
        cutoffs = {key: now - timedelta(minutes=mins) for key, mins in (
            ("1m", 1), ("5m", 5), ("15m", 15), ("60m", 60)
        )}
        with self._tx() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FILTER (WHERE requested_at >= %s) AS r1,
                       COUNT(*) FILTER (WHERE requested_at >= %s) AS r5,
                       COUNT(*) FILTER (WHERE requested_at >= %s) AS r15,
                       COUNT(*) FILTER (WHERE requested_at >= %s) AS r60
                  FROM eis_request_events WHERE host=%s
                """,
                (cutoffs["1m"], cutoffs["5m"], cutoffs["15m"], cutoffs["60m"], host),
            )
            req = dict(cur.fetchone())
            cur.execute(
                """
                SELECT COUNT(*) FILTER (WHERE result='ATTEMPTED' AND requested_at >= %s) AS f1,
                       COUNT(*) FILTER (WHERE result='ATTEMPTED' AND requested_at >= %s) AS f5,
                       COUNT(*) FILTER (WHERE result='ATTEMPTED' AND requested_at >= %s) AS f60
                  FROM eis_file_events WHERE host=%s
                """,
                (cutoffs["1m"], cutoffs["5m"], cutoffs["60m"], host),
            )
            files = dict(cur.fetchone())
            cur.execute(
                "SELECT COALESCE(SUM(bytes_received),0) AS b FROM eis_file_events "
                "WHERE host=%s AND result='DOWNLOADED' AND requested_at >= %s",
                (host, cutoffs["60m"]),
            )
            bytes_last_60m = int(cur.fetchone()["b"] or 0)
            return {
                "requests_last_1m": int(req["r1"] or 0),
                "requests_last_5m": int(req["r5"] or 0),
                "requests_last_15m": int(req["r15"] or 0),
                "requests_last_60m": int(req["r60"] or 0),
                "files_last_1m": int(files["f1"] or 0),
                "files_last_5m": int(files["f5"] or 0),
                "files_last_60m": int(files["f60"] or 0),
                "bytes_last_60m": bytes_last_60m,
            }

    def operational_snapshot(self, host: str, now: datetime) -> Dict[str, Any]:
        since = now - timedelta(minutes=5)
        with self._tx() as cur:
            cur.execute(
                "SELECT COUNT(*) AS requests, "
                "COUNT(*) FILTER (WHERE http_status=429) AS r429 "
                "FROM eis_request_events WHERE host=%s AND requested_at >= %s",
                (host, since),
            )
            req = dict(cur.fetchone())
            cur.execute(
                "SELECT COUNT(*) FILTER (WHERE result='DOWNLOADED') AS files, "
                "COALESCE(SUM(bytes_received),0) AS bytes "
                "FROM eis_file_events WHERE host=%s AND requested_at >= %s",
                (host, since),
            )
            files = dict(cur.fetchone())
            return {
                "requests_5m": int(req["requests"] or 0),
                "files_5m": int(files["files"] or 0),
                "bytes_5m": int(files["bytes"] or 0),
                "429_5m": int(req["r429"] or 0),
                "requests_since_block": 0,
            }

    @contextmanager
    def try_probe_lock(self):
        with _PostgresProbeLock(self) as acquired:
            yield acquired
