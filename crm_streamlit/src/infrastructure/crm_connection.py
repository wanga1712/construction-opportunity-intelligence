"""Infrastructure factory for a CRM PostgreSQL connection."""
from __future__ import annotations

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs


def connect_crm():
    """Create a CRM connection from the existing environment contract."""
    return psycopg2.connect(**require_crm_db_connect_kwargs())
