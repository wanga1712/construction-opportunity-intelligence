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
        states[pid] = {
            "has_annotation": True,
            "annotation_id": row.get("id"),
            "annotation_version": row.get("annotation_version"),
            "created_at": row.get("created_at"),
            "annotation_state": outcome,
            "is_reviewed": staged,
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
    reviewed = sum(1 for value in states.values() if value.get("is_staged_complete"))
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
    """Compute review filter counts via SQL ??? no full Python load needed.

    Returns the same keys as annotation_state_counts() but uses SQL aggregation.
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
              payload ->> 'expert_category_scope' AS scope,
              payload ->> 'expert_commercial_entry' AS commercial,
              CASE WHEN payload ->> 'expert_category_scope' IS NOT NULL
                        AND payload ->> 'expert_category_scope' != ''
                   THEN TRUE ELSE FALSE END AS has_scope,
              count(*) AS cnt
           FROM crm_v3_expert_annotations
           WHERE is_current = TRUE AND procurement_id = ANY(%s)
           GROUP BY scope, commercial, has_scope""",
        (ids,),
    )
    # Accumulate
    annotated_ids = 0
    out_cat = 0; in_cat = 0; uncertain = 0
    commercial = 0; non_commercial = 0
    reviewed = 0; legacy = 0
    for r in (rows or []):
        cnt = int(r["cnt"])
        annotated_ids += cnt
        scope = r.get("scope") or ""
        comm = r.get("commercial") or ""
        if scope == OUT_OF_CATEGORY:
            out_cat += cnt
            reviewed += cnt  # OUT is considered reviewed
        elif scope == IN_CATEGORY:
            in_cat += cnt
            reviewed += cnt
        elif scope == UNCERTAIN:
            uncertain += cnt
            reviewed += cnt
        # legacy negative: scope empty but has annotation -> count as legacy
        if not scope and cnt:
            legacy += cnt
        if comm == COMMERCIAL:
            commercial += cnt
        elif comm == NON_COMMERCIAL:
            non_commercial += cnt
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
        UNANNOTATED: total - annotated_ids,
        ANNOTATED: annotated_ids,
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
