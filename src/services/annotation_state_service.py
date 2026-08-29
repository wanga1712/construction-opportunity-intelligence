"""Batch projection of current human expert-annotation state."""
from __future__ import annotations

from typing import Any

from src.services.annotation_category_gate import (
    IN_CATEGORY,
    LEGACY_NOT_INTERESTING,
    OUT_OF_CATEGORY,
    UNCERTAIN,
    category_codes_of,
    category_scope_of,
    is_legacy_negative_payload,
)
from src.services.annotation_staged import is_partially_reviewed, is_staged_complete, subcategory_codes_of
from src.services.expert_commercial_entry import (
    COMMERCIAL,
    NON_COMMERCIAL,
    commercial_entry_of,
    legacy_commercial_state,
)
from src.services.expert_medal_stage import medal_of
from src.services.expert_object_taxonomy import (
    object_sector_of,
    object_subtype_of,
    object_type_of,
)
from src.services.expert_procurement_mode import procurement_mode_of

# Re-export filter keys for UI/tests.
__all__ = [
    "UNANNOTATED",
    "ANNOTATED",
    "NOT_INTERESTING",
    "UNREVIEWED",
    "REVIEWED",
    "PROFILED",
    "OUT_OF_CATEGORY",
    "IN_CATEGORY",
    "UNCERTAIN",
    "LEGACY_NOT_INTERESTING",
    "COMMERCIAL",
    "NON_COMMERCIAL",
    "classify_annotation_payload",
    "load_current_annotation_states",
    "annotation_state_counts",
]

UNANNOTATED = "UNANNOTATED"
ANNOTATED = "ANNOTATED"
NOT_INTERESTING = "NOT_INTERESTING"
UNREVIEWED = "UNREVIEWED"
REVIEWED = "REVIEWED"
PROFILED = "PROFILED"


def classify_annotation_payload(payload: dict | None) -> str:
    """Compatibility outcome for older consumers.

    Stage-1 authority is expert_category_scope when present. Legacy
    OUT_OF_PROFILE/NCE remains NOT_INTERESTING only when category_scope absent.
    """
    if payload is None:
        return UNANNOTATED
    scope = category_scope_of(payload)
    if scope == OUT_OF_CATEGORY:
        return OUT_OF_CATEGORY
    if scope in (IN_CATEGORY, UNCERTAIN):
        return ANNOTATED
    if is_legacy_negative_payload(payload):
        return NOT_INTERESTING
    return ANNOTATED


def load_current_annotation_states(procurement_ids: list[int], crm_db: Any) -> dict[int, dict]:
    """Load all current rows in one query and return a total projection."""
    ids = list(dict.fromkeys(int(value) for value in procurement_ids))
    states = {
        pid: {
            "has_annotation": False,
            "annotation_id": None,
            "annotation_version": None,
            "created_at": None,
            "annotation_state": UNANNOTATED,
            "is_reviewed": False,
            "is_category_reviewed": False,
            "is_staged_complete": False,
            "is_partial": False,
            "is_not_interesting": False,
            "is_legacy_negative": False,
            "expert_category_scope": None,
            "expert_category_codes": [],
            "expert_subcategory_codes": [],
            "expert_object_sector": None,
            "expert_object_type": None,
            "expert_object_subtype": None,
            "expert_procurement_mode": None,
            "expert_commercial_entry": None,
            "expert_medal": None,
            "legacy_commercial_state": None,
            "expert_commercial_verdict": None,
            "expert_scope_verdict": None,
            "annotation_completeness": None,
            "payload": None,
        }
        for pid in ids
    }
    if not ids:
        return states
    rows = crm_db.execute_query(
        """SELECT id, procurement_id, annotation_version, created_at, payload
           FROM crm_v3_expert_annotations
           WHERE is_current = TRUE AND procurement_id = ANY(%s)""",
        (ids,),
    )
    for row in rows:
        payload = row.get("payload") or {}
        pid = int(row["procurement_id"])
        scope = category_scope_of(payload)
        legacy = is_legacy_negative_payload(payload)
        outcome = classify_annotation_payload(payload)
        staged = is_staged_complete(payload)
        partial = is_partially_reviewed(payload)
        is_rev = bool(scope or legacy)
        states[pid] = {
            "has_annotation": True,
            "annotation_id": row.get("id"),
            "annotation_version": row.get("annotation_version"),
            "created_at": row.get("created_at"),
            "annotation_state": outcome,
            "is_reviewed": is_rev,
            "is_category_reviewed": bool(scope),
            "is_staged_complete": staged,
            "is_partial": partial,
            "is_not_interesting": outcome == NOT_INTERESTING or scope == OUT_OF_CATEGORY,
            "is_legacy_negative": legacy,
            "expert_category_scope": scope,
            "expert_category_codes": category_codes_of(payload),
            "expert_subcategory_codes": subcategory_codes_of(payload),
            "expert_object_sector": object_sector_of(payload),
            "expert_object_type": object_type_of(payload),
            "expert_object_subtype": object_subtype_of(payload),
            "expert_procurement_mode": procurement_mode_of(payload),
            "expert_commercial_entry": commercial_entry_of(payload),
            "expert_medal": medal_of(payload),
            "legacy_commercial_state": legacy_commercial_state(payload),
            "expert_commercial_verdict": payload.get("expert_commercial_verdict"),
            "expert_scope_verdict": payload.get("expert_scope_verdict"),
            "annotation_completeness": payload.get("annotation_completeness"),
            "payload": payload,
        }
    return states


def annotation_state_counts(states: dict[int, dict]) -> dict[str, int]:
    """Staged progress counters including commercial secondary filters."""
    total = len(states)
    reviewed = sum(1 for value in states.values() if value.get("is_reviewed"))
    out_of_category = sum(
        1 for value in states.values() if value.get("expert_category_scope") == OUT_OF_CATEGORY
    )
    in_category = sum(
        1 for value in states.values() if value.get("expert_category_scope") == IN_CATEGORY
    )
    uncertain = sum(
        1 for value in states.values() if value.get("expert_category_scope") == UNCERTAIN
    )
    commercial = sum(
        1 for value in states.values() if value.get("expert_commercial_entry") == COMMERCIAL
    )
    non_commercial = sum(
        1 for value in states.values() if value.get("expert_commercial_entry") == NON_COMMERCIAL
    )
    legacy = sum(1 for value in states.values() if value.get("is_legacy_negative"))
    not_interesting = legacy + out_of_category
    return {
        "ALL": total,
        UNREVIEWED: total - reviewed,
        REVIEWED: reviewed,
        OUT_OF_CATEGORY: out_of_category,
        IN_CATEGORY: in_category,
        UNCERTAIN: uncertain,
        COMMERCIAL: commercial,
        NON_COMMERCIAL: non_commercial,
        LEGACY_NOT_INTERESTING: legacy,
        NOT_INTERESTING: not_interesting,
        PROFILED: max(0, reviewed - out_of_category),
        UNANNOTATED: total - reviewed,
        ANNOTATED: reviewed,
    }


def count_annotation_states_sql(procurement_ids: list[int], crm_db: Any) -> dict[str, int]:
    """Compute review filter counts via SQL aggregation ??? no full Python load needed.

    Returns exact same keys as annotation_state_counts().
    """
    ids = list(dict.fromkeys(int(v) for v in procurement_ids))
    total = len(ids)
    if not ids:
        return {"ALL": 0, UNREVIEWED: 0, REVIEWED: 0, OUT_OF_CATEGORY: 0,
                IN_CATEGORY: 0, UNCERTAIN: 0, COMMERCIAL: 0, NON_COMMERCIAL: 0,
                LEGACY_NOT_INTERESTING: 0, NOT_INTERESTING: 0, PROFILED: 0,
                UNANNOTATED: 0, ANNOTATED: 0}

    rows = crm_db.execute_query(
        """SELECT
              CASE 
                WHEN jsonb_typeof(payload -> 'expert_category_scope') = 'object' 
                THEN payload -> 'expert_category_scope' ->> 'verdict' 
                ELSE payload ->> 'expert_category_scope' 
              END AS scope,
              payload ->> 'expert_commercial_entry' AS commercial,
              payload ->> 'expert_commercial_verdict' AS comm_verdict,
              payload ->> 'expert_scope_verdict' AS scope_verdict,
              payload ->> 'expert_medal' AS medal,
              payload -> 'error_reasons' AS error_reasons,
              count(*) AS cnt
           FROM crm_v3_expert_annotations
           WHERE is_current = TRUE AND procurement_id = ANY(%s)
           GROUP BY scope, commercial, comm_verdict, scope_verdict, medal, error_reasons""",
        (ids,),
    )
    annotated_cnt = 0
    out_cat = 0; in_cat = 0; uncertain = 0
    commercial = 0; non_commercial = 0
    legacy = 0
    for r in (rows or []):
        cnt = int(r["cnt"])
        annotated_cnt += cnt
        scope = r.get("scope") or ""
        comm = r.get("commercial") or ""
        
        reasons = r.get("error_reasons") or []
        if isinstance(reasons, str):
            reasons = [reasons]
        is_legacy = (not scope) and (
            r.get("comm_verdict") == "NO_COMMERCIAL_ENTRY"
            or r.get("scope_verdict") == "OUT_OF_PROFILE"
            or r.get("medal") == "NCE"
            or "OUT_OF_PROFILE" in reasons
        )
        
        if scope == OUT_OF_CATEGORY:
            out_cat += cnt
        elif scope == IN_CATEGORY:
            in_cat += cnt
        elif scope == UNCERTAIN:
            uncertain += cnt
            
        if is_legacy:
            legacy += cnt

        if comm == COMMERCIAL:
            commercial += cnt
        elif comm == NON_COMMERCIAL:
            non_commercial += cnt

    reviewed = in_cat + out_cat + uncertain + legacy
    not_interesting = legacy + out_cat
    return {
        "ALL": total,
        UNREVIEWED: total - reviewed,
        REVIEWED: reviewed,
        OUT_OF_CATEGORY: out_cat,
        IN_CATEGORY: in_cat,
        UNCERTAIN: uncertain,
        COMMERCIAL: commercial,
        NON_COMMERCIAL: non_commercial,
        LEGACY_NOT_INTERESTING: legacy,
        NOT_INTERESTING: not_interesting,
        PROFILED: max(0, reviewed - out_cat),
        UNANNOTATED: total - annotated_cnt,
        ANNOTATED: annotated_cnt,
    }


def annotation_filter_sql_clause(selected_state: str) -> str:
    """Return a SQL WHERE fragment that implements the review filter on the procurement IDs.

    Returns '' (empty string) for 'ALL' filter.
    Requires LEFT JOIN crm_v3_expert_annotations ea
        ON ea.procurement_id = cp.id AND ea.is_current = TRUE
    """
    if selected_state == "ALL":
        return ""
    if selected_state == REVIEWED:
        return "AND ea.id IS NOT NULL AND ea.payload ->> 'expert_category_scope' IS NOT NULL AND ea.payload ->> 'expert_category_scope' != ''"
    if selected_state == UNREVIEWED:
        return "AND (ea.id IS NULL OR ea.payload ->> 'expert_category_scope' IS NULL OR ea.payload ->> 'expert_category_scope' = '')"
    if selected_state == OUT_OF_CATEGORY:
        return "AND ea.payload ->> 'expert_category_scope' = 'OUT_OF_CATEGORY'"
    if selected_state == IN_CATEGORY:
        return "AND ea.payload ->> 'expert_category_scope' = 'IN_CATEGORY'"
    if selected_state == UNCERTAIN:
        return "AND ea.payload ->> 'expert_category_scope' = 'UNCERTAIN'"
    if selected_state == COMMERCIAL:
        return "AND ea.payload ->> 'expert_commercial_entry' = 'COMMERCIAL'"
    if selected_state == NON_COMMERCIAL:
        return "AND ea.payload ->> 'expert_commercial_entry' = 'NON_COMMERCIAL'"
    if selected_state == LEGACY_NOT_INTERESTING:
        return "AND ea.id IS NOT NULL AND (ea.payload ->> 'expert_category_scope' IS NULL OR ea.payload ->> 'expert_category_scope' = '')"
    return ""


def filter_workset_ids_sql(procurement_ids: list[int], selected_review: str, crm_db: Any) -> list[int]:
    """Filter procurement_ids by selected review state in SQL before pagination."""
    if not procurement_ids or selected_review == "ALL":
        return procurement_ids
    scope_expr = "CASE WHEN jsonb_typeof(payload -> 'expert_category_scope') = 'object' THEN payload -> 'expert_category_scope' ->> 'verdict' ELSE payload ->> 'expert_category_scope' END"
    if selected_review == UNREVIEWED:
        sql = f"""
            SELECT p_id FROM unnest(%s::bigint[]) AS p_id
            WHERE p_id NOT IN (
                SELECT ea.procurement_id 
                FROM crm_v3_expert_annotations ea
                WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s)
                  AND (
                    ({scope_expr} IS NOT NULL AND {scope_expr} != '')
                    OR (({scope_expr} IS NULL OR {scope_expr} = '') AND (
                      ea.payload ->> 'expert_commercial_verdict' = 'NO_COMMERCIAL_ENTRY'
                      OR ea.payload ->> 'expert_scope_verdict' = 'OUT_OF_PROFILE'
                      OR ea.payload ->> 'expert_medal' = 'NCE'
                    ))
                  )
            )
        """
        rows = crm_db.execute_query(sql, (procurement_ids, procurement_ids))
    elif selected_review == REVIEWED:
        sql = f"""
            SELECT ea.procurement_id 
            FROM crm_v3_expert_annotations ea
            WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s)
              AND (
                ({scope_expr} IS NOT NULL AND {scope_expr} != '')
                OR (({scope_expr} IS NULL OR {scope_expr} = '') AND (
                  ea.payload ->> 'expert_commercial_verdict' = 'NO_COMMERCIAL_ENTRY'
                  OR ea.payload ->> 'expert_scope_verdict' = 'OUT_OF_PROFILE'
                  OR ea.payload ->> 'expert_medal' = 'NCE'
                ))
              )
        """
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == OUT_OF_CATEGORY:
        sql = f"SELECT ea.procurement_id FROM crm_v3_expert_annotations ea WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) AND {scope_expr} = 'OUT_OF_CATEGORY'"
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == IN_CATEGORY:
        sql = f"SELECT ea.procurement_id FROM crm_v3_expert_annotations ea WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) AND {scope_expr} = 'IN_CATEGORY'"
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == UNCERTAIN:
        sql = f"SELECT ea.procurement_id FROM crm_v3_expert_annotations ea WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) AND {scope_expr} = 'UNCERTAIN'"
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == COMMERCIAL:
        sql = f"SELECT ea.procurement_id FROM crm_v3_expert_annotations ea WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) AND ea.payload ->> 'expert_commercial_entry' = 'COMMERCIAL'"
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == NON_COMMERCIAL:
        sql = f"SELECT ea.procurement_id FROM crm_v3_expert_annotations ea WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) AND ea.payload ->> 'expert_commercial_entry' = 'NON_COMMERCIAL'"
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == LEGACY_NOT_INTERESTING:
        sql = f"""
            SELECT ea.procurement_id FROM crm_v3_expert_annotations ea 
            WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) 
              AND ({scope_expr} IS NULL OR {scope_expr} = '')
              AND (
                ea.payload ->> 'expert_commercial_verdict' = 'NO_COMMERCIAL_ENTRY'
                OR ea.payload ->> 'expert_scope_verdict' = 'OUT_OF_PROFILE'
                OR ea.payload ->> 'expert_medal' = 'NCE'
              )
        """
        rows = crm_db.execute_query(sql, (procurement_ids,))
    else:
        rows = []
    filtered = [r[0] if isinstance(r, (tuple, list)) else r.get("procurement_id") or r.get("p_id") for r in (rows or [])]
    filtered_set = set(int(x) for x in filtered)
    return [pid for pid in procurement_ids if pid in filtered_set]


LAW_FILTERS = (
    ("ALL", "\u0412\u0441\u0435"),
    ("44-\u0424\u0417", "44-\u0424\u0417"),
    ("223-\u0424\u0417", "223-\u0424\u0417"),
)

def count_law_states_sql(procurement_ids: list[int], crm_db: Any) -> dict[str, int]:
    """Compute law filter counts via SQL aggregation."""
    if not procurement_ids:
        return {"ALL": 0, "44-\u0424\u0417": 0, "223-\u0424\u0417": 0}
    rows = crm_db.execute_query(
        "SELECT source_table, count(*) AS cnt FROM crm_procurements WHERE id = ANY(%s) GROUP BY source_table",
        (procurement_ids,),
    )
    c44 = 0
    c223 = 0
    for r in (rows or []):
        stbl = r.get("source_table")
        cnt = int(r.get("cnt") or 0)
        if stbl == "reestr_contract_44_fz":
            c44 = cnt
        elif stbl == "reestr_contract_223_fz":
            c223 = cnt
    return {
        "ALL": len(procurement_ids),
        "44-\u0424\u0417": c44,
        "223-\u0424\u0417": c223,
    }

def filter_workset_ids_by_law(procurement_ids: list[int], selected_law: str, crm_db: Any) -> list[int]:
    """Filter procurement_ids by law in SQL before review filtering and pagination."""
    if not procurement_ids or selected_law == "ALL":
        return procurement_ids
    if selected_law == "44-\u0424\u0417":
        source_tbl = "reestr_contract_44_fz"
    elif selected_law == "223-\u0424\u0417":
        source_tbl = "reestr_contract_223_fz"
    else:
        return procurement_ids
        
    rows = crm_db.execute_query(
        "SELECT id FROM crm_procurements WHERE id = ANY(%s) AND source_table = %s",
        (procurement_ids, source_tbl),
    )
    matching = set(r["id"] for r in (rows or []))
    return [pid for pid in procurement_ids if pid in matching]
