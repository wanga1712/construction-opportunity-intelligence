"""Batch projection of current human expert-annotation state."""
from __future__ import annotations

from typing import Any

UNANNOTATED = "UNANNOTATED"
ANNOTATED = "ANNOTATED"
NOT_INTERESTING = "NOT_INTERESTING"


def classify_annotation_payload(payload: dict | None) -> str:
    if payload is None:
        return UNANNOTATED
    reasons = payload.get("error_reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    if (
        payload.get("expert_commercial_verdict") == "NO_COMMERCIAL_ENTRY"
        or payload.get("expert_scope_verdict") == "OUT_OF_PROFILE"
        or payload.get("expert_medal") == "NCE"
        or "OUT_OF_PROFILE" in reasons
    ):
        return NOT_INTERESTING
    return ANNOTATED


def load_current_annotation_states(procurement_ids: list[int], crm_db: Any) -> dict[int, dict]:
    """Load all current rows in one query and return a total projection."""
    ids = list(dict.fromkeys(int(value) for value in procurement_ids))
    states = {
        pid: {"has_annotation": False, "annotation_id": None,
              "annotation_version": None, "created_at": None,
              "annotation_state": UNANNOTATED,
              "expert_commercial_verdict": None, "expert_scope_verdict": None,
              "annotation_completeness": None, "payload": None}
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
        states[pid] = {
            "has_annotation": True,
            "annotation_id": row.get("id"),
            "annotation_version": row.get("annotation_version"),
            "created_at": row.get("created_at"),
            "annotation_state": classify_annotation_payload(payload),
            "expert_commercial_verdict": payload.get("expert_commercial_verdict"),
            "expert_scope_verdict": payload.get("expert_scope_verdict"),
            "annotation_completeness": payload.get("annotation_completeness"),
            "payload": payload,
        }
    return states


def annotation_state_counts(states: dict[int, dict]) -> dict[str, int]:
    counts = {UNANNOTATED: 0, ANNOTATED: 0, NOT_INTERESTING: 0}
    for value in states.values():
        counts[value["annotation_state"]] += 1
    counts["ALL"] = len(states)
    return counts
