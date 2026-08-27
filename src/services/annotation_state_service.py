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
from src.services.annotation_staged import is_partially_reviewed, is_staged_complete
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
            "expert_object_sector": None,
            "expert_object_type": None,
            "expert_object_subtype": None,
            "expert_procurement_mode": None,
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
            # Primary progress: full staged completeness (object+mode+category).
            "is_reviewed": staged,
            "is_category_reviewed": bool(scope),
            "is_staged_complete": staged,
            "is_partial": partial,
            "is_not_interesting": outcome == NOT_INTERESTING or scope == OUT_OF_CATEGORY,
            "is_legacy_negative": legacy,
            "expert_category_scope": scope,
            "expert_category_codes": category_codes_of(payload),
            "expert_object_sector": object_sector_of(payload),
            "expert_object_type": object_type_of(payload),
            "expert_object_subtype": object_subtype_of(payload),
            "expert_procurement_mode": procurement_mode_of(payload),
            "expert_commercial_verdict": payload.get("expert_commercial_verdict"),
            "expert_scope_verdict": payload.get("expert_scope_verdict"),
            "annotation_completeness": payload.get("annotation_completeness"),
            "payload": payload,
        }
    return states


def annotation_state_counts(states: dict[int, dict]) -> dict[str, int]:
    """Staged progress counters.

    ALL = UNREVIEWED + REVIEWED where REVIEWED means full staged completeness.
    Category secondary filters still use expert_category_scope.
    Legacy / category-only annotations without object/mode stay UNREVIEWED (partial).
    """
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
    legacy = sum(1 for value in states.values() if value.get("is_legacy_negative"))
    # Compatibility: old NOT_INTERESTING = legacy + new out-of-category
    not_interesting = legacy + out_of_category
    return {
        "ALL": total,
        UNREVIEWED: total - reviewed,
        REVIEWED: reviewed,
        OUT_OF_CATEGORY: out_of_category,
        IN_CATEGORY: in_category,
        UNCERTAIN: uncertain,
        LEGACY_NOT_INTERESTING: legacy,
        NOT_INTERESTING: not_interesting,
        PROFILED: max(0, reviewed - out_of_category),
        UNANNOTATED: total - reviewed,
        ANNOTATED: reviewed,
    }
