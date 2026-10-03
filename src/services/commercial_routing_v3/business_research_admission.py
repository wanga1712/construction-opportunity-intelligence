"""BUSINESS_RESEARCH_ADMISSION_V2 - single canonical admission contract.

Matrix (the ONLY place the business contract is encoded):

    OPEN    + DIRECT_GOODS                 -> ELIGIBLE
    OPEN    + WORKS_WITH_EMBEDDED_PRODUCTS -> ELIGIBLE
    OPEN    + DESIGN_PROJECT               -> ELIGIBLE
    AWARDED + DIRECT_GOODS                 -> EXCLUDED (AWARDED_DIRECT_GOODS)
    AWARDED + WORKS_WITH_EMBEDDED_PRODUCTS -> ELIGIBLE
    AWARDED + DESIGN_PROJECT               -> ELIGIBLE
    WAITING_AWARD + ANY_SCOPE              -> HOLD (WAITING_FOR_AWARD)
    anything else (unknown lifecycle/scope) -> HOLD (fail closed)

Runtime consumers never re-derive this matrix.  They read the *persisted*
decision so producer / reconciliation / claim / UI can never disagree:

  * ``crm_procurement_scope_authority.admission_state``          -> producer gate, awarded UI
  * ``document_processing_queue.category_context->>'admission_state'`` -> claim gate

``decide_admission`` is used only when (re)materialising the authority.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ADMISSION_POLICY_VERSION = "BUSINESS_RESEARCH_ADMISSION_V2"

ELIGIBLE = "ELIGIBLE"
EXCLUDED = "EXCLUDED"
HOLD = "HOLD"

REASON_CURRENT = "CURRENT_BUSINESS_ADMISSION"
REASON_AWARDED_DIRECT = "AWARDED_DIRECT_GOODS"
REASON_WAITING = "WAITING_FOR_AWARD"
REASON_POLICY_UNDECIDED = "POLICY_UNDECIDED"
REASON_UNKNOWN_SCOPE = "UNKNOWN_SCOPE"
REASON_AUTHORITY_MISSING = "AUTHORITY_MISSING"

SCOPE_DIRECT_GOODS = "DIRECT_GOODS"
SCOPE_WORKS_EMBEDDED = "WORKS_WITH_EMBEDDED_PRODUCTS"
SCOPE_DESIGN = "DESIGN_PROJECT"
SCOPE_UNKNOWN = "UNKNOWN"

LC_OPEN = "OPEN"
LC_AWARDED = "AWARDED"
LC_WAITING = "WAITING_SOURCE_OUTCOME"

_WAITING_LIFECYCLES = {LC_WAITING, "WAITING_AWARD", "WAITING"}

_ELIGIBLE_MATRIX = {
    (LC_OPEN, SCOPE_DIRECT_GOODS),
    (LC_OPEN, SCOPE_WORKS_EMBEDDED),
    (LC_OPEN, SCOPE_DESIGN),
    (LC_AWARDED, SCOPE_WORKS_EMBEDDED),
    (LC_AWARDED, SCOPE_DESIGN),
}


def decide_admission(source_lifecycle: Any, scope_type: Any) -> Tuple[str, str]:
    """Canonical BUSINESS_RESEARCH_ADMISSION_V2 decision (fail-closed)."""
    lc = str(source_lifecycle or "").strip().upper()
    sc = str(scope_type or "").strip().upper()
    if lc in _WAITING_LIFECYCLES:
        return HOLD, REASON_WAITING
    if lc == LC_AWARDED and sc == SCOPE_DIRECT_GOODS:
        return EXCLUDED, REASON_AWARDED_DIRECT
    if (lc, sc) in _ELIGIBLE_MATRIX:
        return ELIGIBLE, REASON_CURRENT
    if sc in ("", SCOPE_UNKNOWN):
        return HOLD, REASON_UNKNOWN_SCOPE
    return HOLD, REASON_POLICY_UNDECIDED


def is_queue_eligible(record: Optional[Dict[str, Any]]) -> bool:
    """True only for a fresh, persisted ELIGIBLE decision (fail closed)."""
    if not record:
        return False
    return (
        str(record.get("admission_state") or "").upper() == ELIGIBLE
        and str(record.get("admission_policy_version") or "") == ADMISSION_POLICY_VERSION
    )


def context_admission_fields(record: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Provenance fields persisted on the queue row (category_context)."""
    rec = record or {}
    return {
        "admission_state": rec.get("admission_state") or HOLD,
        "admission_reason": rec.get("admission_reason")
        or (REASON_AUTHORITY_MISSING if not record else REASON_POLICY_UNDECIDED),
        "admission_policy_version": rec.get("admission_policy_version")
        or ADMISSION_POLICY_VERSION,
        "admission_evaluated_at": rec.get("admission_evaluated_at"),
        "procurement_scope_type": rec.get("procurement_scope_type"),
        "source_lifecycle": rec.get("source_lifecycle"),
    }


_AUTH_SELECT = """
    SELECT procurement_id, source_lifecycle, procurement_scope_type,
           scope_confidence, scope_method, scope_version,
           admission_state, admission_reason, admission_policy_version,
           admission_evaluated_at
      FROM crm_procurement_scope_authority
     WHERE procurement_id = ANY(%s)
"""


def load_authority_map(cur, procurement_ids: Sequence[int]) -> Dict[int, Dict[str, Any]]:
    """Load persisted admission rows for the given ids using an open cursor."""
    ids = [int(i) for i in procurement_ids if i is not None]
    if not ids:
        return {}
    out: Dict[int, Dict[str, Any]] = {}
    chunk = 5000
    for i in range(0, len(ids), chunk):
        cur.execute(_AUTH_SELECT, (ids[i : i + chunk],))
        for row in cur.fetchall() or []:
            rec = dict(row)
            out[int(rec["procurement_id"])] = rec
    return out


def load_authority_one(conn, procurement_id: int) -> Optional[Dict[str, Any]]:
    """Load a single persisted admission row (own cursor, RealDict)."""
    import psycopg2.extras

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_AUTH_SELECT, ([int(procurement_id)],))
        row = cur.fetchone()
        return dict(row) if row else None


def load_authority_map_exec(execute_query, procurement_ids: Sequence[int]) -> Dict[int, Dict[str, Any]]:
    """Load admission rows via an execute_query(sql, params) wrapper."""
    ids = [int(i) for i in procurement_ids if i is not None]
    if not ids:
        return {}
    rows = execute_query(_AUTH_SELECT, (ids,)) or []
    out: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        rec = dict(row)
        out[int(rec["procurement_id"])] = rec
    return out
