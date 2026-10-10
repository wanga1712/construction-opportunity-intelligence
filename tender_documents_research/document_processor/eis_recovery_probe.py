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


def _classify_head_status(status: int) -> str:
    if status == 429:
        return "HTTP_429"
    if status == 403:
        return "ACCESS_BLOCK"
    if status >= 500:
        return "SOURCE_OUTAGE"
    return "SOURCE_ERROR"


def run_recovery_probe(guard=None) -> Dict[str, Any]:
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
    canary_url = resolve_canary_url()
    configured_probe_url = (os.getenv("EIS_PROBE_URL") or "").strip()
    probe_url = configured_probe_url or canary_url
    if not probe_url:
        return {"status": "NO_CANARY", "detail": "No production EIS endpoint available"}

    def probe_fn() -> Dict[str, Any]:
        response = client.request_head(
            probe_url,
            request_type="PROBE",
            timeout=(10, 30),
            allow_redirects=True,
            verify=client._get_verify_param(),
        )
        try:
            status = int(response.status_code)
        finally:
            response.close()
        if status == 429:
            raise EisRateLimited(probe_url)
        if status >= 400:
            return {
                "ok": False,
                "status": _classify_head_status(status),
                "detail": f"HEAD {probe_url} -> {status}",
            }

        if not canary_url:
            return {
                "ok": False,
                "status": "NO_CANARY",
                "detail": "No small production filestore URL is available",
            }
        with tempfile.TemporaryDirectory(prefix="eis-canary-") as tmpdir:
            path = client.try_download_direct(
                Path(tmpdir),
                canary_url,
                suggested_filename="eis_canary.bin",
                request_type="PROBE",
            )
            if not path or not path.exists() or path.stat().st_size <= 0:
                return {
                    "ok": False,
                    "status": "CANARY_FAILED",
                    "detail": "Canary file request did not produce bytes",
                }
        return {
            "ok": True,
            "status": "SUCCESS",
            "detail": f"HEAD {status}; canary bytes ok",
        }

    return guard.maybe_run_probe(probe_fn)
