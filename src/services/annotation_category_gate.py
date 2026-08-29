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
    if isinstance(value, dict):
        value = value.get("verdict")
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


def _base_gate_payload(
    *,
    assessment: dict | None,
    created_by: str,
    scope: str,
    category_codes: list[str],
    opportunities: list[dict],
    comment: str,
    evidence_state: str,
    annotation_completeness: str,
) -> dict:
    return {
        "model_assessment_id": (assessment or {}).get("id"),
        CATEGORY_SCOPE_FIELD: scope,
        CATEGORY_CODES_FIELD: category_codes,
        "annotation_review_scope": "CATEGORY_GATE",
        "annotation_completeness": annotation_completeness,
        "evidence_state": evidence_state,
        "expert_comment": comment or "",
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


def build_out_of_category_payload(
    *,
    assessment: dict | None,
    created_by: str,
    comment: str = "",
) -> dict:
    """Stage-1 NO: OUT_OF_PRODUCT_CATEGORY only — no NCE/OUT_OF_PROFILE authority."""
    return _base_gate_payload(
        assessment=assessment,
        created_by=created_by,
        scope=OUT_OF_CATEGORY,
        category_codes=[],
        opportunities=[],
        comment=comment,
        evidence_state="SUFFICIENT",
        annotation_completeness="COMPLETE",
    )


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
    return _base_gate_payload(
        assessment=assessment,
        created_by=created_by,
        scope=IN_CATEGORY,
        category_codes=codes,
        opportunities=opportunities,
        comment="",
        evidence_state="SUFFICIENT",
        annotation_completeness="PARTIAL",
    )


def build_uncertain_payload(
    *,
    assessment: dict | None,
    created_by: str,
    comment: str = "",
) -> dict:
    return _base_gate_payload(
        assessment=assessment,
        created_by=created_by,
        scope=UNCERTAIN,
        category_codes=[],
        opportunities=[],
        comment=comment,
        evidence_state="INSUFFICIENT",
        annotation_completeness="PARTIAL",
    )


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
    """Read-only first-stage rows including staged object/mode fields."""
    from src.services.annotation_staged import first_stage_dataset_rows_staged

    return first_stage_dataset_rows_staged(crm_db, limit=limit)
