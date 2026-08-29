"""Two-mode V3 routing: DIRECT GOODS vs OBJECT procurement (construction/design)."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.domain.commercial_routing_v3 import ProcurementForm, ResearchAction
from src.services.commercial_routing_v3.construction_semantics import (
    card_is_genuine_construction,
    is_genuine_construction_object,
)
from src.services.commercial_routing_v3.direct_product_evidence import (
    enforce_direct_supply_product_evidence,
)
from src.services.commercial_routing_v3.procurement_form import (
    strong_direct_goods_evidence,
    strong_object_procurement_evidence,
)

PROMPT_VERSION_OBJECT_MODE = "v3_category_centric_routing_7b_v4"

OBJECT_PROCUREMENT_FORMS: Set[str] = {
    ProcurementForm.CONSTRUCTION_WORKS.value,
    ProcurementForm.DESIGN_AND_BUILD.value,
    ProcurementForm.DESIGN_EXPERTISE_AND_BUILD.value,
    ProcurementForm.DESIGN_ONLY.value,
    ProcurementForm.SURVEY_AND_DESIGN.value,
}

DESIGN_FORMS: Set[str] = {
    ProcurementForm.DESIGN_ONLY.value,
    ProcurementForm.SURVEY_AND_DESIGN.value,
    ProcurementForm.DESIGN_AND_BUILD.value,
    ProcurementForm.DESIGN_EXPERTISE_AND_BUILD.value,
}

_CONSTRUCTION_DOC_PRIORITY = [
    "LOCAL_ESTIMATE",
    "SPECIFICATION",
    "BILL_OF_QUANTITIES",
    "TECHNICAL_ASSIGNMENT",
    "PROJECT_DOCUMENTATION",
    "OTHER_ATTACHMENTS",
]

_DESIGN_DOC_PRIORITY = [
    "DESIGN_TECHNICAL_ASSIGNMENT",
    "DESIGN_REQUIREMENTS",
    "SOURCE_INPUT_DATA",
    "EXISTING_PROJECT_DOCUMENTATION",
    "SPECIFICATIONS_AND_ATTACHMENTS",
]

_ROAD_RE = re.compile(r"дорог|покрыти|асфальт|магистрал|автомобильн\w*\s+дорог", re.I)
_BRIDGE_RE = re.compile(r"мост|путепровод|эстакад", re.I)
_SCHOOL_RE = re.compile(r"школ|образовательн", re.I)
_HEALTH_RE = re.compile(r"поликлиник|больниц|медицин|здрав", re.I)
_GAS_PIPE_RE = re.compile(r"газопровод|газопров", re.I)
_REPAIR_RE = re.compile(r"ремонт|ликвидаци|деформац|восстанов", re.I)
_CAPITAL_RE = re.compile(r"капитальн\w*\s+ремонт|капремонт|реконструкц", re.I)
_NEW_BUILD_RE = re.compile(r"строительств|новое\s+строительство", re.I)
_DESIGN_RE = re.compile(r"проектир|изыскан|рабоч\w*\s+документац|проектн", re.I)

# Road/object-fit weights for contextual categories (10753-style).
_ROAD_CONTEXTUAL_CATS = (
    "drainage_water_management",
    "curbstone",
    "lighting",
    "waterproofing",
    "composite_structures",
)


def is_object_procurement_form(form: str) -> bool:
    return str(form or "").upper() in OBJECT_PROCUREMENT_FORMS


def is_direct_goods_form(form: str) -> bool:
    return str(form or "").upper() == ProcurementForm.DIRECT_GOODS_PURCHASE.value


def _model_input(procurement: Dict[str, Any]) -> Dict[str, Any]:
    mi = procurement.get("v3_model_input")
    return mi if isinstance(mi, dict) else {}


def classify_work_stage(*, title: str, form: str) -> str:
    t = title or ""
    f = str(form or "").upper()
    if f in DESIGN_FORMS or _DESIGN_RE.search(t):
        if "SURVEY" in f or "изыск" in t.lower():
            return "SURVEY_AND_DESIGN"
        return "DESIGN"
    if _CAPITAL_RE.search(t):
        return "CAPITAL_REPAIR"
    if _REPAIR_RE.search(t):
        return "REPAIR"
    if _NEW_BUILD_RE.search(t):
        return "NEW_CONSTRUCTION"
    if f == ProcurementForm.CONSTRUCTION_WORKS.value:
        return "RECONSTRUCTION"
    return "UNKNOWN"


def classify_object(
    procurement: Dict[str, Any],
    *,
    form: str,
) -> Dict[str, Any]:
    """Structured object classification from title + OKPD + form (not OKPD prefix alone)."""
    mi = _model_input(procurement)
    title = str(procurement.get("title") or procurement.get("auction_name") or mi.get("title") or "")
    codes = list(mi.get("okpd_codes") or [])
    if procurement.get("okpd_code"):
        codes.insert(0, str(procurement["okpd_code"]))
    work_stage = classify_work_stage(title=title, form=form)

    sector = "UNKNOWN"
    obj_type = "UNKNOWN"
    subtype = "UNKNOWN"
    context: List[str] = []

    if _ROAD_RE.search(title):
        sector = "TRANSPORT_INFRASTRUCTURE"
        obj_type = "ROAD"
        subtype = "ROAD_PAVEMENT" if _REPAIR_RE.search(title) else "ROAD"
        context.append("ROAD_REPAIR" if _REPAIR_RE.search(title) else "ROAD_WORKS")
    elif _BRIDGE_RE.search(title):
        sector = "TRANSPORT_INFRASTRUCTURE"
        obj_type = "BRIDGE"
        context.append("BRIDGE_WORKS")
    elif _SCHOOL_RE.search(title):
        sector = "SOCIAL_INFRASTRUCTURE"
        obj_type = "SCHOOL"
        subtype = (
            "SCHOOL_BUILDING"
            if _CAPITAL_RE.search(title) or _REPAIR_RE.search(title)
            else "SCHOOL"
        )
        context.append("EDUCATION_FACILITY")
    elif _HEALTH_RE.search(title):
        sector = "HEALTHCARE"
        obj_type = "POLYCLINIC"
        context.append("HEALTHCARE_FACILITY")
    elif _GAS_PIPE_RE.search(title):
        sector = "UTILITY_INFRASTRUCTURE"
        obj_type = "GAS_PIPELINE"
        context.append("UTILITY_NETWORK")
    elif is_genuine_construction_object(title=title, okpd_codes=codes)[0]:
        sector = "GENERAL_CONSTRUCTION"
        obj_type = "BUILDING_OR_STRUCTURE"
        context.append("CONSTRUCTION_OBJECT")

    if work_stage == "REPAIR":
        context.append("REPAIR")
    elif work_stage == "CAPITAL_REPAIR":
        context.append("CAPITAL_REPAIR")
    elif work_stage == "DESIGN":
        context.append("DESIGN_STAGE")

    return {
        "object_sector": sector,
        "object_type": obj_type,
        "object_subtype": subtype,
        "object_context": context[:6],
        "work_stage": work_stage,
    }


def is_genuine_object_procurement(
    procurement: Dict[str, Any],
    *,
    form: str,
) -> Tuple[bool, str]:
    mi = _model_input(procurement)
    title = str(procurement.get("title") or mi.get("title") or "")
    codes = list(mi.get("okpd_codes") or [])
    f = str(form or "").upper()
    if f in DESIGN_FORMS:
        if _DESIGN_RE.search(title) or _SCHOOL_RE.search(title) or _ROAD_RE.search(title):
            return True, "DESIGN_OBJECT_SIGNAL"
        return False, "NOT_GENUINE_DESIGN_OBJECT"
    return card_is_genuine_construction(
        {"title": title, "okpd_codes": codes, "okpd_code": procurement.get("okpd_code")}
    )


def document_research_priority(*, form: str) -> List[str]:
    if str(form or "").upper() in DESIGN_FORMS:
        return list(_DESIGN_DOC_PRIORITY)
    return list(_CONSTRUCTION_DOC_PRIORITY)


def _default_track(form: str) -> str:
    if str(form or "").upper() in DESIGN_FORMS:
        return "DESIGN_REQUIREMENT"
    return "EMBEDDED_MATERIAL"


def _contextual_prior_rows(procurement: Dict[str, Any]) -> List[Dict[str, Any]]:
    mi = _model_input(procurement)
    rows = list(mi.get("CONTEXTUAL_RESEARCH_PRIORS") or [])
    out = []
    for row in rows:
        if isinstance(row, dict) and row.get("category"):
            out.append(row)
    return out


def _road_relevant_categories(obj: Dict[str, Any]) -> List[str]:
    if obj.get("object_type") == "ROAD":
        return list(_ROAD_CONTEXTUAL_CATS)
    if obj.get("object_type") == "SCHOOL":
        return ["lighting", "waterproofing", "flooring", "drainage_water_management"]
    return list(_ROAD_CONTEXTUAL_CATS)


def build_object_mode_hypotheses(
    procurement: Dict[str, Any],
    *,
    form: str,
    allowed_categories: Set[str],
    object_classification: Dict[str, Any],
    max_hypotheses: int = 5,
) -> List[Dict[str, Any]]:
    """Object-level Candidate hypotheses — contextual, confirmation required."""
    priors = _contextual_prior_rows(procurement)
    if not priors:
        return []

    obj_type = object_classification.get("object_type")
    if obj_type == "ROAD":
        preferred = set(_ROAD_CONTEXTUAL_CATS)
        priors = [p for p in priors if p.get("category") in preferred] or priors
    elif obj_type == "SCHOOL":
        preferred = set(_road_relevant_categories(object_classification))
        priors = [p for p in priors if p.get("category") in preferred] or priors

    track = _default_track(form)
    hyps: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for row in priors:
        cat = str(row.get("category") or "").strip()
        if not cat or cat in seen or cat not in allowed_categories:
            continue
        seen.add(cat)
        weight = float(row.get("weight") or 35)
        conf = min(0.62, max(0.28, 0.22 + weight / 200.0))
        why = (
            f"Object {object_classification.get('object_sector')}/"
            f"{object_classification.get('object_type')} — "
            f"{cat} commercially plausible; confirm in tender/project documents."
        )
        hyps.append(
            {
                "category_code": cat,
                "subcategory_code": "SUBCATEGORY_NOT_ASSIGNED",
                "subcategory_status": "SUBCATEGORY_NOT_ASSIGNED",
                "opportunity_track": track,
                "confidence": round(conf, 3),
                "research_action": ResearchAction.LIGHT_RESEARCH.value,
                "research_priority": 0,
                "commercial_priority_score": 0,
                "research_value_score": 0,
                "candidate_medal": None,
                "category_value_basis": "UNKNOWN_ADDRESSABLE_VALUE",
                "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
                "confirmation_required": True,
                "reason_codes": [
                    "object_mode_contextual_prior",
                    "requires_document_confirmation",
                    f"object_type:{object_classification.get('object_type')}",
                ],
                "positive_evidence": [
                    f"object_sector:{object_classification.get('object_sector')}",
                    f"object_type:{object_classification.get('object_type')}",
                    f"work_stage:{object_classification.get('work_stage')}",
                ],
                "negative_evidence": [],
                "why_category": why,
                "material_family": None,
                "work_method": None,
                "application_area": object_classification.get("object_subtype"),
                "object_context": list(object_classification.get("object_context") or [])[:3],
            }
        )
        if len(hyps) >= max_hypotheses:
            break
    return hyps


def _coerce_object_form(
    out: Dict[str, Any], procurement: Dict[str, Any]
) -> str:
    """Fix model misclassification (e.g. capital repair school as DIRECT_GOODS).

    Strong DIRECT_GOODS evidence wins over weak title/OKPD heuristics.
    Strong object/work semantics may still coerce a mistaken DIRECT_GOODS form.
    """
    form = str(
        out.get("procurement_form") or procurement.get("procurement_form") or ""
    ).upper()
    out.setdefault("procurement_form_raw_model", form or "UNKNOWN")
    sdg, sdg_reason = strong_direct_goods_evidence(procurement)
    sobj, sobj_reason = strong_object_procurement_evidence(procurement)
    out["STRONG_DIRECT_GOODS_EVIDENCE"] = "YES" if sdg else "NO"
    out["STRONG_OBJECT_EVIDENCE"] = "YES" if sobj else "NO"
    out["strong_direct_goods_reason"] = sdg_reason
    out["strong_object_reason"] = sobj_reason
    if is_object_procurement_form(form):
        out["form_coercion_applied"] = False
        return form
    if sdg and not sobj:
        out["form_coercion_applied"] = False
        out["FORM_COERCION_REASON"] = None
        out["form_coercion_reason"] = "strong_direct_goods_preserved"
        return form
    mi = _model_input(procurement)
    title = str(mi.get("title") or procurement.get("title") or "")
    lc = str(mi.get("normalized_lifecycle") or "").upper()
    genuine, genuine_reason = is_genuine_object_procurement(
        procurement, form="CONSTRUCTION_WORKS"
    )
    works_okpd = any(
        str(c).startswith(("41.", "42.", "43.")) for c in (mi.get("okpd_codes") or [])
    )
    capital_school = bool(_CAPITAL_RE.search(title) and _SCHOOL_RE.search(title))
    capital_building = bool(
        _CAPITAL_RE.search(title)
        and is_genuine_construction_object(
            title=title, okpd_codes=list(mi.get("okpd_codes") or [])
        )[0]
        and works_okpd
    )
    allow_object_safety = sobj or capital_school or (lc == "AWARDED" and capital_building)
    if not allow_object_safety and genuine and works_okpd and not sdg:
        allow_object_safety = True
        sobj_reason = genuine_reason
    if allow_object_safety:
        out["procurement_form"] = ProcurementForm.CONSTRUCTION_WORKS.value
        out["procurement_form_coerced_from"] = form or "UNKNOWN"
        out["form_coercion_applied"] = True
        out["FORM_COERCION_REASON"] = f"strong_object_safety:{sobj_reason}"
        out["form_coercion_reason"] = out["FORM_COERCION_REASON"]
        return out["procurement_form"]
    out["form_coercion_applied"] = False
    return form


def source_data_quality_label(procurement: Dict[str, Any]) -> str:
    """Lightweight SUSPECT flag for scoring (timing suppression only)."""
    mi = _model_input(procurement)
    reasons: List[str] = []
    table = str(mi.get("source_table") or procurement.get("source_table") or "")
    if "223" in table:
        reasons.append("223_FZ_SOURCE")
    ps = str(mi.get("procurement_start_at") or "")[:10]
    pe = str(mi.get("procurement_end_at") or "")[:10]
    if ps and pe and ps == pe:
        reasons.append("ZERO_DURATION_PROCEDURE_DATES")
    if str(mi.get("source_origin") or "").upper() == "UNKNOWN":
        reasons.append("SOURCE_ORIGIN_UNKNOWN")
    return "SUSPECT" if reasons else "OK"


def enrich_object_mode_routing(
    normalized: Dict[str, Any],
    procurement: Dict[str, Any],
    *,
    allowed_categories: Set[str],
) -> Dict[str, Any]:
    """Apply OBJECT MODE business semantics without mutating MODEL namespace fields.

    Phase 6B invariants:
    - ``object_classification`` stays MODEL (validated) — never overwritten
    - ``commercial_category_hypotheses`` stays MODEL — priors go to contextual/business
    - ``procurement_form`` stays MODEL — coercion stored as business_procurement_form
    """
    import copy

    # Freeze MODEL namespace from the validated input BEFORE any business mutation.
    src = dict(normalized or {})
    model_object_classification = copy.deepcopy(src.get("object_classification"))
    model_hyps = [
        copy.deepcopy(h)
        for h in (src.get("commercial_category_hypotheses") or [])
        if isinstance(h, dict)
    ]
    model_procurement_form = src.get("procurement_form")
    model_empty_status = src.get("empty_hypothesis_status")
    model_overall_action = src.get("overall_research_action")
    model_doc_priority = copy.deepcopy(src.get("document_research_priority"))

    # Business working copy — may be mutated by product-evidence / coercion / priors.
    out = enforce_direct_supply_product_evidence(copy.deepcopy(src), procurement)
    # Business hyps start from post-enforce working set (MODEL snapshot stays pristine).
    enforced_hyps = [
        copy.deepcopy(h)
        for h in (out.get("commercial_category_hypotheses") or [])
        if isinstance(h, dict)
    ]

    mi = _model_input(procurement)
    lc = str(
        mi.get("normalized_lifecycle") or procurement.get("normalized_lifecycle") or ""
    ).upper()
    if lc == "AWARDED":
        winner = mi.get("winner_name") or procurement.get("winner_name")
        out["awarded_context"] = {
            "normalized_lifecycle": "AWARDED",
            "winner_name": winner,
            "winner_inn": mi.get("winner_inn") or procurement.get("winner_inn"),
            "final_contract_price": mi.get("final_contract_price")
            or procurement.get("final_contract_price"),
            "delivery_start_at": mi.get("delivery_start_at")
            or procurement.get("delivery_start_at"),
            "delivery_end_at": mi.get("delivery_end_at") or procurement.get("delivery_end_at"),
            "execution_remaining_days": mi.get("execution_remaining_days"),
        }
        out["post_award_commercial_target"] = "WINNER_CONTRACTOR"
        out["post_award_commercial_target_name"] = winner

    form = _coerce_object_form(out, procurement)
    out["business_procurement_form"] = form
    # Restore MODEL procurement_form (coercion must not impersonate model).
    out["procurement_form"] = model_procurement_form

    if not is_object_procurement_form(form):
        out["routing_mode"] = "DIRECT_OR_OTHER"
        out["object_classification"] = model_object_classification
        out["commercial_category_hypotheses"] = model_hyps
        out["business_category_hypotheses"] = list(enforced_hyps)
        out["contextual_prior_hypotheses"] = []
        return out

    obj = classify_object(procurement, form=form)
    genuine, genuine_reason = is_genuine_object_procurement(procurement, form=form)
    out["routing_mode"] = "OBJECT_MODE" if genuine else "OBJECT_MODE_NON_TARGET"
    out["business_object_classification"] = obj
    # MODEL object_classification is never replaced by Python classify_object.
    out["object_classification"] = model_object_classification
    out["document_research_priority"] = (
        model_doc_priority
        if model_doc_priority is not None
        else document_research_priority(form=form)
    )
    out["business_document_research_priority"] = document_research_priority(form=form)
    out["object_mode_genuine"] = genuine
    out["object_mode_genuine_reason"] = genuine_reason

    if not genuine:
        out["commercial_category_hypotheses"] = model_hyps
        out["business_category_hypotheses"] = list(enforced_hyps)
        out["contextual_prior_hypotheses"] = []
        return out

    empty = str(model_empty_status or "").upper() or None
    mistaken_nce = empty == "NO_COMMERCIAL_ENTRY" or (
        not model_hyps and empty in (None, "NO_COMMERCIAL_ENTRY")
    )

    built: List[Dict[str, Any]] = []
    if mistaken_nce or len(model_hyps) < 1:
        tagged: List[Dict[str, Any]] = []
        for h in build_object_mode_hypotheses(
            procurement,
            form=form,
            allowed_categories=allowed_categories,
            object_classification=obj,
        ):
            row = dict(h)
            row["provenance"] = "CONTEXT_PRIOR"
            rc = list(row.get("reason_codes") or [])
            if "object_mode_contextual_prior" not in rc:
                rc.append("object_mode_contextual_prior")
            row["reason_codes"] = rc[:6]
            tagged.append(row)
        built = tagged
        out["object_mode_nce_override"] = bool(mistaken_nce)
        if mistaken_nce:
            out["empty_hypothesis_reason_codes"] = list(
                out.get("empty_hypothesis_reason_codes") or []
            ) + ["object_mode_blocked_mistaken_nce"]
        # Business may clear empty status for scoring; MODEL empty status restored below.
        out["business_empty_hypothesis_status"] = None
        out["discovery_required"] = True
        out["review_required"] = False
        out["business_overall_research_action"] = ResearchAction.LIGHT_RESEARCH.value

    # Business working set = post-enforce hyps + contextual priors (priors never enter MODEL list).
    business_hyps: List[Dict[str, Any]] = [dict(h) for h in enforced_hyps]
    by_cat = {h["category_code"]: h for h in business_hyps if h.get("category_code")}
    for h in built:
        by_cat.setdefault(h["category_code"], dict(h))
    business_hyps = list(by_cat.values())[:5]

    fixed: List[Dict[str, Any]] = []
    for h in business_hyps:
        row = dict(h)
        is_prior = (
            row.get("provenance") == "CONTEXT_PRIOR"
            or "object_mode_contextual_prior" in list(row.get("reason_codes") or [])
        )
        if str(row.get("opportunity_track") or "").upper() == "DIRECT_SUPPLY":
            row["opportunity_track"] = _default_track(form)
            row["reason_codes"] = list(row.get("reason_codes") or []) + [
                "track_coerced_object_mode"
            ]
        if is_prior:
            row.setdefault("evidence_role", "CONTEXTUAL_RESEARCH_PRIOR")
            row.setdefault("confirmation_required", True)
            row["provenance"] = "CONTEXT_PRIOR"
            rc = list(row.get("reason_codes") or [])
            if "requires_document_confirmation" not in rc:
                rc.append("requires_document_confirmation")
            row["reason_codes"] = rc[:6]
        else:
            row.setdefault("provenance", "MODEL_VALIDATED")
        fixed.append(row)

    if fixed and str(
        out.get("business_overall_research_action") or model_overall_action or ""
    ).upper() in ("SKIP", "METADATA_ONLY"):
        out["business_overall_research_action"] = ResearchAction.LIGHT_RESEARCH.value

    if lc == "AWARDED" and fixed:
        out["business_overall_research_action"] = ResearchAction.PRIORITY_DOCS.value
        for row in fixed:
            rc = list(row.get("reason_codes") or [])
            if "post_award_winner_target" not in rc:
                rc.append("post_award_winner_target")
            row["reason_codes"] = rc[:6]

    out["DOCUMENT_RESEARCH_REQUIRED"] = bool(fixed)

    # Restore MODEL namespace — priors live only under contextual/business keys.
    out["object_classification"] = model_object_classification
    out["procurement_form"] = model_procurement_form
    out["commercial_category_hypotheses"] = model_hyps
    out["empty_hypothesis_status"] = model_empty_status
    out["overall_research_action"] = model_overall_action
    out["contextual_prior_hypotheses"] = [
        h for h in fixed if h.get("provenance") == "CONTEXT_PRIOR"
    ]
    out["business_category_hypotheses"] = fixed
    return out


def classify_procurement_mode(title: str, okpd_code: Optional[str] = None) -> str:
    """Deterministic classification of procurement mode based on title and OKPD code.
    
    Returns one of:
    - PROJECT
    - WORKS
    - PROJECT_AND_WORKS
    - DIRECT_SUPPLY
    - UNCERTAIN
    """
    t = (title or "").lower()
    okpd = (okpd_code or "").strip()

    has_design = bool(re.search(r"проектн|проектир|изыскан|пшд|псд|разработк\w*\s+проект", t))
    has_works = bool(re.search(r"капитальн\w*\s+ремонт|капремонт|ремонт|строительст|выполнен\w*\s+работ|монтаж|устройств", t))
    has_supply = bool(re.search(r"поставк|закупк|приобретен|оказани\w*\s+услуг|оснащен", t))

    if okpd.startswith("71.1") or okpd.startswith("71.12"):
        if has_works:
            return "PROJECT_AND_WORKS"
        return "PROJECT"

    if okpd.startswith("41") or okpd.startswith("42") or okpd.startswith("43"):
        if has_design:
            return "PROJECT_AND_WORKS"
        return "WORKS"

    if okpd.startswith("26") or okpd.startswith("27"):
        if not (has_works or has_design):
            return "DIRECT_SUPPLY"

    if has_design and has_works:
        return "PROJECT_AND_WORKS"
    elif has_design:
        return "PROJECT"
    elif has_works:
        return "WORKS"
    elif has_supply or okpd.startswith("26") or okpd.startswith("27") or okpd.startswith("28") or okpd.startswith("31") or okpd.startswith("32"):
        return "DIRECT_SUPPLY"
    else:
        return "UNCERTAIN"
