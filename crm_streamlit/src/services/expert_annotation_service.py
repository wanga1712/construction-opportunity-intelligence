"""Expert annotation service — versioned storage in crm_v3_expert_annotations.

Public API:
    load_model_assessment_for_annotation(procurement_id, crm_db) -> dict | None
    load_expert_annotation(procurement_id, crm_db) -> dict | None
    save_expert_annotation(procurement_id, payload, created_by, crm_db) -> int
    write_audit_row(procurement_id, model_raw, annotation_payload, crm_db) -> None
    save_taxonomy_proposal(procurement_id, annotation_id, proposal, created_by, crm_db) -> None
    load_categories_for_selector(crm_db) -> list[dict]
    load_subcategories(category_code, crm_db) -> list[dict]
    collect_known_object_types(crm_db) -> list[str]
    collect_known_project_stages(crm_db) -> list[str]

Invariants:
    - MODEL RAW (procurement_ai_assessments) is never mutated.
    - Production projection (crm_procurement_category_opportunities) is not touched.
    - save_expert_annotation is atomic: old is_current→false + new insert in one transaction.
    - Expert annotation NEVER creates confirmed_base_medal / document evidence.
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

# Current payload schema version.  Bump when annotation structure changes
# between major training dataset iterations.
ANNOTATION_SCHEMA_VERSION = 1
_ANNOTATION_LOCK_NAMESPACE = 73103


@contextmanager
def _transaction_connection(crm_db: Any):
    """Yield the production manager connection without breaking its lifecycle.

    Pool-style adapters expose get_connection/release_connection.  The actual
    production CrmDatabaseManager is a connected singleton with
    _ensure_connection/_connection.  Both paths use the same psycopg2
    transaction contract; only pool-acquired connections are released here.
    """
    acquired = hasattr(crm_db, "get_connection")
    if acquired:
        conn = crm_db.get_connection()
    else:
        crm_db._ensure_connection()
        conn = crm_db._connection
    if conn is None:
        raise RuntimeError("CRM database connection is not available")
    try:
        yield conn
    finally:
        if acquired:
            crm_db.release_connection(conn)


def _first_column(row: Any) -> Any:
    """Return the first column from tuple cursors and RealDictCursor rows."""
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


# ─────────────────────────────────────────────────────────────────────────────
# Model assessment reader
# ─────────────────────────────────────────────────────────────────────────────

def load_model_assessment_for_annotation(
    procurement_id: int,
    crm_db: Any,
) -> dict | None:
    """Return the current AI assessment for *procurement_id* as a plain dict.

    Returns None if no assessment exists yet.
    Fields returned:
        id, assessment_version, status, normalized_result (dict),
        proposed_route_profile, proposed_object_type, proposed_procurement_type,
        confidence, reasons, model_version, prompt_version
    """
    rows = crm_db.execute_query(
        """
        SELECT id, assessment_version, status,
               normalized_result,
               proposed_route_profile, proposed_object_type,
               proposed_procurement_type, confidence, reasons,
               model_version, prompt_version
        FROM procurement_ai_assessments
        WHERE procurement_id = %s AND is_current = TRUE
        LIMIT 1
        """,
        (procurement_id,),
    )
    if not rows:
        return None
    row = rows[0]
    nr = row.get("normalized_result") or {}
    if isinstance(nr, str):
        try:
            nr = json.loads(nr)
        except Exception:
            nr = {}
    return {
        "id": row["id"],
        "assessment_version": row["assessment_version"],
        "status": row["status"],
        "normalized_result": nr,
        "proposed_route_profile": row.get("proposed_route_profile"),
        "proposed_object_type": row.get("proposed_object_type"),
        "proposed_procurement_type": row.get("proposed_procurement_type"),
        "confidence": row.get("confidence"),
        "reasons": row.get("reasons"),
        "model_version": row.get("model_version"),
        "prompt_version": row.get("prompt_version"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Expert annotation reader
# ─────────────────────────────────────────────────────────────────────────────

def load_expert_annotation(
    procurement_id: int,
    crm_db: Any,
) -> dict | None:
    """Return the current expert annotation payload or None."""
    rows = crm_db.execute_query(
        """
        SELECT id, annotation_version, payload, created_by, created_at
        FROM crm_v3_expert_annotations
        WHERE procurement_id = %s AND is_current = TRUE
        LIMIT 1
        """,
        (procurement_id,),
    )
    if not rows:
        return None
    row = rows[0]
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    return {
        "annotation_id": row["id"],
        "annotation_version": row["annotation_version"],
        "payload": payload,
        "created_by": row.get("created_by"),
        "created_at": row.get("created_at"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Expert annotation writer — atomic versioned upsert
# ─────────────────────────────────────────────────────────────────────────────

def save_expert_annotation(
    procurement_id: int,
    payload: dict,
    created_by: str,
    crm_db: Any,
) -> int:
    """Atomically version-bump and store expert annotation.

    Algorithm (single transaction):
        1. SELECT MAX(annotation_version) for procurement_id → next_ver
        2. UPDATE is_current=FALSE for existing current row
        3. INSERT new row with is_current=TRUE

    Returns new annotation row id.

    Raises on any DB error — caller should catch and surface to UI.
    """
    payload_with_schema = dict(payload)
    payload_with_schema["schema_version"] = ANNOTATION_SCHEMA_VERSION

    with _transaction_connection(crm_db) as conn:
        with conn:  # transaction
            with conn.cursor() as cur:
                # Serialise version allocation for one procurement even when
                # no prior row exists yet (SELECT FOR UPDATE cannot do that).
                cur.execute(
                    "SELECT pg_advisory_xact_lock(%s, %s)",
                    (_ANNOTATION_LOCK_NAMESPACE, procurement_id),
                )
                # 1. Determine next version
                cur.execute(
                    """
                    SELECT COALESCE(MAX(annotation_version), 0) + 1
                    FROM crm_v3_expert_annotations
                    WHERE procurement_id = %s
                    """,
                    (procurement_id,),
                )
                next_version = _first_column(cur.fetchone())

                # 2. Retire current
                cur.execute(
                    """
                    UPDATE crm_v3_expert_annotations
                    SET is_current = FALSE
                    WHERE procurement_id = %s AND is_current = TRUE
                    """,
                    (procurement_id,),
                )

                # 3. Insert new current
                cur.execute(
                    """
                    INSERT INTO crm_v3_expert_annotations
                        (procurement_id, annotation_version, is_current,
                         decision_source, payload, created_by)
                    VALUES (%s, %s, TRUE, 'EXPERT_ANNOTATION', %s, %s)
                    RETURNING id
                    """,
                    (
                        procurement_id,
                        next_version,
                        json.dumps(payload_with_schema),
                        created_by,
                    ),
                )
                new_id = _first_column(cur.fetchone())
        return new_id


# ─────────────────────────────────────────────────────────────────────────────
# Audit trail writer
# ─────────────────────────────────────────────────────────────────────────────

def write_audit_row(
    procurement_id: int,
    model_raw: dict | None,
    annotation_payload: dict,
    crm_db: Any,
) -> None:
    """Write one audit row to crm_manual_assessments_audit after annotation save."""
    try:
        crm_db.execute_update(
            """
            INSERT INTO crm_manual_assessments_audit
                (procurement_id, action_type, user_name,
                 original_value, corrected_value, approved_for_training)
            VALUES (%s, 'EXPERT_ANNOTATION_SAVED', %s, %s, %s, FALSE)
            """,
            (
                procurement_id,
                annotation_payload.get("created_by", "unknown"),
                json.dumps(model_raw) if model_raw else None,
                json.dumps(annotation_payload),
            ),
        )
    except Exception as exc:
        # Audit failure must never block the primary annotation save.
        logger.warning("Audit write failed for procurement %s: %s", procurement_id, exc)


# ─────────────────────────────────────────────────────────────────────────────
# Taxonomy proposal writer
# ─────────────────────────────────────────────────────────────────────────────

def save_taxonomy_proposal(
    procurement_id: int,
    annotation_id: int | None,
    proposal: dict,
    created_by: str,
    crm_db: Any,
) -> None:
    """Insert one taxonomy proposal row.

    ``proposal`` must contain:
        proposal_type: str (CATEGORY|SUBCATEGORY|OBJECT_SECTOR|OBJECT_TYPE|OBJECT_SUBTYPE|WORK_STAGE)
        proposed_name: str
        proposed_parent_category: str | None
        expert_comment: str | None
    """
    crm_db.execute_update(
        """
        INSERT INTO crm_v3_taxonomy_proposals
            (annotation_id, procurement_id, proposed_name,
             proposed_parent_category, proposal_type,
             expert_comment, review_status, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, 'PENDING', %s)
        """,
        (
            annotation_id,
            procurement_id,
            proposal.get("proposed_name", ""),
            proposal.get("proposed_parent_category"),
            proposal.get("proposal_type", "CATEGORY"),
            proposal.get("expert_comment"),
            created_by,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Taxonomy / category selectors
# ─────────────────────────────────────────────────────────────────────────────

def load_categories_for_selector(crm_db: Any) -> list[dict]:
    """Return active categories ordered by sort_order.

    Each item: {code, name}
    """
    try:
        rows = crm_db.execute_query(
            """
            SELECT category_code, category_name
            FROM crm_product_categories
            WHERE is_active = TRUE
            ORDER BY sort_order, category_code
            """
        )
        return [{"code": r["category_code"], "name": r["category_name"]} for r in (rows or [])]
    except Exception as exc:
        logger.warning("load_categories_for_selector failed: %s", exc)
        return []


def load_subcategories(category_code: str, crm_db: Any) -> list[dict]:
    """Return subcategories for *category_code* ordered by name.

    Each item: {code, name}
    """
    try:
        rows = crm_db.execute_query(
            """
            SELECT subcategory_code, subcategory_name
            FROM crm_product_subcategories
            WHERE category_code = %s
            ORDER BY subcategory_name
            """,
            (category_code,),
        )
        return [{"code": r["subcategory_code"], "name": r["subcategory_name"]} for r in (rows or [])]
    except Exception as exc:
        logger.warning("load_subcategories failed for %s: %s", category_code, exc)
        return []


def collect_expert_object_types(crm_db: Any) -> list[str]:
    """Return distinct expert_object_type values from previously saved expert annotations.

    IMPORTANT: MODEL RAW (procurement_ai_assessments) is NOT queried here.
    MODEL values are free-text produced by the model and may contain errors,
    synonyms or wrong register — they are exactly what experts correct.

    Source of suggestions: crm_v3_expert_annotations.payload->>'expert_object_type'
    These are values that a human expert already validated and wrote.
    They are used as autocomplete suggestions only, not as canonical taxonomy.
    """
    try:
        rows = crm_db.execute_query(
            """
            SELECT DISTINCT payload->>'expert_object_type' AS obj
            FROM crm_v3_expert_annotations
            WHERE is_current = TRUE
              AND payload->>'expert_object_type' IS NOT NULL
              AND payload->>'expert_object_type' != ''
            ORDER BY obj
            LIMIT 200
            """
        )
        return [r["obj"] for r in (rows or []) if r.get("obj")]
    except Exception as exc:
        logger.warning("collect_expert_object_types failed: %s", exc)
        return []


def collect_expert_work_stages(crm_db: Any) -> list[str]:
    """Return distinct expert_work_stage values from previously saved expert annotations.

    IMPORTANT: MODEL RAW is NOT the source.  Only human-authored expert values.
    """
    try:
        rows = crm_db.execute_query(
            """
            SELECT DISTINCT payload->>'expert_work_stage' AS stg
            FROM crm_v3_expert_annotations
            WHERE is_current = TRUE
              AND payload->>'expert_work_stage' IS NOT NULL
              AND payload->>'expert_work_stage' != ''
            ORDER BY stg
            LIMIT 100
            """
        )
        return [r["stg"] for r in (rows or []) if r.get("stg")]
    except Exception as exc:
        logger.warning("collect_expert_work_stages failed: %s", exc)
        return []


def collect_expert_object_subtypes(crm_db: Any) -> list[str]:
    """Return distinct expert_object_subtype values from previously saved expert annotations."""
    try:
        rows = crm_db.execute_query(
            """
            SELECT DISTINCT payload->>'expert_object_subtype' AS sub
            FROM crm_v3_expert_annotations
            WHERE is_current = TRUE
              AND payload->>'expert_object_subtype' IS NOT NULL
              AND payload->>'expert_object_subtype' != ''
            ORDER BY sub
            LIMIT 200
            """
        )
        return [r["sub"] for r in (rows or []) if r.get("sub")]
    except Exception as exc:
        logger.warning("collect_expert_object_subtypes failed: %s", exc)
        return []
