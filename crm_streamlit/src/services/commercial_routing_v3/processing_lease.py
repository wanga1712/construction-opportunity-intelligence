"""Processing lease reclaim for RUNNING rows (no Qwen)."""
from __future__ import annotations

import logging
from typing import Any, Dict

from src.services.commercial_routing_v3.routing_runtime_config import (
    ROUTING_PROCESSING_LEASE_SEC,
)

logger = logging.getLogger("commercial_routing_v3.processing_lease")


def reclaim_stale_running(crm_db) -> Dict[str, Any]:
    """RUNNING past lease → STALE (retryable). Returns counts.

    STALE_PROCESSING_RECOVERY_POLICY=RUNNING_LEASE_EXPIRED_TO_STALE
    """
    before = int(
        crm_db.execute_scalar(
            """
            SELECT COUNT(*)::int FROM crm_procurements
            WHERE ai_assessment_status = 'RUNNING'
              AND (
                ai_assessed_at IS NULL
                OR ai_assessed_at < NOW() - (%s * INTERVAL '1 second')
              )
            """,
            (ROUTING_PROCESSING_LEASE_SEC,),
        )
        or 0
    )
    crm_db.execute_update(
        """
        UPDATE crm_procurements
        SET ai_assessment_status = 'STALE',
            ai_routing_error_class = COALESCE(NULLIF(ai_routing_error_class, ''), 'LEASE_EXPIRED')
        WHERE ai_assessment_status = 'RUNNING'
          AND (
            ai_assessed_at IS NULL
            OR ai_assessed_at < NOW() - (%s * INTERVAL '1 second')
          )
        """,
        (ROUTING_PROCESSING_LEASE_SEC,),
    )
    logger.info(
        "reclaim_stale_running lease_sec=%s reclaimed=%s",
        ROUTING_PROCESSING_LEASE_SEC,
        before,
    )
    return {
        "lease_sec": ROUTING_PROCESSING_LEASE_SEC,
        "reclaimed": before,
        "policy": "RUNNING_LEASE_EXPIRED_TO_STALE",
    }


def count_unrecoverable_running(crm_db) -> int:
    """RUNNING still past lease after reclaim should be 0."""
    val = crm_db.execute_scalar(
        """
        SELECT COUNT(*)::int FROM crm_procurements
        WHERE ai_assessment_status = 'RUNNING'
          AND (
            ai_assessed_at IS NULL
            OR ai_assessed_at < NOW() - (%s * INTERVAL '1 second')
          )
        """,
        (ROUTING_PROCESSING_LEASE_SEC,),
    )
    return int(val or 0)
