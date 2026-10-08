"""Category-specific human dispute capture (versioned, capture-only).

Reuses the existing versioned writer ``save_expert_annotation`` and the existing
``crm_v3_expert_annotations`` storage. No new tables / DDL.

SEMANTICS (HUMAN-CATEGORY-DISPUTE-CAPTURE-1):
  * The signal is CATEGORY-SPECIFIC: one ``procurement × category × subcategory``
    link is disputed while every other category stays untouched.
  * It is NOT a global ``OUT_OF_CATEGORY`` verdict and MUST NOT write
    ``expert_category_scope``.
  * No pipeline activation: no queue job, no documents, no Qwen, no medal /
    admission / taxonomy change.

Storage contract: an entry appended to ``payload.rejected_model_opportunities``
with ``expert_action = REQUEST_RECHECK`` and ``verification_state``.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Dict, Optional

REQUEST_RECHECK = "REQUEST_RECHECK"

REASON_CODES = (
    "WRONG_PRODUCT_TYPE",
    "ACCESSORY_NOT_MAIN_PRODUCT",
    "SOFTWARE_NOT_HARDWARE",
    "WRONG_SUBCATEGORY",
    "TITLE_MISLEADING",
    "OTHER",
)

STATE_NONE = "NONE"
STATE_PENDING_RECHECK = "PENDING_RECHECK"
STATE_CANCELLED = "CANCELLED"
STATE_VERIFIED_REJECTED = "VERIFIED_REJECTED"
STATE_VERIFIED_CONFIRMED = "VERIFIED_CONFIRMED"
STATE_CANCELLED_BY_USER = "CANCELLED_BY_USER"

_STATE_MAP = {
    STATE_PENDING_RECHECK: STATE_PENDING_RECHECK,
    STATE_CANCELLED_BY_USER: STATE_CANCELLED,
    STATE_VERIFIED_REJECTED: STATE_VERIFIED_REJECTED,
    STATE_VERIFIED_CONFIRMED: STATE_VERIFIED_CONFIRMED,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(category_code: Any, subcategory_code: Any) -> tuple:
    return (
        str(category_code or "").strip(),
        (str(subcategory_code).strip() if subcategory_code else None),
    )


def build_dispute_entry(
    *,
    category_code: str,
    category_name: Optional[str] = None,
    subcategory_code: Optional[str] = None,
    subcategory_name: Optional[str] = None,
    reason_code: str,
    comment: str = "",
    created_by: str,
    model_assessment_id: Any = None,
    model_inference_run_id: Any = None,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build one versioned REQUEST_RECHECK entry. Category-specific only."""
    if reason_code not in REASON_CODES:
        raise ValueError(f"reason_code must be one of {REASON_CODES}, got {reason_code!r}")
    return {
        "expert_action": REQUEST_RECHECK,
        "category_code": category_code,
        "category_name": category_name,
        "subcategory_code": subcategory_code,
        "subcategory_name": subcategory_name,
        "reason_code": reason_code,
        "comment": comment or "",
        "verification_state": STATE_PENDING_RECHECK,
        "model_assessment_id": model_assessment_id,
        "model_inference_run_id": model_inference_run_id,
        "created_by": created_by,
        "created_at": created_at or _now_iso(),
    }


def upsert_dispute_entry(
    payload: Dict[str, Any],
    entry: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a copy of *payload* with the dispute entry for its key replaced.

    Never mutates the input. The existing opportunity / medal / taxonomy fields
    are preserved untouched; only ``rejected_model_opportunities`` changes.
    """
    new_payload = copy.deepcopy(payload or {})
    rejected = list(new_payload.get("rejected_model_opportunities") or [])
    key = _key(entry.get("category_code"), entry.get("subcategory_code"))
    # Drop prior REQUEST_RECHECK entries for the same link (latest wins).
    rejected = [
        r for r in rejected
        if not (
            isinstance(r, dict)
            and r.get("expert_action") == REQUEST_RECHECK
            and _key(r.get("category_code"), r.get("subcategory_code")) == key
        )
    ]
    rejected.append(entry)
    new_payload["rejected_model_opportunities"] = rejected
    return new_payload


def cancel_dispute_entry(
    payload: Dict[str, Any],
    *,
    category_code: str,
    subcategory_code: Optional[str],
    created_by: str,
) -> Optional[Dict[str, Any]]:
    """Return payload with the link's dispute marked CANCELLED_BY_USER.

    Returns None when there is no REQUEST_RECHECK entry for the link (no-op).
    History is preserved: a NEW cancellation entry is appended, the original
    pending entry is kept.
    """
    key = _key(category_code, subcategory_code)
    pending = [
        r for r in (payload or {}).get("rejected_model_opportunities") or []
        if isinstance(r, dict)
        and r.get("expert_action") == REQUEST_RECHECK
        and _key(r.get("category_code"), r.get("subcategory_code")) == key
        and r.get("verification_state") == STATE_PENDING_RECHECK
    ]
    if not pending:
        return None
    last = pending[-1]
    entry = dict(last)
    entry["verification_state"] = STATE_CANCELLED_BY_USER
    entry["created_by"] = created_by
    entry["created_at"] = _now_iso()
    return append_dispute_entry(payload, entry)


def append_dispute_entry(
    payload: Dict[str, Any],
    entry: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a copy of *payload* with *entry* appended (history preserved).

    Unlike :func:`upsert_dispute_entry`, prior entries for the same link are
    kept — used for cancellation / verification lifecycle transitions.
    """
    new_payload = copy.deepcopy(payload or {})
    rejected = list(new_payload.get("rejected_model_opportunities") or [])
    rejected.append(entry)
    new_payload["rejected_model_opportunities"] = rejected
    return new_payload


def dispute_state_from_payload(
    payload: Optional[Dict[str, Any]],
    *,
    category_code: str,
    subcategory_code: Optional[str],
) -> str:
    """Read-model state for one procurement×category(×subcategory) link."""
    key = _key(category_code, subcategory_code)
    matches = [
        r for r in (payload or {}).get("rejected_model_opportunities") or []
        if isinstance(r, dict)
        and r.get("expert_action") == REQUEST_RECHECK
        and _key(r.get("category_code"), r.get("subcategory_code")) == key
    ]
    if not matches:
        return STATE_NONE
    return _STATE_MAP.get(str((matches[-1] or {}).get("verification_state") or ""), STATE_NONE)


def is_pending(payload: Optional[Dict[str, Any]], *, category_code: str, subcategory_code: Optional[str]) -> bool:
    return dispute_state_from_payload(
        payload, category_code=category_code, subcategory_code=subcategory_code
    ) == STATE_PENDING_RECHECK


def _pending_unchanged(
    payload: Optional[Dict[str, Any]],
    *,
    category_code: str,
    subcategory_code: Optional[str],
    reason_code: str,
    comment: str,
) -> bool:
    key = _key(category_code, subcategory_code)
    matches = [
        r for r in (payload or {}).get("rejected_model_opportunities") or []
        if isinstance(r, dict)
        and r.get("expert_action") == REQUEST_RECHECK
        and _key(r.get("category_code"), r.get("subcategory_code")) == key
    ]
    if not matches:
        return False
    last = matches[-1]
    return (
        last.get("verification_state") == STATE_PENDING_RECHECK
        and last.get("reason_code") == reason_code
        and (last.get("comment") or "") == (comment or "")
    )


# ─────────────────────────────────────────────────────────────────────────────
# DB-bound API (thin wrappers; capture-only)
# ─────────────────────────────────────────────────────────────────────────────

def get_category_dispute_state(
    procurement_id: int,
    category_code: str,
    subcategory_code: Optional[str],
    crm_db: Any,
) -> str:
    from src.services.expert_annotation_service import load_expert_annotation

    ann = load_expert_annotation(procurement_id, crm_db)
    payload = (ann or {}).get("payload") if isinstance(ann, dict) else None
    return dispute_state_from_payload(
        payload, category_code=category_code, subcategory_code=subcategory_code
    )


def capture_category_dispute(
    *,
    procurement_id: int,
    category_code: str,
    subcategory_code: Optional[str],
    reason_code: str,
    comment: str,
    created_by: str,
    crm_db: Any,
    category_name: Optional[str] = None,
    subcategory_name: Optional[str] = None,
    assessment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist a category-specific dispute as a NEW annotation version.

    Returns {"saved": bool, "state": str, "annotation_id": int|None}.
    No-op (saved=False) when an identical pending dispute already exists.
    """
    from src.services.expert_annotation_service import (
        load_expert_annotation,
        save_expert_annotation,
    )

    ann = load_expert_annotation(procurement_id, crm_db)
    payload = dict((ann or {}).get("payload") or {})
    if _pending_unchanged(
        payload,
        category_code=category_code,
        subcategory_code=subcategory_code,
        reason_code=reason_code,
        comment=comment,
    ):
        return {"saved": False, "state": STATE_PENDING_RECHECK, "annotation_id": (ann or {}).get("annotation_id")}

    entry = build_dispute_entry(
        category_code=category_code,
        category_name=category_name,
        subcategory_code=subcategory_code,
        subcategory_name=subcategory_name,
        reason_code=reason_code,
        comment=comment,
        created_by=created_by,
        model_assessment_id=(assessment or {}).get("id"),
        model_inference_run_id=(assessment or {}).get("inference_run_id"),
    )
    new_payload = upsert_dispute_entry(payload, entry)
    new_id = save_expert_annotation(procurement_id, new_payload, created_by, crm_db)
    return {"saved": True, "state": STATE_PENDING_RECHECK, "annotation_id": new_id}


def cancel_category_dispute(
    *,
    procurement_id: int,
    category_code: str,
    subcategory_code: Optional[str],
    created_by: str,
    crm_db: Any,
) -> Dict[str, Any]:
    """Append a CANCELLED_BY_USER version for the link (history preserved)."""
    from src.services.expert_annotation_service import (
        load_expert_annotation,
        save_expert_annotation,
    )

    ann = load_expert_annotation(procurement_id, crm_db)
    payload = dict((ann or {}).get("payload") or {})
    new_payload = cancel_dispute_entry(
        payload,
        category_code=category_code,
        subcategory_code=subcategory_code,
        created_by=created_by,
    )
    if new_payload is None:
        return {"saved": False, "state": STATE_NONE, "annotation_id": (ann or {}).get("annotation_id")}
    new_id = save_expert_annotation(procurement_id, new_payload, created_by, crm_db)
    return {"saved": True, "state": STATE_CANCELLED, "annotation_id": new_id}
