"""Foundation primitives for document-confirmed opportunity lineage.

DOCUMENT-CONFIRMED-OPPORTUNITY-FOUNDATION-1. Pure, side-effect free helpers
(plus one narrow persistence helper) that establish the *contract*:

    candidate_initial  -> (trusted document facts) -> confirmed_base -> current_effective

Scope guard: this module does NOT run extraction, does NOT call Qwen, does NOT
change scoring weights/thresholds, and does NOT mutate candidate_initial.

The UI read-model and the runtime wiring into medal_lineage are deliberately
NOT done here (see WIP report) so that production behaviour is unchanged.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple

# procurement forms where contract total MUST NOT become category value
WORKS_FORMS = frozenset({
    "CONSTRUCTION_WORKS",
    "DESIGN_AND_BUILD",
    "DESIGN_EXPERTISE_AND_BUILD",
    "DESIGN_ONLY",
    "SURVEY_AND_DESIGN",
})

DIRECT_FORM = "DIRECT_GOODS"

BASIS_DOC_EXPLICIT_TOTAL = "DOCUMENT_EXPLICIT_TOTAL"
BASIS_DOC_ENTITY_SUM = "DOCUMENT_ENTITY_TOTAL_SUM"
BASIS_DOC_QTY_X_UNIT = "DOCUMENT_QTY_X_UNIT_PRICE"
BASIS_DIRECT_SINGLE = "DIRECT_SINGLE_CATEGORY_PROCUREMENT_VALUE"
BASIS_UNKNOWN = "UNKNOWN_ADDRESSABLE_VALUE"

ALLOWED_BASIS = frozenset({
    BASIS_DOC_EXPLICIT_TOTAL, BASIS_DOC_ENTITY_SUM, BASIS_DOC_QTY_X_UNIT,
    BASIS_DIRECT_SINGLE, BASIS_UNKNOWN,
})

STATE_CANDIDATE = "CANDIDATE"
STATE_CONFIRMED = "CONFIRMED"
STATE_REJECTED = "REJECTED"
STATE_INSUFFICIENT = "INSUFFICIENT"

SUBCAT_MODEL_CANDIDATE = "MODEL_CANDIDATE"
SUBCAT_CONFIRMED = "CONFIRMED"
SUBCAT_UNCONFIRMED = "UNCONFIRMED"

AUTH_PRELIMINARY = "PRELIMINARY"
AUTH_CONFIRMED = "CONFIRMED"


def is_works_form(procurement_form: Optional[str]) -> bool:
    return str(procurement_form or "").strip().upper() in WORKS_FORMS


def works_value_gate(procurement_form: Optional[str], basis: Optional[str]) -> bool:
    """True when (form, basis) is legally allowed to set category value.

    Hard invariant: WORKS_CATEGORY_VALUE_FROM_CONTRACT_TOTAL = 0. A works/object
    procurement may never use the contract total as the category value.
    """
    basis = str(basis or BASIS_UNKNOWN).strip().upper()
    if basis not in ALLOWED_BASIS:
        return False
    if is_works_form(procurement_form):
        return basis in (BASIS_DOC_EXPLICIT_TOTAL, BASIS_DOC_ENTITY_SUM, BASIS_DOC_QTY_X_UNIT)
    if basis == BASIS_DIRECT_SINGLE:
        return str(procurement_form or "").strip().upper() == DIRECT_FORM
    return True


def category_state(
    *,
    procurement_form: Optional[str],
    has_trusted_evidence: bool,
    confirmed_base_medal: Optional[str],
    has_safe_negative: bool = False,
    documents_terminal: bool = False,
) -> str:
    if has_safe_negative and documents_terminal:
        return STATE_REJECTED
    if has_trusted_evidence or confirmed_base_medal:
        return STATE_CONFIRMED
    if documents_terminal:
        return STATE_INSUFFICIENT
    return STATE_CANDIDATE


def subcategory_state(
    *,
    procurement_form: Optional[str],
    has_subcategory_evidence: bool,
    confirmed: bool = False,
) -> str:
    """Model/context subcategory is only ever MODEL_CANDIDATE when unproven."""
    if confirmed and has_subcategory_evidence:
        return SUBCAT_CONFIRMED
    if has_subcategory_evidence:
        return SUBCAT_CONFIRMED
    return SUBCAT_MODEL_CANDIDATE


def current_effective_authority(confirmed_base_medal: Optional[str]) -> str:
    """Never present current_effective as document-confirmed without confirmed_base."""
    return AUTH_CONFIRMED if confirmed_base_medal else AUTH_PRELIMINARY


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    # "6.200.000,00" european -> handle by keeping last separator as decimal
    if text.count(".") > 1:
        head, _, tail = text.rpartition(".")
        text = head.replace(".", "") + "." + tail
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def derive_category_value_from_entities(entities: Iterable[Dict[str, Any]]) -> Tuple[Optional[Decimal], str]:
    """Deterministic category value from trusted structured entities.

    Dedup by structured_entity_id so one factual position is never counted
    twice (VALUE_DOUBLE_COUNT=0). Financial math is Decimal-only.
    """
    seen = set()
    totals: List[Decimal] = []
    qty_unit_sum = Decimal("0")
    have_qty_unit = False

    for e in entities or []:
        if not isinstance(e, dict):
            continue
        eid = e.get("structured_entity_id") or e.get("id")
        if eid is None or eid in seen:
            continue
        seen.add(eid)
        total = _to_decimal(e.get("total_price_value") or e.get("total_price_raw"))
        qty = _to_decimal(e.get("quantity_value") or e.get("quantity_raw"))
        unit = _to_decimal(e.get("unit_price_value") or e.get("unit_price_raw"))
        if total is not None:
            totals.append(total)
        elif qty is not None and unit is not None and e.get("subject_bound"):
            qty_unit_sum += qty * unit
            have_qty_unit = True

    if len(totals) == 1:
        return totals[0], BASIS_DOC_EXPLICIT_TOTAL
    if len(totals) > 1:
        return sum(totals, Decimal("0")), BASIS_DOC_ENTITY_SUM
    if have_qty_unit:
        return qty_unit_sum, BASIS_DOC_QTY_X_UNIT
    return None, BASIS_UNKNOWN


def evidence_fingerprint(
    *,
    procurement_id: int,
    category_code: str,
    subcategory_code: Optional[str],
    entity_ids: Iterable[Any],
    values: Iterable[Any],
    extractor_version: Optional[str] = None,
) -> str:
    """Deterministic fingerprint of the trusted factual authority."""
    payload = {
        "pid": int(procurement_id),
        "cat": category_code,
        "sub": subcategory_code,
        "entities": sorted(str(x) for x in (entity_ids or [])),
        "values": sorted(str(x) for x in (values or [])),
        "extractor": extractor_version,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def should_apply_evidence(previous_fingerprint: Optional[str], new_fingerprint: str) -> bool:
    """Idempotence gate: same evidence snapshot must produce no re-write."""
    return bool(new_fingerprint) and new_fingerprint != (previous_fingerprint or "")


def commercial_scale_authority(
    *,
    procurement_form: Optional[str],
    opportunity_track: Optional[str],
    basis: Optional[str],
    category_value: Optional[Decimal],
) -> Tuple[Optional[Decimal], str]:
    """Return (scale_value, source) for the scorer without touching weights.

    WORKS/OBJECT: only a confirmed document category value may drive scale;
    the procurement contract total never does.
    """
    basis = str(basis or BASIS_UNKNOWN).strip().upper()
    if category_value is not None and works_value_gate(procurement_form, basis):
        return category_value, "CONFIRMED_CATEGORY_DOCUMENT_VALUE"
    return None, "NOT_AVAILABLE"


def confirmed_base_can_revise(previous_fingerprint: Optional[str], new_fingerprint: str) -> bool:
    return should_apply_evidence(previous_fingerprint, new_fingerprint)
