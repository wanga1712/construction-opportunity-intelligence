"""
document_processor/backends/factory.py

Backend factory for document processing pipeline.

PROCESSING_BACKEND env var:
  unset / "LEGACY" → returns None  (100% legacy behavior unchanged)
  "S13_V2"         → returns S13ProcessingBackend
                     FAIL FAST if document_intelligence unreachable.
                     NO automatic fallback to LEGACY.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .queue_repository import QueueRepository, S13V2QueueRepository, LegacyQueueRepository
from .s13_results import S13V2ResultStore
from .state_repository import ProcessingStateRepository, LegacyStateRepository, S13V2StateRepository


@dataclass
class ProcessingBackend:
    """Holds queue, result, and state backends."""
    queue: QueueRepository
    results: object
    state: ProcessingStateRepository


def create_processing_backend(backend_name: str, db=None) -> ProcessingBackend:
    """
    Return ProcessingBackend for S13_V2, or LEGACY fallback.
    Raises RuntimeError if S13_V2 selected and DB unreachable.
    """
    if backend_name == "S13_V2":
        dsn = _load_s13_dsn()
        queue_repo = S13V2QueueRepository(dsn)
        result_store = S13V2ResultStore(dsn)
        state_repo = S13V2StateRepository(dsn, pipeline_generation="S13_V2")
        _verify_s13_connection(queue_repo)
        return ProcessingBackend(queue=queue_repo, results=result_store, state=state_repo)

    # Legacy fallback
    state_repo = LegacyStateRepository(db, db_alias='tender_monitor')
    queue_repo = LegacyQueueRepository(db, db_alias='tender_monitor')
    return ProcessingBackend(queue=queue_repo, results=None, state=state_repo)

def _load_s13_dsn() -> dict:
    return {
        "host":     os.getenv("S13_DOCUMENT_DB_HOST", "localhost"),
        "port":     int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname":   os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user":     os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }


def _verify_s13_connection(queue_repo: S13V2QueueRepository) -> None:
    """FAIL FAST: raise RuntimeError if S13 DB is unreachable."""
    try:
        queue_repo._get_conn() # Verify connection implicitly
    except Exception as exc:
        raise RuntimeError(
            f"[FATAL] PROCESSING_BACKEND=S13_V2 but document_intelligence "
            f"is unreachable: {exc}\n"
            f"NOT falling back to LEGACY. Fix DB or unset PROCESSING_BACKEND."
        ) from exc
