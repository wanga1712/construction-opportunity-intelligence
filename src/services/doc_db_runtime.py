"""Fail-closed document-intelligence PostgreSQL runtime settings.

The document contour is NOT the CRM database: it has its own database, its own
runtime role (``doc_worker``) and its own credentials. This module is the single
authority for that connection. UI/ad-hoc callers must not build their own
host/user/password fallbacks, must not inherit the CRM role, and must never
carry a hardcoded credential.

Canonical endpoint (docs/PROJECT_OPERATING_RULES.md): S13 local
``127.0.0.1:5432/document_intelligence`` as role ``doc_worker``.

Off-S13 runtimes (e.g. the local Windows Streamlit dev instance) must override
host/port explicitly - normally through an approved SSH tunnel:

    S13_DOCUMENT_DB_HOST=127.0.0.1
    S13_DOCUMENT_DB_PORT=15432

When host/port/role are not set explicitly the canonical defaults are used and
a warning is logged, so the fallback is never silent.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List
from src.services.db_host_guard import assert_host_allowed

logger = logging.getLogger(__name__)


class DocDbConfigError(RuntimeError):
    """Missing or invalid document DB runtime configuration. Never includes secrets."""


DOC_DB_NAME = "document_intelligence"
CANONICAL_HOST = "127.0.0.1"
CANONICAL_PORT = 5432
CANONICAL_USER = "doc_worker"

# Canonical endpoint values are documented, not guessed: only the password is
# never inferable, so it is the one hard requirement.
_EXPLICIT_DEFAULTS = {
    "S13_DOCUMENT_DB_HOST": CANONICAL_HOST,
    "S13_DOCUMENT_DB_PORT": str(CANONICAL_PORT),
    "S13_DOCUMENT_DB_USER": CANONICAL_USER,
}


def _resolve(keys: List[str]) -> Dict[str, str]:
    resolved: Dict[str, str] = {}
    defaulted: List[str] = []
    for key in keys:
        value = os.environ.get(key)
        if value is None or not str(value).strip():
            resolved[key] = _EXPLICIT_DEFAULTS[key]
            defaulted.append(key)
        else:
            resolved[key] = str(value).strip()
    if defaulted:
        logger.warning(
            "document DB endpoint using canonical S13 defaults for: %s",
            ", ".join(defaulted),
        )
    return resolved


def require_doc_db_connect_kwargs() -> Dict[str, object]:
    """Return psycopg2.connect kwargs for document_intelligence. Single authority."""
    password = os.environ.get("S13_DOCUMENT_DB_PASSWORD")
    if password is None or not str(password).strip():
        raise DocDbConfigError(
            "Missing required document DB configuration: S13_DOCUMENT_DB_PASSWORD. "
            "Set it in the runtime environment; hardcoded credentials are not allowed."
        )

    resolved = _resolve(list(_EXPLICIT_DEFAULTS))
    port_raw = resolved["S13_DOCUMENT_DB_PORT"]
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise DocDbConfigError("S13_DOCUMENT_DB_PORT must be an integer.") from exc

    dbname = str(os.environ.get("S13_DOCUMENT_DB_NAME") or "").strip() or DOC_DB_NAME
    return {
        "host": assert_host_allowed(
            resolved["S13_DOCUMENT_DB_HOST"], "S13_DOCUMENT_DB_HOST"
        ),
        "port": port,
        "user": resolved["S13_DOCUMENT_DB_USER"],
        "password": password,
        "dbname": dbname,
    }
