"""Staged annotation helpers: object → mode → category → commercial → medal."""
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
from src.services.expert_commercial_entry import (
    COMMERCIAL,
    COMMERCIAL_ENTRY_FIELD,
    NON_COMMERCIAL,
    UNCERTAIN as ENTRY_UNCERTAIN,
    commercial_entry_label,
    commercial_entry_of,
    derive_legacy_verdict,
    legacy_commercial_state,
    model_commercial_entry_hint,
)
from src.services.expert_medal_stage import (
    MEDAL_FIELD,
    MEDAL_VALUES,
    derive_legacy_nce_medal,
    medal_label,
    medal_of,
    model_medal_hint,
)
from src.services.expert_object_taxonomy import (
    OBJECT_SECTOR_FIELD,
    OBJECT_SUBTYPE_FIELD,
    OBJECT_TYPE_FIELD,
    object_sector_of,
    object_subtype_of,
    object_summary_label,
    object_type_label,
    object_type_of,
    model_object_hints,
)
from src.services.expert_procurement_mode import (
    PROCUREMENT_MODE_FIELD,
    model_procurement_mode_hint,
    procurement_mode_label,
    procurement_mode_of,
)
from src.services.source_contour import enrich_dataset_row

ANNOTATION_VERSION_FIELD = "annotation_version"
STAGED_REVIEW_SCOPE = "STAGED_OBJECT_MODE_CATEGORY_COMMERCIAL"
SUBCATEGORY_CODES_FIELD = "expert_subcategory_codes"


def subcategory_codes_of(payload: dict | None) -> list[str]:
    if not payload:
        return []
    raw = payload.get(SUBCATEGORY_CODES_FIELD) or []
    if isinstance(raw, str):
        raw = [raw]
    # Also harvest from opportunities if top-level absent.
    if not raw:
        for opp in payload.get("opportunities") or []:
            if isinstance(opp, dict) and opp.get("subcategory_code"):
                raw.append(str(opp["subcategory_code"]))
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def merge_staged_fields(
    payload: dict,
    *,
    object_sector: str | None,
    object_type: str | None,
    object_subtype: str | None = None,
    procurement_mode: str | None,
    taxonomy_proposals: list[dict] | None = None,
    commercial_entry: str | None = None,
    expert_medal: str | None = None,
    subcategory_codes: list[str] | None = None,
    category_names: dict[str, str] | None = None,
) -> dict:
    """Attach staged fields to a category-gate payload (additive)."""
    out = dict(payload)
    if object_sector:
        out[OBJECT_SECTOR_FIELD] = object_sector
    if object_type:
        out[OBJECT_TYPE_FIELD] = object_type
    if object_subtype:
        out[OBJECT_SUBTYPE_FIELD] = object_subtype
    if procurement_mode:
        out[PROCUREMENT_MODE_FIELD] = procurement_mode
    if commercial_entry:
        out[COMMERCIAL_ENTRY_FIELD] = commercial_entry
        legacy = derive_legacy_verdict(commercial_entry)
        if legacy:
            out["expert_commercial_verdict"] = legacy
        # Human medal authority is GOLD–WOOD only.
        if commercial_entry == COMMERCIAL and expert_medal in MEDAL_VALUES:
            out[MEDAL_FIELD] = expert_medal
        elif commercial_entry == NON_COMMERCIAL:
            # Do not present NCE as human medal; keep null human medal + legacy NCE compat.
            out.pop(MEDAL_FIELD, None)
            out["_legacy_medal_compat"] = derive_legacy_nce_medal(
                commercial_entry=commercial_entry
            )
        elif commercial_entry == ENTRY_UNCERTAIN:
            out.pop(MEDAL_FIELD, None)
    elif expert_medal in MEDAL_VALUES:
        out[MEDAL_FIELD] = expert_medal

    if subcategory_codes is not None:
        codes = [str(c).strip() for c in subcategory_codes if str(c or "").strip()]
        out[SUBCATEGORY_CODES_FIELD] = codes
        # Sync first matching subcategory onto opportunities by category.
        names = category_names or {}
        for opp in out.get("opportunities") or []:
            if not isinstance(opp, dict):
                continue
            cat = opp.get("category_code")
            # Keep existing subcategory if still in selected list; else clear.
            current = opp.get("subcategory_code")
            if current and current in codes:
                continue
            # Assign codes that look like they belong via session map later.
            opp.setdefault("category_name", names.get(cat))

    if taxonomy_proposals:
        existing = list(out.get("taxonomy_proposals") or [])
        existing.extend(taxonomy_proposals)
        out["taxonomy_proposals"] = existing
    out["annotation_review_scope"] = STAGED_REVIEW_SCOPE
    out["annotation_completeness"] = (
        "COMPLETE" if is_staged_complete(out) else "PARTIAL"
    )
    return out


def apply_subcategory_map(
    payload: dict,
    *,
    subcategory_by_category: dict[str, str | None],
) -> dict:
    """Write per-category subcategory onto opportunities + flatten codes list."""
    out = dict(payload)
    codes: list[str] = []
    opps = []
    for opp in out.get("opportunities") or []:
        if not isinstance(opp, dict):
            continue
        row = dict(opp)
        cat = str(row.get("category_code") or "")
        sub = subcategory_by_category.get(cat)
        row["subcategory_code"] = sub or None
        if sub:
            codes.append(str(sub))
        opps.append(row)
    out["opportunities"] = opps
    out[SUBCATEGORY_CODES_FIELD] = codes
    out["annotation_completeness"] = (
        "COMPLETE" if is_staged_complete(out) else "PARTIAL"
    )
    return out


def has_object_classification(payload: dict | None) -> bool:
    if not payload:
        return False
    return bool(object_sector_of(payload) and object_type_of(payload))


def is_staged_complete(payload: dict | None) -> bool:
    """Full completeness for this WIP.

    OUT_OF_CATEGORY: object + mode + scope
    UNCERTAIN scope: object + mode + scope (may stay partial if incomplete object)
    IN_CATEGORY + COMMERCIAL: + category + commercial_entry + medal
    IN_CATEGORY + NON_COMMERCIAL: + category + commercial_entry (no medal)
    IN_CATEGORY + UNCERTAIN entry: + category + commercial_entry (no medal)
    """
    if not payload:
        return False
    scope = category_scope_of(payload)
    if not scope:
        return False
    if not has_object_classification(payload):
        return False
    if not procurement_mode_of(payload):
        return False
    if scope == OUT_OF_CATEGORY:
        return True
    if scope == UNCERTAIN:
        return True
    if scope != IN_CATEGORY:
        return False
    if not category_codes_of(payload):
        return False
    entry = commercial_entry_of(payload)
    if not entry:
        return False
    if entry == COMMERCIAL:
        return bool(medal_of(payload))
    # NON_COMMERCIAL / UNCERTAIN entry — medal not required
    return True


def is_partially_reviewed(payload: dict | None) -> bool:
    if not payload or is_staged_complete(payload):
        return False
    return bool(
        category_scope_of(payload)
        or has_object_classification(payload)
        or procurement_mode_of(payload)
        or commercial_entry_of(payload)
        or medal_of(payload)
    )


def category_display_labels(
    payload: dict | None,
    *,
    name_by_code: dict[str, str] | None = None,
) -> list[str]:
    names = name_by_code or {}
    labels = []
    for code in category_codes_of(payload):
        labels.append(names.get(code) or code)
    return labels


def staged_card_summary(
    payload: dict | None,
    *,
    name_by_code: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Compact structured result for primary card after save."""
    if not payload:
        return {"status": "UNREVIEWED", "lines": []}
    if not is_partially_reviewed(payload) and not is_staged_complete(payload):
        return {"status": "UNREVIEWED", "lines": []}
    lines: list[tuple[str, str]] = []
    obj = object_summary_label(payload)
    if obj:
        lines.append(("🏢", obj))
    mode = procurement_mode_label(procurement_mode_of(payload))
    if mode:
        lines.append(("🛠", mode))
    scope = category_scope_of(payload)
    if scope == OUT_OF_CATEGORY:
        lines.append(("⛔", "Вне товарных категорий"))
    elif scope == UNCERTAIN:
        lines.append(("?", "Товарная принадлежность: не уверен"))
    elif scope == IN_CATEGORY:
        cats = category_display_labels(payload, name_by_code=name_by_code)
        if cats:
            lines.append(("📦", ", ".join(cats)))
        entry = commercial_entry_of(payload)
        if entry == COMMERCIAL:
            lines.append(("✓", "Коммерчески подходит"))
            med = medal_label(medal_of(payload))
            if med:
                lines.append(("🥇" if medal_of(payload) == "GOLD" else "🏅", med))
        elif entry == NON_COMMERCIAL:
            lines.append(("⛔", "Коммерчески не подходит"))
        elif entry == ENTRY_UNCERTAIN:
            lines.append(("?", "Коммерческая оценка: не уверен"))
        elif legacy_commercial_state(payload):
            lines.append(("⚠", "Legacy коммерческое состояние — нужна доразметка"))
    status = "REVIEWED" if is_staged_complete(payload) else "PARTIAL"
    return {"status": status, "lines": lines}


def compare_human_vs_model_staged(
    *,
    payload: dict | None,
    assessment: dict | None,
) -> dict[str, Any]:
    """Read-only multi-target comparison; PARTIAL where model lacks clean field."""
    human_obj = object_type_of(payload)
    model_hints = model_object_hints(assessment)
    model_obj = model_hints.get("object_type")
    human_mode = procurement_mode_of(payload)
    model_mode = model_procurement_mode_hint(assessment)
    human_scope = category_scope_of(payload)
    from src.services.annotation_category_gate import derive_model_stage1_scope

    model_scope, model_codes = derive_model_stage1_scope(assessment)
    human_codes = category_codes_of(payload)
    human_entry = commercial_entry_of(payload)
    model_entry = model_commercial_entry_hint(assessment)
    human_medal = medal_of(payload)
    model_medal = model_medal_hint(assessment)

    def _match(a, b):
        if a is None or b is None:
            return None
        return a == b

    return {
        "human_object": human_obj,
        "model_object": model_obj,
        "object_match": _match(human_obj, model_obj),
        "human_procurement_mode": human_mode,
        "model_procurement_mode": model_mode,
        "mode_match": _match(human_mode, model_mode),
        "human_category_scope": human_scope,
        "model_category_scope": model_scope,
        "category_scope_match": _match(human_scope, model_scope),
        "human_category_codes": human_codes,
        "model_category_codes": model_codes,
        "category_match": (
            None
            if human_scope is None or model_scope is None
            else set(human_codes) == set(model_codes)
        ),
        "human_commercial_entry": human_entry,
        "model_commercial_entry": model_entry,
        "commercial_match": _match(human_entry, model_entry),
        "human_medal": human_medal,
        "model_medal": model_medal,
        "medal_match": _match(human_medal, model_medal),
        "MODEL_OBJECT_COMPARISON": "PARTIAL",
        "MODEL_MODE_COMPARISON": "PARTIAL",
        "MODEL_CATEGORY_COMPARISON": "PARTIAL",
        "MODEL_COMMERCIAL_COMPARISON": "PARTIAL",
        "MODEL_MEDAL_COMPARISON": "PARTIAL",
        "comparison_mode": "PARTIAL",
    }


def first_stage_dataset_rows_staged(crm_db: Any, *, limit: int = 200) -> list[dict]:
    """Extended staged dataset including commercial/medal/subcategory fields."""
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
        comparison = compare_human_vs_model_staged(payload=payload, assessment=None)
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
            SUBCATEGORY_CODES_FIELD: subcategory_codes_of(payload),
            COMMERCIAL_ENTRY_FIELD: commercial_entry_of(payload),
            MEDAL_FIELD: medal_of(payload),
            "legacy_commercial_state": legacy_commercial_state(payload),
            "annotation_created_at": row.get("created_at"),
            "annotation_version": row.get("annotation_version"),
            "staged_complete": is_staged_complete(payload),
            "object_match": comparison.get("object_match"),
            "mode_match": comparison.get("mode_match"),
            "category_scope_match": comparison.get("category_scope_match"),
            "category_match": comparison.get("category_match"),
            "commercial_match": comparison.get("commercial_match"),
            "medal_match": comparison.get("medal_match"),
        }
        out.append(enrich_dataset_row(base, row.get("source_table")))
    return out
