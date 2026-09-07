"""Non-destructive reconciliation of active queue admission snapshots."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .admission_policy import ADMISSION_HOLD, ADMISSION_POLICY_VERSION

ACTIVE_QUEUE_STATUSES = frozenset({"PENDING", "PRE_RESEARCH_WAITING", "pending"})
MAX_ADMISSION_STALENESS_BEFORE_CLAIM = "reconciled immediately before every claim cycle"


def load_current_authority(procurement_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Read current CRM authority using CRM credentials, never document credentials."""
    if not procurement_ids:
        return {}
    import os
    import psycopg2
    import psycopg2.extras

    connection = psycopg2.connect(
        host=os.getenv("CRM_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("CRM_DB_PORT", "5432")),
        dbname=os.getenv("CRM_DB_DATABASE", "crm"),
        user=os.getenv("CRM_DB_USER", ""),
        password=os.getenv("CRM_DB_PASSWORD", ""),
    )
    try:
        with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT procurement_id, admission_state, admission_reason,
                       admission_policy_version, admission_evaluated_at,
                       scope_version
                FROM crm_procurement_scope_authority
                WHERE procurement_id = ANY(%s)
                """,
                (procurement_ids,),
            )
            return {int(row["procurement_id"]): dict(row) for row in cursor.fetchall()}
    finally:
        connection.close()


def reconcile_active_queue_rows(
    queue_rows: list[Mapping[str, Any]],
    authority_by_procurement: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return active rows whose persisted admission context must change."""
    changes: list[dict[str, Any]] = []
    for row in queue_rows:
        if row.get("status") not in ACTIVE_QUEUE_STATUSES:
            continue
        authority = authority_by_procurement.get(int(row["procurement_id"]))
        if authority is None:
            desired_state = ADMISSION_HOLD
            desired_reason = "AUTHORITY_MISSING"
            desired_version = ADMISSION_POLICY_VERSION
            desired_evaluated_at = None
            desired_scope_version = None
        else:
            desired_state = str(authority.get("admission_state") or ADMISSION_HOLD)
            desired_reason = str(authority.get("admission_reason") or "AUTHORITY_MISSING")
            desired_version = str(authority.get("admission_policy_version") or ADMISSION_POLICY_VERSION)
            evaluated_at = authority.get("admission_evaluated_at")
            desired_evaluated_at = (
                evaluated_at.isoformat()
                if hasattr(evaluated_at, "isoformat")
                else evaluated_at
            )
            desired_scope_version = authority.get("scope_version")

        context = deepcopy(row.get("category_context") or {})
        current = (
            context.get("admission_state"),
            context.get("admission_reason"),
            context.get("admission_policy_version"),
            context.get("admission_evaluated_at"),
            context.get("authority_scope_version"),
        )
        desired = (
            desired_state,
            desired_reason,
            desired_version,
            desired_evaluated_at,
            desired_scope_version,
        )
        if current == desired:
            continue

        context.update(
            admission_state=desired_state,
            admission_reason=desired_reason,
            admission_policy_version=desired_version,
            admission_evaluated_at=desired_evaluated_at,
            authority_scope_version=desired_scope_version,
        )
        changes.append(
            {
                "queue_id": row["id"],
                "procurement_id": row["procurement_id"],
                "previous_admission_state": current[0],
                "admission_state": desired_state,
                "admission_reason": desired_reason,
                "category_context": context,
            }
        )
    return changes
