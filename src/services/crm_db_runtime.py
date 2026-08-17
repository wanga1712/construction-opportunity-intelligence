"""Fail-closed CRM PostgreSQL runtime settings.

UI and ad-hoc psycopg2 callers must not own host/user/password fallbacks.
Required environment: CRM_DB_HOST, CRM_DB_PORT, CRM_DB_DATABASE,
CRM_DB_USER, CRM_DB_PASSWORD.
"""
from __future__ import annotations

import os
from typing import Dict, List


class CrmDbConfigError(RuntimeError):
    """Missing or invalid CRM DB runtime configuration. Never include secrets."""


_REQUIRED = (
    "CRM_DB_HOST",
    "CRM_DB_PORT",
    "CRM_DB_DATABASE",
    "CRM_DB_USER",
    "CRM_DB_PASSWORD",
)


def _missing_keys() -> List[str]:
    missing: List[str] = []
    for key in _REQUIRED:
        value = os.environ.get(key)
        if value is None or not str(value).strip():
            missing.append(key)
    return missing


def require_crm_db_connect_kwargs() -> Dict[str, object]:
    """Return psycopg2.connect kwargs from env only. No hardcoded fallbacks."""
    missing = _missing_keys()
    if missing:
        raise CrmDbConfigError(
            "Missing required CRM DB configuration: "
            + ", ".join(missing)
            + ". Set them in the runtime environment; hardcoded fallbacks are not allowed."
        )
    port_raw = str(os.environ.get("CRM_DB_PORT") or "").strip()
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise CrmDbConfigError("CRM_DB_PORT must be an integer.") from exc
    return {
        "host": str(os.environ["CRM_DB_HOST"]).strip(),
        "port": port,
        "user": str(os.environ["CRM_DB_USER"]).strip(),
        "password": os.environ["CRM_DB_PASSWORD"],
        "dbname": str(os.environ["CRM_DB_DATABASE"]).strip(),
    }
