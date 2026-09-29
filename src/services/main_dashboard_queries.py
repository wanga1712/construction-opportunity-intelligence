"""Main dashboard — bounded read-only DB access (crm + document_intelligence).

Every function here is SELECT-only and bounded: no per-category N+1, no
unbounded scans. Connection kwargs come from the production runtime env.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.services.medal_semantics_v2 import (
    MEDAL_SEMANTICS_VERSION,
    PRODUCTION_MODEL,
    PRODUCTION_PROMPT_VERSION,
)

from src.services.doc_db_runtime import DOC_DB_NAME  # noqa: F401  (canonical name)

logger = logging.getLogger(__name__)


def crm_connect_kwargs(timeout: int = 5) -> Dict[str, Any]:
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs

    kwargs = dict(require_crm_db_connect_kwargs())
    kwargs["connect_timeout"] = timeout
    return kwargs


def doc_connect_kwargs(timeout: int = 5) -> Dict[str, Any]:
    """Document-intelligence DB kwargs. Single authority, no fallbacks.

    The document contour has its own database, its own runtime role and its own
    credentials, so its configuration is never inherited from the CRM role and
    never guessed locally. See ``src.services.doc_db_runtime``.
    """
    from src.services.doc_db_runtime import require_doc_db_connect_kwargs

    kwargs: Dict[str, Any] = dict(require_doc_db_connect_kwargs())
    kwargs["connect_timeout"] = timeout
    return kwargs


def fetch(kwargs: Dict[str, Any], sql: str, params: Sequence[Any] = ()) -> List[Tuple]:
    import psycopg2

    conn = psycopg2.connect(**kwargs)
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 8000")
            cur.execute(sql, tuple(params))
            return list(cur.fetchall())
    finally:
        conn.close()


# ── SQL ───────────────────────────────────────────────────────────────────

ACTIVE_SQL = """
SELECT cp.id, coalesce(cp.contract_number, ''), cp.crm_created_at, cp.end_date, cp.initial_price,
       (cp.crm_created_at >= now() - INTERVAL '24 hours') AS is_new
FROM crm_procurements cp
WHERE cp.crm_stage = 'torgi'
  AND cp.award_status = 'submission_open'
  AND cp.end_date >= CURRENT_DATE + INTERVAL '2 days'
"""

# Authority: a "current Second Pass result" is the current assessment that is
# attached to a completed PRODUCTION model run (procurement_ai_assessments.
# inference_run_id -> crm_v3_model_inference_runs). Legacy is_current rows with
# no run are not current-v2 results and must not be counted.
ASSESSMENT_SQL = (
    """
SELECT a.procurement_id,
       (a.normalized_result IS NOT NULL) AS has_result,
       upper(coalesce(a.proposed_level, '')) AS level
FROM procurement_ai_assessments a
JOIN crm_v3_model_inference_runs r ON r.id = a.inference_run_id
WHERE a.is_current AND a.procurement_id = ANY(%s)
  AND NOT a.is_stale
  AND a.prompt_version = '__MS_PROMPT__'
  AND a.normalized_result->>'semantics_version' = '__MS_VERSION__'
  AND r.run_kind = 'PRODUCTION'
  AND r.run_status IN ('COMPLETED', 'VALIDATED_SUCCESS')
  AND r.model_name = '__MS_MODEL__'
"""
    .replace("__MS_PROMPT__", PRODUCTION_PROMPT_VERSION)
    .replace("__MS_VERSION__", str(MEDAL_SEMANTICS_VERSION))
    .replace("__MS_MODEL__", PRODUCTION_MODEL)
)

CATEGORY_REGISTRY_SQL = """
SELECT category_code, category_name
FROM crm_product_categories
WHERE is_active = TRUE
ORDER BY sort_order, category_code
"""

# MEDAL SEMANTICS V2 authority: a category medal may only be supplied by a
# successful current-semantics run using the production prompt and model.
# Legacy (run-less), stale and other-prompt rows are excluded from the
# commercial category matrix.
CATEGORY_MEDAL_SQL = (
    """
WITH active AS (
    SELECT cp.id FROM crm_procurements cp
    WHERE cp.crm_stage = 'torgi' AND cp.award_status = 'submission_open'
      AND cp.end_date >= CURRENT_DATE + INTERVAL '2 days'
),
sp_cat AS (
    SELECT DISTINCT a.procurement_id AS pid, (ce->>'category_code') AS cat,
           upper(coalesce(ce->>'category_model_medal', '')) AS medal
    FROM procurement_ai_assessments a
    JOIN active ON active.id = a.procurement_id
    JOIN crm_v3_model_inference_runs r ON r.id = a.inference_run_id
    CROSS JOIN LATERAL jsonb_array_elements(
        COALESCE(a.normalized_result->'category_evaluations', '[]'::jsonb)) ce
    WHERE a.is_current
      AND NOT a.is_stale
      AND a.prompt_version = '__MS_PROMPT__'
      AND a.normalized_result->>'semantics_version' = '__MS_VERSION__'
      AND r.run_kind = 'PRODUCTION'
      AND r.run_status IN ('COMPLETED', 'VALIDATED_SUCCESS')
      AND r.model_name = '__MS_MODEL__'
),
fp_cat AS (
    SELECT DISTINCT o.procurement_id AS pid, o.commercial_category_code AS cat,
           upper(coalesce(o.candidate_initial_medal, '')) AS medal
    FROM crm_procurement_category_opportunities o
    JOIN active ON active.id = o.procurement_id
    WHERE o.status = 'CURRENT' AND o.candidate_initial_medal IS NOT NULL
),
united AS (
    SELECT pid, cat, medal, 'SECOND_PASS' AS src FROM sp_cat
    UNION ALL
    SELECT f.pid, f.cat, f.medal, 'FIRST_PASS' AS src FROM fp_cat f
    WHERE NOT EXISTS (SELECT 1 FROM sp_cat s WHERE s.pid = f.pid AND s.cat = f.cat)
),
ranked AS (
    SELECT pid, cat, medal, src,
           row_number() OVER (
               PARTITION BY pid, cat
               ORDER BY CASE medal
                   WHEN 'GOLD' THEN 1 WHEN 'SILVER' THEN 2
                   WHEN 'BRONZE' THEN 3 WHEN 'WOOD' THEN 4
                   ELSE 9 END
           ) AS rn
    FROM united
)
SELECT pid, cat, medal, src FROM ranked WHERE rn = 1
"""
    .replace("__MS_PROMPT__", PRODUCTION_PROMPT_VERSION)
    .replace("__MS_VERSION__", str(MEDAL_SEMANTICS_VERSION))
    .replace("__MS_MODEL__", PRODUCTION_MODEL)
)

DOC_STATS_SQL = """
SELECT f.procurement_id,
       count(*) AS files,
       count(*) FILTER (WHERE f.download_status = 'COMPLETED') AS completed,
       count(*) FILTER (WHERE f.download_status = 'FAILED') AS failed
FROM document_files f
WHERE f.procurement_id = ANY(%s)
GROUP BY 1
"""

DOC_MATCHES_SQL = """
SELECT procurement_id, count(*)
FROM document_matches
WHERE procurement_id = ANY(%s)
GROUP BY 1
"""

DOC_ERRORS_SQL = """
SELECT coalesce(left(error_message, 120), ''), download_status, count(*)
FROM document_files
WHERE created_at > now() - INTERVAL '24 hours'
  AND (error_message IS NOT NULL OR download_status = 'FAILED')
GROUP BY 1, 2
"""

CRM_SYNC_SQL = """
SELECT max(crm_updated_at) FROM crm_procurements
WHERE id >= (SELECT max(id) - 5000 FROM crm_procurements)
"""

NEWEST_INGEST_SQL = """
SELECT crm_created_at FROM crm_procurements ORDER BY id DESC LIMIT 1
"""

QUEUE_PRODUCER_SQL = """
SELECT max(created_at) FROM document_processing_queue
"""

DOC_WORKER_SQL = """
SELECT greatest(max(coalesce(completed_at, started_at)), max(started_at))
FROM document_processing_queue
"""

# Authority: crm_v3_model_inference_runs only has created_at (there is no
# started_at/finished_at/completed_at column), and a row is inserted when the
# worker *claims* the run -- not when it finishes. So the heartbeat is the last
# PRODUCTION run attempt. SHADOW rows belong to the shadow predictor, a
# different worker, and must not mask the production heartbeat.
SECOND_PASS_SQL = """
SELECT max(created_at) FROM crm_v3_model_inference_runs
WHERE run_kind = 'PRODUCTION'
"""


# ── row loaders ───────────────────────────────────────────────────────────

def load_active_rows() -> List[Tuple]:
    return fetch(crm_connect_kwargs(), ACTIVE_SQL)


def load_assessment_levels(ids: Sequence[int]) -> Dict[int, Tuple[bool, str]]:
    out: Dict[int, Tuple[bool, str]] = {}
    if not ids:
        return out
    for pid, has_result, level in fetch(crm_connect_kwargs(), ASSESSMENT_SQL, (list(ids),)):
        out[int(pid)] = (bool(has_result), str(level or ""))
    return out


def load_category_registry() -> List[Tuple[str, str]]:
    return [(str(r[0]), str(r[1])) for r in fetch(crm_connect_kwargs(), CATEGORY_REGISTRY_SQL)]


def load_category_medals() -> List[Tuple[int, str, str, str]]:
    return [
        (int(pid), str(cat), str(medal), str(src))
        for pid, cat, medal, src in fetch(crm_connect_kwargs(), CATEGORY_MEDAL_SQL)
    ]


def load_doc_stats(ids: Sequence[int]) -> Dict[str, Any]:
    stats: Dict[str, Any] = {"files": {}, "matches": {}, "error": None}
    if not ids:
        return stats
    try:
        kwargs = doc_connect_kwargs()
        for pid, files, completed, failed in fetch(kwargs, DOC_STATS_SQL, (list(ids),)):
            stats["files"][int(pid)] = (int(files), int(completed), int(failed))
        for pid, cnt in fetch(kwargs, DOC_MATCHES_SQL, (list(ids),)):
            stats["matches"][int(pid)] = int(cnt)
    except Exception as exc:  # noqa: BLE001 - reported, never zeroed
        logger.warning("dashboard doc stats failed: %s", exc)
        stats["error"] = f"{type(exc).__name__}: {exc}"
    return stats


def load_doc_error_rows() -> Tuple[List[Tuple], Optional[str]]:
    try:
        return fetch(doc_connect_kwargs(), DOC_ERRORS_SQL), None
    except Exception as exc:  # noqa: BLE001
        logger.warning("dashboard doc errors failed: %s", exc)
        return [], f"{type(exc).__name__}: {exc}"


def load_freshness_stamps() -> Dict[str, Any]:
    """Bounded heartbeat probes. Each entry: (value, error)."""
    probes = {
        "crm_sync": (crm_connect_kwargs(), CRM_SYNC_SQL),
        "new_procurement": (crm_connect_kwargs(), NEWEST_INGEST_SQL),
        "queue_producer": (doc_connect_kwargs(), QUEUE_PRODUCER_SQL),
        "doc_worker": (doc_connect_kwargs(), DOC_WORKER_SQL),
        "second_pass": (crm_connect_kwargs(), SECOND_PASS_SQL),
    }
    out: Dict[str, Any] = {}
    for key, (kwargs, sql) in probes.items():
        try:
            rows = fetch(kwargs, sql)
            out[key] = (rows[0][0] if rows and rows[0] else None, None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("dashboard heartbeat %s failed: %s", key, exc)
            out[key] = (None, f"{type(exc).__name__}: {exc}")
    return out