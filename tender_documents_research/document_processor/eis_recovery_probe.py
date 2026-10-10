"""Minimal automatic recovery probe for the EIS circuit breaker."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import psycopg2

from .concurrency_manager import DownloadCoordinator
from .eis_rate_limit_guard import EisRateLimited, get_eis_guard
from .eis_rate_limit_store import load_document_dsn
from .http_client import HttpFileClient

LOGGER = logging.getLogger("document_processor.eis_recovery_probe")
DEFAULT_PROBE_URL = "https://zakupki.gov.ru/robots.txt"
MAX_CANARY_CANDIDATES = int(os.getenv("EIS_CANARY_CANDIDATES", "5"))

# Canary outcomes that must NEVER extend the rate-limit block.
CANARY_STALE_STATUSES = (404, 410)


def _url_hash(url: str) -> str:
    import hashlib

    return hashlib.sha256((url or "").strip().lower().encode("utf-8")).hexdigest()


def mark_canary_stale(url: str, status: int, dsn: Optional[dict] = None) -> None:
    """Record a 404/410 canary so later probes rotate to another URL."""
    try:
        conn = psycopg2.connect(**(dsn or load_document_dsn()))
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO eis_canary_stale_urls (url_hash, url, last_status)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (url_hash)
                    DO UPDATE SET last_status = EXCLUDED.last_status, marked_at = now()
                    """,
                    (_url_hash(url), url, int(status)),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # stale marking must never break the probe
        LOGGER.warning("Cannot mark canary URL stale: %s", exc)


def resolve_canary_candidates(
    dsn: Optional[dict] = None, limit: int = MAX_CANARY_CANDIDATES
) -> list:
    """Fresh persisted EIS file URLs, newest first, stale ones excluded."""
    configured = (os.getenv("EIS_CANARY_URL") or "").strip()
    if configured:
        return [configured]
    try:
        conn = psycopg2.connect(**(dsn or load_document_dsn()))
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT df.url
                      FROM document_files df
                     WHERE df.url LIKE %s
                       AND df.download_status = 'COMPLETED'
                       AND COALESCE(df.file_size_bytes, 0) BETWEEN 1 AND 5242880
                       AND COALESCE(df.local_deleted_at, 'infinity'::timestamptz) > NOW()
                       AND NOT EXISTS (
                             SELECT 1 FROM eis_canary_stale_urls s
                              WHERE s.url_hash = COALESCE(df.physical_download_key, df.url_hash, df.url)
                                 OR s.url = df.url
                       )
                     GROUP BY df.url
                     ORDER BY min(df.file_size_bytes) ASC NULLS LAST, max(df.id) DESC
                     LIMIT %s
                    """,
                    ("%zakupki.gov.ru/%filestore%", max(1, int(limit))),
                )
                return [row[0] for row in (cur.fetchall() or []) if row and row[0]]
        finally:
            conn.close()
    except Exception as exc:
        LOGGER.warning("Cannot resolve EIS canary URLs: %s", exc)
        return []


def resolve_canary_url(dsn: Optional[dict] = None) -> Optional[str]:
    """Pick one small, locally relevant production file for the canary."""
    configured = (os.getenv("EIS_CANARY_URL") or "").strip()
    if configured:
        return configured
    try:
        conn = psycopg2.connect(**(dsn or load_document_dsn()))
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT url
                      FROM document_files
                     WHERE url LIKE %s
                       AND download_status = 'COMPLETED'
                       AND COALESCE(file_size_bytes, 0) BETWEEN 1 AND 5242880
                       AND COALESCE(local_deleted_at, 'infinity'::timestamptz) > NOW()
                     ORDER BY file_size_bytes ASC NULLS LAST, id DESC
                     LIMIT 1
                    """,
                    ("%zakupki.gov.ru/%filestore%",),
                )
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            conn.close()
    except Exception as exc:
        LOGGER.warning("Cannot resolve EIS canary URL: %s", exc)
        return None


def _classify_reachability_status(status: int) -> str:
    """Reachability verdict for the EIS host itself."""
    if status == 429:
        return "HTTP_429"
    if status in (401, 403):
        return "ACCESS_BLOCK"
    if status >= 500:
        return "SOURCE_UNAVAILABLE"
    if 200 <= status < 400:
        return "EIS_REACHABLE"
    return "SOURCE_ERROR"


def run_recovery_probe(guard=None) -> Dict[str, Any]:
    """Two independent questions.

    1. Is the EIS host reachable at all?  (reachability endpoint)
    2. Is the stored canary file still alive? (canary, rotatable)

    A stale canary (404/410) must never extend the rate-limit block; only a
    429 (rate limited) or a hard transport/5xx failure keeps it in force.
    """
    guard = guard or get_eis_guard()
    if not guard.probe_due():
        return {"status": "NOT_DUE"}

    logger = logging.getLogger("document_processor.eis_recovery_probe")
    coordinator = DownloadCoordinator()
    client = HttpFileClient(
        os.getenv("DOCUMENT_PROXY_URL"),
        os.getenv("DOCUMENT_PROXY_MODE", "endpoint"),
        logger,
        guard=guard,
    )
    client.set_request_gate(coordinator.request_slot)
    configured_probe_url = (os.getenv("EIS_PROBE_URL") or "").strip()
    probe_url = configured_probe_url or DEFAULT_PROBE_URL
    if not probe_url:
        return {"status": "NO_CANARY", "detail": "No production EIS endpoint available"}

    def probe_fn() -> Dict[str, Any]:
        # ---- step 1: is the host reachable?
        response = client.request_head(
            probe_url,
            request_type="PROBE",
            timeout=(10, 30),
            allow_redirects=True,
            verify=client._get_verify_param(),
        )
        try:
            reach_status = int(response.status_code)
        finally:
            response.close()
        reachability = _classify_reachability_status(reach_status)
        if reachability == "HTTP_429":
            raise EisRateLimited(probe_url)
        if reachability == "EIS_REACHABLE":
            pass
        elif reachability in ("SOURCE_UNAVAILABLE", "ACCESS_BLOCK", "SOURCE_ERROR"):
            return {
                "ok": False,
                "status": reachability,
                "detail": f"HEAD {probe_url} -> {reach_status}",
            }
        else:
            return {
                "ok": False,
                "status": reachability,
                "detail": f"HEAD {probe_url} -> {reach_status}",
            }

        # ---- step 2: canary liveness (rotates on stale, never blocks EIS)
        canary_targets = list(resolve_canary_candidates())
        if probe_url not in canary_targets:
            canary_targets.append(probe_url)
        stale_hits = []
        with tempfile.TemporaryDirectory(prefix="eis-canary-") as tmpdir:
            for target in canary_targets:
                try:
                    response = client.request_head(
                        target,
                        request_type="PROBE",
                        timeout=(10, 30),
                        allow_redirects=True,
                        verify=client._get_verify_param(),
                    )
                    try:
                        canary_status = int(response.status_code)
                    finally:
                        response.close()
                except EisRateLimited:
                    raise
                except Exception as exc:
                    logger.warning("Canary HEAD failed for %s: %s", target, exc)
                    continue
                if canary_status == 429:
                    raise EisRateLimited(target)
                if canary_status in CANARY_STALE_STATUSES:
                    mark_canary_stale(target, canary_status)
                    stale_hits.append((target, canary_status))
                    continue
                if canary_status >= 400:
                    continue
                path = client.try_download_direct(
                    Path(tmpdir),
                    target,
                    suggested_filename="eis_canary.bin",
                    request_type="PROBE",
                )
                if path and path.exists() and path.stat().st_size > 0:
                    return {
                        "ok": True,
                        "status": "CANARY_OK",
                        "detail": (
                            f"EIS_REACHABLE HEAD {reach_status}; "
                            f"canary live ({target[:60]})"
                        ),
                    }
            # Reachability already proven: a stale/absent canary must NOT
            # extend the block (CANARY_404_410_EXTEND_BLOCK=NO).
            return {
                "ok": True,
                "status": "CANARY_STALE",
                "detail": (
                    f"EIS_REACHABLE HEAD {reach_status}; "
                    f"canary stale/absent ({len(stale_hits)} stale)"
                ),
            }

    return guard.maybe_run_probe(probe_fn)
