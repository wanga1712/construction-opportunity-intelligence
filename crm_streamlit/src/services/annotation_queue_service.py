"""Expert annotation queue — bypasses torgi publication gate.

Queue authority: procurement_ai_assessments (is_current) JOIN crm_procurements.
Normal CRM publication SQL is NOT used for reachability; visibility is computed
for display/filtering only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Mapping, Optional, Sequence

from src.services.torgi_publication import (
    is_torgi_publication_visible,
    publication_schema_ready,
    source_lifecycle_allows_torgi,
    torgi_publication_sql_filters,
)

QUEUE_MODE_OPEN_ASSESSED = "open_assessed"
QUEUE_MODE_ALL_CURRENT = "all_current"

ANNOTATION_FILTER_ALL = "all"
ANNOTATION_FILTER_UNANNOTATED = "unannotated"
ANNOTATION_FILTER_ANNOTATED = "annotated"

MODEL_SOURCE_ALL = "all"
MODEL_SOURCE_RAW = "raw_available"
MODEL_SOURCE_LEGACY = "legacy"

PUBLICATION_FILTER_ALL = "all"
PUBLICATION_FILTER_VISIBLE = "visible"
PUBLICATION_FILTER_HIDDEN = "hidden"


class LifecycleLabel(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    OTHER = "OTHER"


def _canonical_open_sql(alias: str = "cp") -> str:
    return f"""
        {alias}.crm_stage = 'torgi'
        AND {alias}.award_status = 'submission_open'
        AND {alias}.end_date >= CURRENT_DATE
    """


def _current_assessment_sql(alias: str = "ai") -> str:
    return f"""
        {alias}.is_current = TRUE
        AND upper(coalesce({alias}.status, '')) NOT IN ('ERROR', 'FAILED')
        AND {alias}.normalized_result IS NOT NULL
    """


def _has_inference_run_column(crm_db: Any) -> bool:
    try:
        rows = crm_db.execute_query(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'procurement_ai_assessments'
              AND column_name = 'inference_run_id'
            LIMIT 1
            """
        )
        return bool(rows)
    except Exception:
        return False


def _has_inference_runs_table(crm_db: Any) -> bool:
    try:
        return bool(
            crm_db.execute_scalar(
                "SELECT to_regclass('public.crm_v3_model_inference_runs') IS NOT NULL"
            )
        )
    except Exception:
        return False


def _exclude_shadow_sql(ai_alias: str = "ai") -> str:
    return f"""
        (
            {ai_alias}.inference_run_id IS NULL
            OR NOT EXISTS (
                SELECT 1
                FROM crm_v3_model_inference_runs ir_ex
                WHERE ir_ex.id = {ai_alias}.inference_run_id
                  AND ir_ex.run_kind = 'SHADOW'
            )
        )
    """


def _annotation_exists_sql(proc_alias: str = "cp") -> str:
    return f"""
        EXISTS (
            SELECT 1
            FROM crm_v3_expert_annotations ea
            WHERE ea.procurement_id = {proc_alias}.id
              AND ea.is_current = TRUE
        )
    """


@dataclass(frozen=True)
class AnnotationQueueFilters:
    queue_mode: str = QUEUE_MODE_OPEN_ASSESSED
    annotation_status: str = ANNOTATION_FILTER_UNANNOTATED
    model_source: str = MODEL_SOURCE_ALL
    publication_visibility: str = PUBLICATION_FILTER_ALL
    model_category: str = "all"


def build_queue_where(
    filters: AnnotationQueueFilters,
    *,
    has_inference_run_id: bool = True,
    has_inference_runs_table: bool = True,
) -> tuple[str, list[Any]]:
    """Return SQL WHERE body (without WHERE keyword) and params."""
    clauses = [_current_assessment_sql("ai")]
    if has_inference_run_id and has_inference_runs_table:
        clauses.append(_exclude_shadow_sql("ai"))
    params: list[Any] = []

    if filters.queue_mode == QUEUE_MODE_OPEN_ASSESSED:
        clauses.append(_canonical_open_sql("cp"))
    elif filters.queue_mode != QUEUE_MODE_ALL_CURRENT:
        raise ValueError(f"Unknown queue_mode: {filters.queue_mode}")

    if filters.annotation_status == ANNOTATION_FILTER_UNANNOTATED:
        clauses.append(f"NOT {_annotation_exists_sql('cp')}")
    elif filters.annotation_status == ANNOTATION_FILTER_ANNOTATED:
        clauses.append(_annotation_exists_sql("cp"))

    if filters.model_source == MODEL_SOURCE_RAW and has_inference_run_id:
        clauses.append("ai.inference_run_id IS NOT NULL")
    elif filters.model_source == MODEL_SOURCE_LEGACY and has_inference_run_id:
        clauses.append("ai.inference_run_id IS NULL")

    if filters.model_category and filters.model_category != "all":
        code = filters.model_category
        if has_inference_run_id and has_inference_runs_table:
            clauses.append(
                """
            (
                EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements(
                        coalesce(ai.normalized_result->'category_opportunities', '[]'::jsonb)
                    ) elem
                    WHERE elem->>'category_code' = %s
                )
                OR EXISTS (
                    SELECT 1
                    FROM crm_v3_model_inference_runs ir_cat
                    JOIN LATERAL jsonb_array_elements(
                        coalesce(
                            ir_cat.validated_model_result->'commercial_category_hypotheses',
                            '[]'::jsonb
                        )
                    ) vh ON TRUE
                    WHERE ir_cat.id = ai.inference_run_id
                      AND coalesce(vh->>'category_code', vh->>'commercial_category_code') = %s
                )
            )
            """
            )
            params.extend([code, code])
        else:
            clauses.append(
                """
            EXISTS (
                SELECT 1
                FROM jsonb_array_elements(
                    coalesce(ai.normalized_result->'category_opportunities', '[]'::jsonb)
                ) elem
                WHERE elem->>'category_code' = %s
            )
            """
            )
            params.append(code)

    return " AND ".join(clauses), params


def queue_order_sql(filters: AnnotationQueueFilters) -> str:
    if filters.queue_mode == QUEUE_MODE_OPEN_ASSESSED:
        return "cp.end_date ASC NULLS LAST, cp.id ASC"
    return "ai.id ASC, cp.id ASC"


def fetch_queue_ids(
    crm_db: Any,
    filters: AnnotationQueueFilters,
) -> list[int]:
    has_ir = _has_inference_run_column(crm_db)
    has_ir_table = _has_inference_runs_table(crm_db)
    where_sql, params = build_queue_where(
        filters,
        has_inference_run_id=has_ir,
        has_inference_runs_table=has_ir_table,
    )
    order = queue_order_sql(filters)
    rows = crm_db.execute_query(
        f"""
        SELECT cp.id
        FROM procurement_ai_assessments ai
        JOIN crm_procurements cp ON cp.id = ai.procurement_id
        WHERE {where_sql}
        ORDER BY {order}
        """,
        tuple(params),
    )
    ids = [int(r["id"]) for r in (rows or [])]
    if filters.publication_visibility == PUBLICATION_FILTER_ALL:
        return ids
    vis_map = batch_publication_visibility(crm_db, ids)
    if filters.publication_visibility == PUBLICATION_FILTER_VISIBLE:
        return [pid for pid in ids if vis_map.get(pid)]
    return [pid for pid in ids if not vis_map.get(pid)]


def fetch_queue_counters(crm_db: Any) -> dict[str, int]:
    has_ir = _has_inference_run_column(crm_db)
    has_ir_table = _has_inference_runs_table(crm_db)
    shadow_clause = _exclude_shadow_sql("ai") if has_ir and has_ir_table else "TRUE"
    pub_ready = publication_schema_ready(crm_db)
    if pub_ready:
        pub_visible_cte = f"""
        pub_visible AS (
            SELECT DISTINCT cp.id
            FROM crm_procurements cp
            JOIN canonical_open co ON co.id = cp.id
            JOIN open_assessed oa ON oa.id = cp.id
            WHERE TRUE
            {torgi_publication_sql_filters()}
        )"""
        pub_visible_select = "(SELECT count(*) FROM pub_visible)"
        pub_hidden_select = "(SELECT count(*) FROM open_assessed) - (SELECT count(*) FROM pub_visible)"
    else:
        pub_visible_cte = "pub_visible AS (SELECT NULL::bigint AS id WHERE FALSE)"
        pub_visible_select = "0"
        pub_hidden_select = "0"
    rows = crm_db.execute_query(
        f"""
        WITH canonical_open AS (
            SELECT cp.id
            FROM crm_procurements cp
            WHERE {_canonical_open_sql("cp")}
        ),
        open_assessed AS (
            SELECT DISTINCT cp.id
            FROM procurement_ai_assessments ai
            JOIN crm_procurements cp ON cp.id = ai.procurement_id
            WHERE {_current_assessment_sql("ai")}
              AND {shadow_clause}
              AND {_canonical_open_sql("cp")}
        ),
        {pub_visible_cte}
        SELECT
            (SELECT count(*) FROM canonical_open) AS canonical_open,
            (SELECT count(*) FROM open_assessed) AS open_assessed,
            (SELECT count(*) FROM canonical_open) -
                (SELECT count(*) FROM open_assessed) AS open_without_assessment,
            (
                SELECT count(*) FROM open_assessed oa
                WHERE EXISTS (
                    SELECT 1 FROM crm_v3_expert_annotations ea
                    WHERE ea.procurement_id = oa.id AND ea.is_current = TRUE
                )
            ) AS open_assessed_annotated,
            (
                SELECT count(*) FROM open_assessed oa
                WHERE NOT EXISTS (
                    SELECT 1 FROM crm_v3_expert_annotations ea
                    WHERE ea.procurement_id = oa.id AND ea.is_current = TRUE
                )
            ) AS open_assessed_unannotated,
            (
                SELECT count(*)
                FROM procurement_ai_assessments ai
                WHERE {_current_assessment_sql("ai")}
                  AND {shadow_clause}
            ) AS all_current_assessments,
            {pub_visible_select} AS publication_visible_open_assessed,
            {pub_hidden_select} AS publication_hidden_open_assessed,
            (
                SELECT count(*) FROM crm_v3_expert_annotations
                WHERE is_current = TRUE
            ) AS expert_annotations_total
        """
    )
    row = (rows or [{}])[0]
    return {k: int(row.get(k) or 0) for k in row}


def fetch_model_category_choices(crm_db: Any) -> list[str]:
    has_ir = _has_inference_run_column(crm_db) and _has_inference_runs_table(crm_db)
    validated_union = ""
    if has_ir:
        validated_union = """
            UNION
            SELECT coalesce(vh->>'category_code', vh->>'commercial_category_code')
            FROM procurement_ai_assessments ai
            JOIN crm_v3_model_inference_runs ir ON ir.id = ai.inference_run_id
            CROSS JOIN LATERAL jsonb_array_elements(
                coalesce(ir.validated_model_result->'commercial_category_hypotheses', '[]'::jsonb)
            ) vh
            WHERE ai.is_current = TRUE
              AND coalesce(vh->>'category_code', vh->>'commercial_category_code') IS NOT NULL
        """
    rows = crm_db.execute_query(
        f"""
        SELECT DISTINCT cat_code AS code
        FROM (
            SELECT elem->>'category_code' AS cat_code
            FROM procurement_ai_assessments ai
            CROSS JOIN LATERAL jsonb_array_elements(
                coalesce(ai.normalized_result->'category_opportunities', '[]'::jsonb)
            ) elem
            WHERE ai.is_current = TRUE
              AND elem->>'category_code' IS NOT NULL
              AND elem->>'category_code' != ''
            {validated_union}
        ) x
        WHERE cat_code IS NOT NULL AND cat_code != ''
        ORDER BY cat_code
        """
    )
    return [r["code"] for r in (rows or []) if r.get("code")]


def batch_publication_visibility(
    crm_db: Any,
    procurement_ids: Sequence[int],
) -> dict[int, bool]:
    if not procurement_ids:
        return {}
    if not publication_schema_ready(crm_db):
        return {pid: False for pid in procurement_ids}

    placeholders = ",".join(["%s"] * len(procurement_ids))
    proc_rows = crm_db.execute_query(
        f"""
        SELECT id, crm_stage, award_status, end_date
        FROM crm_procurements
        WHERE id IN ({placeholders})
        """,
        tuple(procurement_ids),
    )
    ai_rows = crm_db.execute_query(
        f"""
        SELECT procurement_id, status, normalized_result, inference_run_id
        FROM procurement_ai_assessments
        WHERE procurement_id IN ({placeholders})
          AND is_current = TRUE
        """,
        tuple(procurement_ids),
    )
    opp_rows = crm_db.execute_query(
        f"""
        SELECT procurement_id, commercial_category_code, commercial_state, status
        FROM crm_procurement_category_opportunities
        WHERE procurement_id IN ({placeholders})
          AND status = 'CURRENT'
        """,
        tuple(procurement_ids),
    )

    ai_by_pid = {int(r["procurement_id"]): r for r in (ai_rows or [])}
    opps_by_pid: dict[int, list[dict]] = {}
    for r in opp_rows or []:
        pid = int(r["procurement_id"])
        opps_by_pid.setdefault(pid, []).append(dict(r))

    out: dict[int, bool] = {}
    today = date.today()
    for pr in proc_rows or []:
        pid = int(pr["id"])
        nr = ai_by_pid.get(pid, {}).get("normalized_result")
        if isinstance(nr, str):
            try:
                nr = json.loads(nr)
            except Exception:
                nr = None
        ai_row = {
            "status": ai_by_pid.get(pid, {}).get("status"),
            "normalized_result": nr,
        }
        visible, _ = is_torgi_publication_visible(
            crm_stage=pr.get("crm_stage") or "",
            award_status=pr.get("award_status") or "",
            end_date=pr.get("end_date"),
            ai_row=ai_row,
            opportunities=opps_by_pid.get(pid, []),
            today=today,
        )
        out[pid] = visible
    for pid in procurement_ids:
        out.setdefault(pid, False)
    return out


def batch_annotated_flags(crm_db: Any, procurement_ids: Sequence[int]) -> dict[int, bool]:
    if not procurement_ids:
        return {}
    placeholders = ",".join(["%s"] * len(procurement_ids))
    rows = crm_db.execute_query(
        f"""
        SELECT procurement_id
        FROM crm_v3_expert_annotations
        WHERE procurement_id IN ({placeholders})
          AND is_current = TRUE
        """,
        tuple(procurement_ids),
    )
    annotated = {int(r["procurement_id"]) for r in (rows or [])}
    return {pid: pid in annotated for pid in procurement_ids}


def fetch_procurement_header(crm_db: Any, procurement_id: int) -> dict | None:
    rows = crm_db.execute_query(
        """
        SELECT cp.id, cp.auction_name, cp.initial_price, cp.final_price,
               cp.delivery_region,
               cp.okpd_code, cp.okpd_name, cp.crm_stage, cp.award_status,
               cp.end_date, cp.contract_number, cp.customer, cp.source_table,
               cp.source_id, cp.tender_link, cp.crm_created_at,
               cp.crm_updated_at, cp.source_updated_at
        FROM crm_procurements cp
        WHERE cp.id = %s
        LIMIT 1
        """,
        (procurement_id,),
    )
    return dict(rows[0]) if rows else None


def lifecycle_label(row: Mapping[str, Any], *, today: date | None = None) -> str:
    today = today or date.today()
    if source_lifecycle_allows_torgi(
        crm_stage=row.get("crm_stage") or "",
        award_status=row.get("award_status") or "",
        end_date=row.get("end_date"),
        today=today,
    ):
        return LifecycleLabel.OPEN.value
    stage = (row.get("crm_stage") or "").lower()
    if stage in ("torgi", "komissia", "consideration"):
        return LifecycleLabel.CLOSED.value
    return LifecycleLabel.OTHER.value
