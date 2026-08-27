"""Staged annotation helpers: object + procurement mode + category gate merge."""
from __future__ import annotations

from typing import Any

from src.services.annotation_category_gate import (
    CATEGORY_CODES_FIELD,
    CATEGORY_SCOPE_FIELD,
    IN_CATEGORY,
    OUT_OF_CATEGORY,
    UNCERTAIN,
    category_codes_of,
    category_scope_of,
)
from src.services.expert_object_taxonomy import (
    OBJECT_SECTOR_FIELD,
    OBJECT_SUBTYPE_FIELD,
    OBJECT_TYPE_FIELD,
    object_sector_of,
    object_subtype_of,
    object_summary_label,
    object_type_of,
)
from src.services.expert_procurement_mode import (
    PROCUREMENT_MODE_FIELD,
    procurement_mode_label,
    procurement_mode_of,
)
from src.services.source_contour import enrich_dataset_row, resolve_source_contour

ANNOTATION_VERSION_FIELD = "annotation_version"
STAGED_REVIEW_SCOPE = "STAGED_OBJECT_MODE_CATEGORY"


def merge_staged_fields(
    payload: dict,
    *,
    object_sector: str | None,
    object_type: str | None,
    object_subtype: str | None = None,
    procurement_mode: str | None,
    taxonomy_proposals: list[dict] | None = None,
) -> dict:
    """Attach staged object/mode fields to a category-gate payload (additive)."""
    out = dict(payload)
    if object_sector:
        out[OBJECT_SECTOR_FIELD] = object_sector
    if object_type:
        out[OBJECT_TYPE_FIELD] = object_type
    if object_subtype:
        out[OBJECT_SUBTYPE_FIELD] = object_subtype
    if procurement_mode:
        out[PROCUREMENT_MODE_FIELD] = procurement_mode
    if taxonomy_proposals:
        existing = list(out.get("taxonomy_proposals") or [])
        existing.extend(taxonomy_proposals)
        out["taxonomy_proposals"] = existing
    out["annotation_review_scope"] = STAGED_REVIEW_SCOPE
    out["annotation_completeness"] = (
        "COMPLETE" if is_staged_complete(out) else "PARTIAL"
    )
    return out


def has_object_classification(payload: dict | None) -> bool:
    """Object stage minimum: sector + type (subtype optional)."""
    if not payload:
        return False
    return bool(object_sector_of(payload) and object_type_of(payload))


def is_staged_complete(payload: dict | None) -> bool:
    """Fully reviewed for this WIP: object + mode + category gate (+ codes if IN)."""
    if not payload:
        return False
    scope = category_scope_of(payload)
    if not scope:
        return False
    if not has_object_classification(payload):
        return False
    if not procurement_mode_of(payload):
        return False
    if scope == IN_CATEGORY and not category_codes_of(payload):
        return False
    return True


def is_partially_reviewed(payload: dict | None) -> bool:
    """Has some stage-1 authority but not full staged completeness."""
    if not payload or is_staged_complete(payload):
        return False
    return bool(
        category_scope_of(payload)
        or has_object_classification(payload)
        or procurement_mode_of(payload)
    )


def staged_card_summary(payload: dict | None) -> dict[str, Any]:
    """Compact structured result for primary card after save."""
    if not payload:
        return {"status": "UNREVIEWED", "lines": []}
    if not is_partially_reviewed(payload) and not is_staged_complete(payload):
        return {"status": "UNREVIEWED", "lines": []}
    lines: list[tuple[str, str]] = []
    obj = object_summary_label(payload)
    if obj:
        lines.append(("🏢 Объект", obj))
    mode = procurement_mode_label(procurement_mode_of(payload))
    if mode:
        lines.append(("🛠 Формат", mode))
    scope = category_scope_of(payload)
    codes = category_codes_of(payload)
    if scope == OUT_OF_CATEGORY:
        lines.append(("⛔", "Вне товарных категорий"))
    elif scope == UNCERTAIN:
        lines.append(("?", "Категория: не уверен"))
    elif scope == IN_CATEGORY:
        if codes:
            lines.append(("📦 Категория", ", ".join(codes)))
        else:
            lines.append(("📦 Категория", "в товарных категориях"))
    status = "REVIEWED" if is_staged_complete(payload) else "PARTIAL"
    return {"status": status, "lines": lines}


def collect_staged_session_fields(session_get, procurement_id: int, sk) -> dict[str, Any]:
    """Read staged draft values from Streamlit session via _sk helper."""
    return {
        "object_sector": session_get(sk(procurement_id, "obj_sector")) or None,
        "object_type": session_get(sk(procurement_id, "obj_type")) or None,
        "object_subtype": session_get(sk(procurement_id, "obj_subtype")) or None,
        "procurement_mode": session_get(sk(procurement_id, "proc_mode")) or None,
    }


def first_stage_dataset_rows_staged(crm_db: Any, *, limit: int = 200) -> list[dict]:
    """Extended first-stage dataset including object/mode fields."""
    from src.services.annotation_category_gate import CATEGORY_SCOPE_FIELD as CSF

    rows = crm_db.execute_query(
        f"""
        SELECT a.procurement_id, a.annotation_version, a.created_at, a.payload,
               p.contract_number, p.source_table, p.auction_name,
               p.okpd_code, p.okpd_name
        FROM crm_v3_expert_annotations a
        JOIN crm_procurements p ON p.id = a.procurement_id
        WHERE a.is_current = TRUE
          AND (
            COALESCE(a.payload->>'{CSF}', '') <> ''
            OR COALESCE(a.payload->>'{OBJECT_SECTOR_FIELD}', '') <> ''
            OR COALESCE(a.payload->>'{PROCUREMENT_MODE_FIELD}', '') <> ''
          )
        ORDER BY a.created_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    out = []
    for row in rows or []:
        payload = row.get("payload") or {}
        base = {
            "procurement_id": row["procurement_id"],
            "procurement_number": row.get("contract_number"),
            "title": row.get("auction_name"),
            "okpd_code": row.get("okpd_code"),
            "okpd_name": row.get("okpd_name"),
            OBJECT_SECTOR_FIELD: object_sector_of(payload),
            OBJECT_TYPE_FIELD: object_type_of(payload),
            OBJECT_SUBTYPE_FIELD: object_subtype_of(payload),
            PROCUREMENT_MODE_FIELD: procurement_mode_of(payload),
            CATEGORY_SCOPE_FIELD: category_scope_of(payload),
            CATEGORY_CODES_FIELD: category_codes_of(payload),
            "annotation_created_at": row.get("created_at"),
            "annotation_version": row.get("annotation_version"),
            "staged_complete": is_staged_complete(payload),
        }
        out.append(enrich_dataset_row(base, row.get("source_table")))
    return out
