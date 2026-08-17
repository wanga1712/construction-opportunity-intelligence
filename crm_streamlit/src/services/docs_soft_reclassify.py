"""Soft reclassify queue rows — DISABLED for CRM source-readonly enforcement.

document_processing_queue lives on source/docs infrastructure.
CRM application must not mutate it via tender_db.
"""
from __future__ import annotations


def soft_reclassify_docs_queue(tender_db=None, **_kwargs) -> dict:
    """Fail-closed: CRM must not UPDATE document_processing_queue on source DB."""
    return {
        "error": (
            "SOURCE_DB_READONLY: soft_reclassify_docs_queue is disabled in CRM. "
            "Document queue mutations belong to the docs subsystem, not CRM."
        ),
        "total": 0,
        "blocked": True,
    }
