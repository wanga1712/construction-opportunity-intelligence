"""Canonical global guard for all requests to zakupki.gov.ru."""

from __future__ import annotations

import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, Optional

from .eis_rate_limit_store import (
    EIS_HOST,
    PostgresEisStateStore,
)

LOGGER = logging.getLogger("document_processor.eis_rate_limit_guard")
MINIMUM_COOLDOWN_SECONDS = 300
DEFAULT_PROBE_ERROR_RETRY_SECONDS = 300
DEFAULT_BLOCK_CASCADE_MINUTES = "5,15,30,60,120,180"


def block_cascade_seconds() -> list[int]:
    raw = os.getenv("EIS_BLOCK_CASCADE_MINUTES", DEFAULT_BLOCK_CASCADE_MINUTES)
    values: list[int] = []
    for part in raw.split(","):
        try:
            minutes = float(part.strip())
        except ValueError:
            continue
        if minutes > 0:
            values.append(int(minutes * 60))
    if not values:
        values = [5 * 60, 15 * 60, 30 * 60, 60 * 60, 120 * 60, 180 * 60]
    return sorted(values)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_eis_url(url: Optional[str]) -> bool:
    return "zakupki.gov.ru" in (url or "")


def parse_retry_after(raw: Optional[str], now: Optional[datetime] = None) -> Optional[int]:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return max(0, int(float(value)))
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(value)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return max(0, int((target - (now or utcnow())).total_seconds()))
    except Exception:
        return None


def extract_xid(body: Optional[str]) -> Optional[str]:
    match = re.search(r"\bXID\s*[:=]?\s*(\d{3,})\b", body or "", flags=re.IGNORECASE)
    return match.group(1) if match else None


def _as_datetime(value: Any) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


class EisRateLimited(RuntimeError):
    """Raised immediately after a 429; no local retry/fallback is allowed."""

    def __init__(
        self,
        url: str,
        retry_after: Optional[int] = None,
        xid: Optional[str] = None,
        response_headers: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(f"EIS_RATE_LIMITED url={url} retry_after={retry_after}")
        self.url = url
        self.http_status = 429
        self.retry_after = retry_after
        self.xid = xid
        self.response_headers = response_headers or {}


class EisRateLimitBlocked(RuntimeError):
    """Raised before a request when the global EIS breaker is open."""

    def __init__(self, state: Optional[Dict[str, Any]] = None) -> None:
        super().__init__("EIS_RATE_LIMIT_BLOCKED")
        self.state = state or {}


class EisGuardUnavailable(RuntimeError):
    """The DB authority is unavailable; EIS requests fail closed."""


class EisRateLimitGuard:
    """Single policy authority for EIS block state, probes and telemetry."""

    def __init__(self, store=None, host: str = EIS_HOST) -> None:
        self.store = store or PostgresEisStateStore()
        self.host = host
        self._local_block_until: Optional[datetime] = None
        self._lock = threading.RLock()
        self._probe_active = False

    def _local_blocked(self, now: datetime) -> bool:
        with self._lock:
            return bool(self._local_block_until and self._local_block_until > now)

    def _set_local_block(self, until: datetime) -> None:
        with self._lock:
            if self._local_block_until is None or until > self._local_block_until:
                self._local_block_until = until

    def _clear_local_block(self) -> None:
        with self._lock:
            self._local_block_until = None

    def _fetch_state(self) -> Dict[str, Any]:
        try:
            return self.store.fetch_state(self.host)
        except Exception as exc:
            raise EisGuardUnavailable(str(exc)) from exc

    def state(self) -> Dict[str, Any]:
        return self._fetch_state()

    def is_blocked(self, now: Optional[datetime] = None) -> bool:
        now = now or utcnow()
        if self._local_blocked(now):
            return True
        try:
            state = self._fetch_state()
        except EisGuardUnavailable as exc:
            LOGGER.critical("EIS guard DB unavailable; failing closed: %s", exc)
            return True
        blocked_until = _as_datetime(state.get("blocked_until"))
        return bool(blocked_until and blocked_until > now)

    def ensure_request_allowed(
        self, request_type: str = "DOWNLOAD", now: Optional[datetime] = None
    ) -> None:
        now = now or utcnow()
        if request_type == "PROBE" and self._probe_active:
            return
        if self.is_blocked(now):
            try:
                state = self._fetch_state()
            except EisGuardUnavailable:
                state = {}
            raise EisRateLimitBlocked(state)

    def record_request_start(self, request_type: str, url: str, concurrency: int = 0) -> int:
        try:
            return self.store.record_request_start(
                self.host, request_type, url, concurrency, utcnow()
            )
        except Exception as exc:
            LOGGER.error("EIS telemetry request start failed: %s", exc)
            return 0

    def record_request_finish(
        self,
        event_id: int,
        status: Optional[int],
        bytes_received: Optional[int] = None,
        duration_ms: Optional[int] = None,
        xid: Optional[str] = None,
        retry_after: Optional[int] = None,
        error_class: Optional[str] = None,
    ) -> None:
        if not event_id:
            return
        try:
            self.store.record_request_finish(
                event_id,
                status,
                bytes_received,
                duration_ms,
                xid=xid,
                retry_after=retry_after,
                error_class=error_class,
            )
        except Exception as exc:
            LOGGER.error("EIS telemetry request finish failed: %s", exc)

    def record_file_event(self, **event: Any) -> None:
        try:
            self.store.record_file_event(host=self.host, **event)
        except Exception as exc:
            LOGGER.error("EIS file telemetry failed: %s", exc)

    @staticmethod
    def _config_snapshot(active_downloads: int) -> Dict[str, int]:
        return {
            "active_downloads_at_429": int(active_downloads or 0),
            "configured_max_downloads": int(os.getenv("MAX_ACTIVE_DOWNLOADS", "2")),
            "configured_stagger_ms": int(
                float(os.getenv("DOWNLOAD_STAGGER_INTERVAL_MS", "5000"))
            ),
        }

    def record_429(
        self,
        url: str,
        retry_after: Optional[int] = None,
        xid: Optional[str] = None,
        active_downloads: int = 0,
    ) -> Dict[str, Any]:
        now = utcnow()
        cascade = block_cascade_seconds()
        try:
            previous = int(self._fetch_state().get("consecutive_blocks") or 0)
        except Exception:
            previous = 0
        next_index = min(previous, len(cascade) - 1)
        cooldown = max(cascade[next_index], int(retry_after or 0))
        self._set_local_block(now + timedelta(seconds=cooldown))
        state: Dict[str, Any] = {"host": self.host}
        try:
            snapshot = self.store.telemetry_snapshot(self.host, now)
            state = self.store.apply_429(
                self.host,
                now,
                retry_after,
                xid,
                snapshot,
                self._config_snapshot(active_downloads),
                cascade,
            )
            blocked_until = _as_datetime(state.get("blocked_until"))
            if blocked_until:
                self._set_local_block(blocked_until)
        except Exception as exc:
            LOGGER.critical("EIS 429 block could not be persisted: %s", exc)
        LOGGER.critical(
            "EIS GLOBAL BLOCK: 429 url=%s retry_after=%s xid=%s until=%s",
            url,
            retry_after,
            xid,
            state.get("blocked_until"),
        )
        return state

    def record_probe_result(self, status: str, detail: Optional[str] = None) -> None:
        now = utcnow()
        try:
            if status == "SUCCESS":
                self.store.apply_probe_success(self.host, now)
                self._clear_local_block()
            elif status == "HTTP_429":
                self.store.apply_probe_status(self.host, now, status)
            else:
                retry = int(
                    os.getenv("EIS_PROBE_ERROR_BACKOFF_SECONDS", str(DEFAULT_PROBE_ERROR_RETRY_SECONDS))
                )
                self.store.apply_probe_error(self.host, now, status, retry)
        except Exception as exc:
            LOGGER.error("EIS probe result could not be persisted: %s", exc)
        LOGGER.warning("EIS probe result=%s detail=%s", status, detail or "")

    def probe_due(self, now: Optional[datetime] = None) -> bool:
        now = now or utcnow()
        try:
            state = self._fetch_state()
        except EisGuardUnavailable:
            return False
        blocked_until = _as_datetime(state.get("blocked_until"))
        return bool(blocked_until and blocked_until <= now)

    def maybe_run_probe(self, probe_fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
        now = utcnow()
        if not self.probe_due(now):
            return {"status": "NOT_DUE"}
        try:
            with self.store.try_probe_lock() as acquired:
                if not acquired:
                    return {"status": "LOCK_BUSY"}
                now = utcnow()
                if not self.probe_due(now):
                    return {"status": "NOT_DUE"}
                with self._lock:
                    self._probe_active = True
                try:
                    self.store.apply_probe_started(self.host, now)
                    result = probe_fn() or {}
                    if result.get("ok"):
                        self.record_probe_result("SUCCESS", result.get("detail"))
                        return {**result, "status": "RECOVERED"}
                    status = str(result.get("status") or "SOURCE_ERROR")
                    self.record_probe_result(status, result.get("detail"))
                    return {"status": status, **result}
                except EisRateLimited as exc:
                    self.record_probe_result("HTTP_429", str(exc))
                    return {
                        "status": "HTTP_429",
                        "retry_after": exc.retry_after,
                        "xid": exc.xid,
                    }
                except Exception as exc:
                    self.record_probe_result("NETWORK_ERROR", str(exc))
                    return {"status": "NETWORK_ERROR", "detail": str(exc)}
                finally:
                    with self._lock:
                        self._probe_active = False
        except Exception as exc:
            LOGGER.error("EIS probe orchestration failed: %s", exc)
            return {"status": "PROBE_ERROR", "detail": str(exc)}

    def operational_report(self, now: Optional[datetime] = None) -> str:
        now = now or utcnow()
        try:
            state = self._fetch_state()
            snap = self.store.operational_snapshot(self.host, now)
        except Exception as exc:
            return f"EIS GUARD\nstatus=UNAVAILABLE\nerror={exc}"
        blocked_until = _as_datetime(state.get("blocked_until"))
        if blocked_until and blocked_until > now:
            return "\n".join(
                [
                    "EIS GUARD",
                    "status=BLOCKED",
                    f"blocked_since={state.get('blocked_since')}",
                    f"blocked_until={blocked_until.isoformat()}",
                    "reason=HTTP_429",
                    f"xid={state.get('last_429_xid') or '-'}",
                    f"requests_since_block={snap.get('requests_since_block', 0)}",
                    f"next_probe={blocked_until.isoformat()}",
                ]
            )
        return "\n".join(
            [
                "EIS GUARD",
                "status=OPEN",
                f"requests_5m={snap.get('requests_5m', 0)}",
                f"files_5m={snap.get('files_5m', 0)}",
                f"bytes_5m={snap.get('bytes_5m', 0)}",
                f"429_5m={snap.get('429_5m', 0)}",
                f"consecutive_blocks={state.get('consecutive_blocks') or 0}",
                f"last_429={state.get('last_429_at') or '-'}",
            ]
        )


_GUARD_LOCK = threading.Lock()
_GUARD: Optional[EisRateLimitGuard] = None


def get_eis_guard() -> EisRateLimitGuard:
    global _GUARD
    with _GUARD_LOCK:
        if _GUARD is None:
            _GUARD = EisRateLimitGuard()
        return _GUARD


def reset_eis_guard_for_tests(guard: Optional[EisRateLimitGuard] = None) -> None:
    global _GUARD
    with _GUARD_LOCK:
        _GUARD = guard
