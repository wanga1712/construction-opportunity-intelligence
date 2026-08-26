"""First-stage expert product-category gate (title + OKPD only).

Authority field in crm_v3_expert_annotations.payload JSONB:

  expert_category_scope ∈ {IN_CATEGORY, OUT_OF_CATEGORY, UNCERTAIN}
  expert_category_codes : list[str]  (canonical crm_product_categories codes)

Legacy OUT_OF_PROFILE / NCE / NOT_INTERESTING remain historical and are NOT
the semantic authority for stage-1 NO.
"""
from __future__ import annotations

from typing import Any

CATEGORY_SCOPE_FIELD = "expert_category_scope"
CATEGORY_CODES_FIELD = "expert_category_codes"

IN_CATEGORY = "IN_CATEGORY"
OUT_OF_CATEGORY = "OUT_OF_CATEGORY"
UNCERTAIN = "UNCERTAIN"
CATEGORY_SCOPE_VALUES = (IN_CATEGORY, OUT_OF_CATEGORY, UNCERTAIN)

FIRST_GATE_QUESTION = "Относится ли закупка к нашим товарным категориям?"
OUT_OF_CATEGORY_BADGE = "⛔ Вне товарных категорий"
LEGACY_NEGATIVE_BADGE = "Старая «Неинтересная»"

# Filter / counter keys (UI)
LEGACY_NOT_INTERESTING = "LEGACY_NOT_INTERESTING"


def category_scope_of(payload: dict | None) -> str | None:
    if not payload:
        return None
    value = payload.get(CATEGORY_SCOPE_FIELD)
    return value if value in CATEGORY_SCOPE_VALUES else None


def category_codes_of(payload: dict | None) -> list[str]:
    if not payload:
        return []
    raw = payload.get(CATEGORY_CODES_FIELD) or []
    if isinstance(raw, str):
        raw = [raw]
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def is_legacy_negative_payload(payload: dict | None) -> bool:
    """Old broad 'Неинтересная' / OUT_OF_PROFILE without category-scope authority."""
    if not payload or category_scope_of(payload):
        return False
    reasons = payload.get("error_reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    return (
        payload.get("expert_commercial_verdict") == "NO_COMMERCIAL_ENTRY"
        or payload.get("expert_scope_verdict") == "OUT_OF_PROFILE"
        or payload.get("expert_medal") == "NCE"
        or "OUT_OF_PROFILE" in reasons
    )


def build_out_of_category_payload(
    *,
    assessment: dict | None,
    created_by: str,
    comment: str = "",
) -> dict:
    """Stage-1 NO: OUT_OF_PRODUCT_CATEGORY only — no NCE/OUT_OF_PROFILE authority."""
    return {
        "model_assessment_id": (assessment or {}).get("id"),
        CATEGORY_SCOPE_FIELD: OUT_OF_CATEGORY,
        CATEGORY_CODES_FIELD: [],
        "annotation_review_scope": "CATEGORY_GATE",
        "annotation_completeness": "COMPLETE",
        "evidence_state": "SUFFICIENT",
        "expert_comment": comment or "",
        "opportunities": [],
        "rejected_model_opportunities": [],
        "taxonomy_proposals": [],
        "training_evidence_quality": (
            "IMMUTABLE_MODEL_TRACE"
            if assessment and assessment.get("inference_run_id")
            else "LEGACY_NO_RAW"
        ),
        "created_by": created_by,
    }


def build_in_category_payload(
    *,
    assessment: dict | None,
    created_by: str,
    category_codes: list[str],
    category_names: dict[str, str] | None = None,
) -> dict:
    codes = [str(c).strip() for c in category_codes if str(c or "").strip()]
    names = category_names or {}
    opportunities = []
    for idx, code in enumerate(codes, start=1):
        opportunities.append(
            {
                "expert_action": "ADD",
                "category_code": code,
                "category_name": names.get(code),
                "opportunity_track": "EMBEDDED_MATERIAL",
                "expert_rank": idx,
                "expert_reviewed": True,
                "comment": "",
            }
        )
    return {
        "model_assessment_id": (assessment or {}).get("id"),
        CATEGORY_SCOPE_FIELD: IN_CATEGORY,
        CATEGORY_CODES_FIELD: codes,
        "annotation_review_scope": "CATEGORY_GATE",
        "annotation_completeness": "PARTIAL",
        "evidence_state": "SUFFICIENT",
        "expert_comment": "",
        "opportunities": opportunities,
        "rejected_model_opportunities": [],
        "taxonomy_proposals": [],
        "training_evidence_quality": (
            "IMMUTABLE_MODEL_TRACE"
            if assessment and assessment.get("inference_run_id")
            else "LEGACY_NO_RAW"
        ),
        "created_by": created_by,
    }


def build_uncertain_payload(
    *,
    assessment: dict | None,
    created_by: str,
    comment: str = "",
) -> dict:
    return {
        "model_assessment_id": (assessment or {}).get("id"),
        CATEGORY_SCOPE_FIELD: UNCERTAIN,
        CATEGORY_CODES_FIELD: [],
        "annotation_review_scope": "CATEGORY_GATE",
        "annotation_completeness": "PARTIAL",
        "evidence_state": "INSUFFICIENT",
        "expert_comment": comment or "",
        "opportunities": [],
        "rejected_model_opportunities": [],
        "taxonomy_proposals": [],
        "training_evidence_quality": (
            "IMMUTABLE_MODEL_TRACE"
            if assessment and assessment.get("inference_run_id")
            else "LEGACY_NO_RAW"
        ),
        "created_by": created_by,
    }


def derive_model_stage1_scope(assessment: dict | None) -> tuple[str | None, list[str]]:
    """Best-effort read-only mapping from current V3 model — may be PARTIAL."""
    if not assessment:
        return None, []
    nr = assessment.get("normalized_result") or {}
    codes: list[str] = []
    for opp in nr.get("category_opportunities") or []:
        if isinstance(opp, dict) and opp.get("category_code"):
            codes.append(str(opp["category_code"]))
    for hyp in nr.get("commercial_category_hypotheses") or []:
        if isinstance(hyp, dict):
            code = hyp.get("category_code") or hyp.get("commercial_category_code")
            if code:
                codes.append(str(code))
    # de-dupe
    seen: list[str] = []
    for code in codes:
        if code not in seen:
            seen.append(code)
    scope_status = nr.get("business_scope_status")
    if seen:
        return IN_CATEGORY, seen
    if scope_status == "OUT_OF_PROFILE":
        return OUT_OF_CATEGORY, []
    return None, []


def compare_human_vs_model(
    *,
    human_scope: str | None,
    human_codes: list[str],
    assessment: dict | None,
) -> dict[str, Any]:
    model_scope, model_codes = derive_model_stage1_scope(assessment)
    if human_scope is None:
        agreement = None
        disagreement = "HUMAN_MISSING"
    elif model_scope is None:
        agreement = None
        disagreement = "MODEL_SCOPE_UNAVAILABLE"
    elif human_scope == model_scope:
        agreement = True
        disagreement = None
        if human_scope == IN_CATEGORY and set(human_codes) != set(model_codes):
            agreement = False
            disagreement = "CATEGORY_CODES_MISMATCH"
    else:
        agreement = False
        disagreement = f"{human_scope}_vs_{model_scope}"
    return {
        "human_category_scope": human_scope,
        "human_category_codes": human_codes,
        "model_category_scope": model_scope,
        "model_category_codes": model_codes,
        "agreement": agreement,
        "disagreement_type": disagreement,
        "comparison_mode": "PARTIAL",
    }


def first_stage_dataset_rows(crm_db: Any, *, limit: int = 200) -> list[dict]:
    """Read-only first-stage reviewed rows for export/view."""
    rows = crm_db.execute_query(
        f"""
        SELECT a.procurement_id, a.annotation_version, a.created_at, a.payload,
               p.contract_number, p.source_table, p.auction_name,
               p.okpd_code, p.okpd_name
        FROM crm_v3_expert_annotations a
        JOIN crm_procurements p ON p.id = a.procurement_id
        WHERE a.is_current = TRUE
          AND COALESCE(a.payload->>'{CATEGORY_SCOPE_FIELD}', '') <> ''
        ORDER BY a.created_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    out = []
    for row in rows or []:
        payload = row.get("payload") or {}
        law = "223" if "223" in str(row.get("source_table") or "") else (
            "44" if "44" in str(row.get("source_table") or "") else "OTHER"
        )
        out.append(
            {
                "procurement_id": row["procurement_id"],
                "procurement_number": row.get("contract_number"),
                "law": law,
                "title": row.get("auction_name"),
                "okpd_code": row.get("okpd_code"),
                "okpd_name": row.get("okpd_name"),
                "expert_category_scope": category_scope_of(payload),
                "expert_category_codes": category_codes_of(payload),
                "annotation_created_at": row.get("created_at"),
                "annotation_version": row.get("annotation_version"),
            }
        )
    return out
