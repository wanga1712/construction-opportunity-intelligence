"""V3 prompt v6.3 — Phase 7.1 balance pass (SHADOW only).

v6_2 fixed negative/example-leakage but over-abstained on clear directs.
v6_3 keeps v6_2 negative/object anti-spam guards and restores strong DIRECT
positive examples (general patterns, not ID-specific).

Frozen: v6_1, v6_2 remain for comparison. Production stays on prompt.py v5.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from src.services.commercial_routing_v3.prompt import (
    allowed_category_codes_block,
    compact_registry_for_prompt,
)

PROMPT_VERSION = "v3_category_centric_routing_7b_v6_3"
NUM_PREDICT = 640

_FORMS = (
    "DIRECT_GOODS_PURCHASE | CONSTRUCTION_WORKS | DESIGN_AND_BUILD | "
    "DESIGN_EXPERTISE_AND_BUILD | DESIGN_ONLY | SURVEY_AND_DESIGN | "
    "WORKS_OTHER | SERVICES_OTHER | UNKNOWN"
)


def build_v6_3_prompt_from_model_input(
    model_input: Dict[str, Any],
    *,
    registry: List[Dict[str, Any]],
    okpd_priors: List[Dict[str, Any]],
    procurement_form_prior: str,
) -> str:
    from src.services.commercial_routing_v3.model_input import (
        model_input_as_prompt_procurement,
        model_input_json,
    )

    procurement = model_input_as_prompt_procurement(model_input)
    compact_reg, _ = compact_registry_for_prompt(registry, procurement, okpd_priors)
    registry_desc = "Live commercial registry (category_code MUST match exactly):\n"
    for cat in compact_reg:
        registry_desc += (
            f"- {cat['category_code']}: {cat.get('category_name', '')} "
            f"[{cat.get('lifecycle_state', 'ACTIVE')}]\n"
        )

    code = str(procurement.get("okpd_code") or "")
    priors = [
        p
        for p in okpd_priors
        if code
        and str(p.get("okpd_pattern") or "")
        and (code == str(p["okpd_pattern"]) or code.startswith(str(p["okpd_pattern"])))
    ][:12]

    mi_json = model_input_json(model_input)
    return (
        "You are a commercial routing expert for public procurements (V3).\n"
        "Reply with ONE compact JSON object only. No markdown. No prose.\n"
        f"prompt_version={PROMPT_VERSION}\n"
        f"model_input_version={model_input.get('model_input_version')}\n\n"
        "CRITICAL: Decide form FIRST. DIRECT goods rules and OBJECT rules must not mix.\n"
        "If procurement_form=DIRECT_GOODS_PURCHASE, IGNORE the bare-road empty example.\n\n"
        "DECISION ORDER:\n"
        "STEP 1 — What is actually being procured? (product name OR work/object OR service)\n"
        "STEP 2 — ONE procurement_form (never pipe-joined).\n"
        "STEP 3 — If DIRECT_GOODS_PURCHASE:\n"
        "  Map the purchased item itself to an ACTIVE registry code when title/OKPD clearly names it.\n"
        "  Emit hypothesis (DIRECT_SUPPLY, confirmation_required=false). Do NOT abstain for missing docs.\n"
        "  Patterns: светильник/лампа→lighting; ноутбук/ПК/моноблок/компьютер→computers; "
        "линолеум/ламинат→flooring; гидроизоляция→waterproofing; "
        "кабельн* лоток/кабеленесущ→cable_support_systems; бордюр→curbstone; "
        "дренаж/ливнев*/оборудование ливневой канализации→drainage_water_management.\n"
        "  Outside registry product → [] + NO_COMMERCIAL_ENTRY + SKIP.\n"
        "  Spare parts FOR equipment → [] + REVIEW_REQUIRED (not the equipment category).\n"
        "STEP 4 — If CONSTRUCTION_WORKS/DESIGN_*/WORKS_OTHER:\n"
        "  Contextual hyps only with material/object evidence "
        "(confirmation_required=true). Bare road/building without material words → "
        "[] + INSUFFICIENT_EVIDENCE|REVIEW_REQUIRED. Never invent categories because they are "
        "common in construction or because customer facility might contain them.\n"
        "STEP 5 — If SERVICES_OTHER (поверка/verification/consulting/security services):\n"
        "  [] + NO_COMMERCIAL_ENTRY. Never emit curbstone/lighting/drainage/flooring.\n"
        "STEP 6 — hypotheses=[] requires empty_hypothesis_status (null INVALID).\n"
        "overall_research_action ONE of SKIP|METADATA_ONLY|LIGHT_RESEARCH|PRIORITY_DOCS|DEEP_RESEARCH.\n\n"
        f"Allowed procurement_form: {_FORMS}\n"
        f"Heuristic form prior (not dogma): {procurement_form_prior}\n"
        "category_code MUST match ALLOWED list exactly. No medals/scores.\n\n"
        f"{allowed_category_codes_block(registry)}\n"
        f"{registry_desc}\n"
        f"OKPD/title priors HINTS only:\n{json.dumps(priors, ensure_ascii=False, default=str)}\n\n"
        f"INPUT:\n{mi_json}\n\n"
        "POS lighting: "
        '{"procurement_form":"DIRECT_GOODS_PURCHASE","commercial_category_hypotheses":'
        '[{"category_code":"lighting","opportunity_track":"DIRECT_SUPPLY","confidence":0.8,'
        '"research_action":"LIGHT_RESEARCH","reason_codes":["title_product_match"],'
        '"evidence_role":"DIRECT_CATEGORY_EVIDENCE","confirmation_required":false,'
        '"subcategory_code":"SUBCATEGORY_NOT_ASSIGNED"}],'
        '"object_classification":{"object_type":"GOODS","object_subtype":"LIGHTING","work_stage":"SUPPLY"},'
        '"empty_hypothesis_status":null,"overall_research_action":"LIGHT_RESEARCH",'
        '"analysis_modes":["DIRECT_PRODUCT"],"source_contour":"PUBLIC_44FZ",'
        '"object_context":[],"material_signals":[],"work_methods":[],"application_areas":[],'
        '"brands":[],"document_research_priority":[],"preferred_opportunity_track":null,'
        '"empty_hypothesis_reason_codes":[],"discovery_required":false}\n'
        "POS computers/monoblock: same shape with category_code=computers, object_subtype=COMPUTERS.\n"
        "POS flooring/linoleum: category_code=flooring.\n"
        "POS storm-sewer equipment: category_code=drainage_water_management.\n"
        "NEG service verification: "
        '{"procurement_form":"SERVICES_OTHER","commercial_category_hypotheses":[],'
        '"empty_hypothesis_status":"NO_COMMERCIAL_ENTRY","overall_research_action":"SKIP",'
        '"object_classification":{"object_type":"SERVICE","object_subtype":"METERING_VERIFICATION",'
        '"work_stage":"SERVICE"},"analysis_modes":["DIRECT_PRODUCT"],"source_contour":"PUBLIC_44FZ",'
        '"object_context":[],"material_signals":[],"work_methods":[],"application_areas":[],'
        '"brands":[],"document_research_priority":[],"preferred_opportunity_track":null,'
        '"empty_hypothesis_reason_codes":["service_outside_registry"],"discovery_required":false}\n'
        "OBJ bare road (NOT for direct goods): "
        '{"procurement_form":"CONSTRUCTION_WORKS","commercial_category_hypotheses":[],'
        '"empty_hypothesis_status":"INSUFFICIENT_EVIDENCE","overall_research_action":"LIGHT_RESEARCH",'
        '"object_classification":{"object_type":"ROAD","object_subtype":"ROAD_REPAIR","work_stage":"REPAIR"},'
        '"analysis_modes":["EMBEDDED_MATERIAL_DISCOVERY"],"source_contour":"PUBLIC_44FZ",'
        '"object_context":[],"material_signals":[],"work_methods":[],"application_areas":[],'
        '"brands":[],"document_research_priority":["LOCAL_ESTIMATE"],"preferred_opportunity_track":null,'
        '"empty_hypothesis_reason_codes":["no_material_evidence_in_title"],"discovery_required":true}\n'
    )


def build_v6_3_prompt(
    procurement: Dict[str, Any],
    *,
    registry: List[Dict[str, Any]],
    okpd_priors: List[Dict[str, Any]],
    routing_signals: List[Dict[str, Any]],
    procurement_form_prior: str,
) -> str:
    del routing_signals
    model_input = procurement.get("v3_model_input")
    if isinstance(model_input, dict) and model_input.get("model_input_version"):
        return build_v6_3_prompt_from_model_input(
            model_input,
            registry=registry,
            okpd_priors=okpd_priors,
            procurement_form_prior=procurement_form_prior,
        )
    thin = {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "title": procurement.get("title") or procurement.get("auction_name"),
        "okpd_codes": [procurement.get("okpd_code")] if procurement.get("okpd_code") else [],
        "okpd_name": procurement.get("okpd_name"),
        "price": procurement.get("price") or procurement.get("initial_price"),
        "customer": procurement.get("customer"),
        "law_type": procurement.get("law_type"),
        "source_table": procurement.get("source_table"),
        "region": procurement.get("region") or procurement.get("delivery_region"),
    }
    return build_v6_3_prompt_from_model_input(
        thin,
        registry=registry,
        okpd_priors=okpd_priors,
        procurement_form_prior=procurement_form_prior,
    )
