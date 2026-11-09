"""BUSINESS_RESEARCH_ADMISSION_V2 - canonical business research admission.

The admission matrix is deliberately isolated from research priors, commercial
medals, document confirmation, and queue claim policy.  Runtime consumers read
the persisted decision; only materialisation calls ``decide_admission``.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

ADMISSION_POLICY_VERSION = "BUSINESS_RESEARCH_ADMISSION_V2"

ELIGIBLE = "ELIGIBLE"
EXCLUDED = "EXCLUDED"
HOLD = "HOLD"

REASON_CURRENT = "CURRENT_BUSINESS_ADMISSION"
REASON_AWARDED_DIRECT = "AWARDED_DIRECT_GOODS"
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

_WAITING_LIFECYCLES = frozenset({LC_WAITING, "WAITING_AWARD", "WAITING"})
_RECOGNIZED_WAITING_SCOPES = frozenset(
    {SCOPE_DIRECT_GOODS, SCOPE_WORKS_EMBEDDED, SCOPE_DESIGN}
)
_ELIGIBLE_MATRIX = {
    (LC_OPEN, SCOPE_DIRECT_GOODS),
    (LC_OPEN, SCOPE_WORKS_EMBEDDED),
    (LC_OPEN, SCOPE_DESIGN),
    (LC_AWARDED, SCOPE_WORKS_EMBEDDED),
    (LC_AWARDED, SCOPE_DESIGN),
}


def decide_admission(source_lifecycle: Any, scope_type: Any) -> Tuple[str, str]:
    """Return ``(admission_state, reason_code)`` using fail-closed semantics."""
    lc = str(source_lifecycle or "").strip().upper()
    scope = str(scope_type or "").strip().upper()

    if lc == LC_AWARDED and scope == SCOPE_DIRECT_GOODS:
        return EXCLUDED, REASON_AWARDED_DIRECT
    if lc in _WAITING_LIFECYCLES and scope in _RECOGNIZED_WAITING_SCOPES:
        return ELIGIBLE, REASON_CURRENT
    if (lc, scope) in _ELIGIBLE_MATRIX:
        return ELIGIBLE, REASON_CURRENT
    if scope in ("", SCOPE_UNKNOWN):
        return HOLD, REASON_UNKNOWN_SCOPE
    return HOLD, REASON_POLICY_UNDECIDED


def admission_contract(source_lifecycle: Any, scope_type: Any) -> Dict[str, str]:
    """Materialisation-facing contract with explicit state/reason/version."""
    state, reason_code = decide_admission(source_lifecycle, scope_type)
    return {
        "admission_state": state,
        "reason_code": reason_code,
        "admission_reason": reason_code,
        "admission_policy_version": ADMISSION_POLICY_VERSION,
    }


def is_queue_eligible(record: Optional[Dict[str, Any]]) -> bool:
    """True only for a fresh persisted ELIGIBLE decision."""
    if not record:
        return False
    return (
        str(record.get("admission_state") or "").upper() == ELIGIBLE
        and str(record.get("admission_policy_version") or "")
        == ADMISSION_POLICY_VERSION
    )


def _json_safe(value: Any) -> Any:
    """Coerce DB values (datetime/date/Decimal) into JSON-native values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


def context_admission_fields(record: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Admission-only provenance fields persisted in queue ``category_context``."""
    rec = record or {}
    fields = {
        "admission_state": rec.get("admission_state") or HOLD,
        "admission_reason": rec.get("admission_reason")
        or (REASON_AUTHORITY_MISSING if not record else REASON_POLICY_UNDECIDED),
        "admission_policy_version": rec.get("admission_policy_version")
        or ADMISSION_POLICY_VERSION,
        "admission_evaluated_at": rec.get("admission_evaluated_at"),
        "procurement_scope_type": rec.get("procurement_scope_type"),
        "source_lifecycle": rec.get("source_lifecycle"),
    }
    return {key: _json_safe(value) for key, value in fields.items()}


_AUTH_SELECT = """
    SELECT procurement_id, source_lifecycle, procurement_scope_type,
           scope_confidence, scope_method, scope_version,
           admission_state, admission_reason, admission_policy_version,
           admission_evaluated_at
      FROM crm_procurement_scope_authority
     WHERE procurement_id = ANY(%s)
"""


def load_authority_map(
    cur, procurement_ids: Sequence[int]
) -> Dict[int, Dict[str, Any]]:
    """Load persisted admission rows for ``procurement_ids``."""
    ids = [int(i) for i in procurement_ids if i is not None]
    if not ids:
        return {}
    out: Dict[int, Dict[str, Any]] = {}
    chunk = 5000
    for start in range(0, len(ids), chunk):
        cur.execute(_AUTH_SELECT, (ids[start : start + chunk],))
        for row in cur.fetchall() or []:
            rec = dict(row)
            out[int(rec["procurement_id"])] = rec
    return out


def load_authority_one(conn, procurement_id: int) -> Optional[Dict[str, Any]]:
    """Load one persisted admission row using its own cursor."""
    import psycopg2.extras

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_AUTH_SELECT, ([int(procurement_id)],))
        row = cur.fetchone()
        return dict(row) if row else None


def load_authority_map_exec(
    execute_query, procurement_ids: Sequence[int]
) -> Dict[int, Dict[str, Any]]:
    """Load admission rows through an ``execute_query(sql, params)`` wrapper."""
    ids = [int(i) for i in procurement_ids if i is not None]
    if not ids:
        return {}
    rows = execute_query(_AUTH_SELECT, (ids,)) or []
    out: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        rec = dict(row)
        out[int(rec["procurement_id"])] = rec
    return out
