"""FROZEN SHADOW prompt v6.1 — do not edit; Phase 7.1 compares against this.

Frozen snapshot of Phase 7 candidate. Production default remains prompt.py v5.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from src.services.commercial_routing_v3.prompt import (
    allowed_category_codes_block,
    compact_registry_for_prompt,
)

PROMPT_VERSION = "v3_category_centric_routing_7b_v6_1"
NUM_PREDICT = 640

_FORMS = (
    "DIRECT_GOODS_PURCHASE | CONSTRUCTION_WORKS | DESIGN_AND_BUILD | "
    "DESIGN_EXPERTISE_AND_BUILD | DESIGN_ONLY | SURVEY_AND_DESIGN | "
    "WORKS_OTHER | SERVICES_OTHER | UNKNOWN"
)


def build_v6_1_prompt_from_model_input(
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
        "DECISION ORDER (follow exactly):\n"
        "1) Set procurement_form from the allowed list (ONE token, never pipe-joined).\n"
        "2) Set object_classification with SHORT ENGLISH tokens "
        "(e.g. ROAD, SCHOOL, GOODS, CAPITAL_REPAIR).\n"
        "3) Inspect ALLOWED_COMMERCIAL_CATEGORY_CODES.\n"
        "4) Decide hypotheses:\n"
        "   A) DIRECT_GOODS_PURCHASE:\n"
        "      - If title clearly names a sellable registry product → emit that category_code "
        "(track=DIRECT_SUPPLY, confirmation_required=false).\n"
        "      - Examples that MUST map when title is clear: "
        "светильник/лампа→lighting; ноутбук/ПК→computers; линолеум/ламинат→flooring; "
        "гидроизоляция→waterproofing; кабельн* лоток/кабеленесущ→cable_support_systems; "
        "бордюр→curbstone; дренаж/ливнев→drainage_water_management.\n"
        "      - Spare parts / consumables FOR equipment (not the equipment itself) → "
        "hypotheses=[] empty_hypothesis_status=REVIEW_REQUIRED (not a forced product category).\n"
        "      - Multi-product title listing several registry goods → emit 1–3 matching codes "
        "OR hypotheses=[] empty_hypothesis_status=REVIEW_REQUIRED.\n"
        "      - Product clearly outside registry → hypotheses=[] "
        "empty_hypothesis_status=NO_COMMERCIAL_ENTRY overall_research_action=SKIP.\n"
        "      - Do NOT invent flooring/waterproofing/drainage for a generic building/module "
        "unless those words appear in title/OKPD evidence.\n"
        "   B) CONSTRUCTION_WORKS / DESIGN_*:\n"
        "      Emit 0–3 contextual hypotheses only when commercially plausible "
        "(track=EMBEDDED_MATERIAL|DESIGN_REQUIREMENT|DESIGN_INFLUENCE, "
        "evidence_role=CONTEXTUAL_RESEARCH_PRIOR, confirmation_required=true).\n"
        "      Do NOT invent drainage/waterproofing/lighting merely because it is a road/building.\n"
        "      If weak evidence → hypotheses=[] AND empty_hypothesis_status="
        "INSUFFICIENT_EVIDENCE or REVIEW_REQUIRED.\n"
        "5) If commercial_category_hypotheses is [] then empty_hypothesis_status MUST be one of "
        "NO_COMMERCIAL_ENTRY|INSUFFICIENT_EVIDENCE|REVIEW_REQUIRED (null is INVALID).\n"
        "6) overall_research_action ONE of: SKIP|METADATA_ONLY|LIGHT_RESEARCH|"
        "PRIORITY_DOCS|DEEP_RESEARCH.\n\n"
        f"Allowed procurement_form values: {_FORMS}\n"
        "Heuristic form prior (not dogma): "
        f"{procurement_form_prior}\n\n"
        "category_code rules:\n"
        "- MUST be copied exactly from ALLOWED_COMMERCIAL_CATEGORY_CODES.\n"
        "- NEVER use OKPD codes, Russian labels, or invented names as category_code.\n"
        "- Do NOT output candidate_medal or candidate_score.\n\n"
        f"{allowed_category_codes_block(registry)}\n"
        f"{registry_desc}\n"
        f"OKPD/title priors are HINTS only (not answers):\n"
        f"{json.dumps(priors, ensure_ascii=False, default=str)}\n\n"
        "INPUT (V3_ROUTING_MODEL_INPUT_V3):\n"
        f"{mi_json}\n\n"
        "POSITIVE EXAMPLE lighting:\n"
        '{"source_contour":"PUBLIC_44FZ","procurement_form":"DIRECT_GOODS_PURCHASE",'
        '"analysis_modes":["DIRECT_PRODUCT"],'
        '"object_context":[],"material_signals":[],"work_methods":[],"application_areas":[],"brands":[],'
        '"commercial_category_hypotheses":[{'
        '"category_code":"lighting","subcategory_code":"SUBCATEGORY_NOT_ASSIGNED",'
        '"opportunity_track":"DIRECT_SUPPLY","confidence":0.75,'
        '"research_action":"LIGHT_RESEARCH","reason_codes":["title_product_match"],'
        '"evidence_role":"DIRECT_CATEGORY_EVIDENCE","confirmation_required":false}],'
        '"object_classification":{"object_sector":"SUPPLY","object_type":"GOODS",'
        '"object_subtype":"LIGHTING","object_context":[],"work_stage":"SUPPLY"},'
        '"document_research_priority":[],'
        '"empty_hypothesis_status":null,"preferred_opportunity_track":null,'
        '"empty_hypothesis_reason_codes":[],"discovery_required":false,'
        '"overall_research_action":"LIGHT_RESEARCH"}\n\n'
        "POSITIVE EXAMPLE flooring (линолеум):\n"
        '{"source_contour":"PUBLIC_44FZ","procurement_form":"DIRECT_GOODS_PURCHASE",'
        '"analysis_modes":["DIRECT_PRODUCT"],'
        '"object_context":[],"material_signals":[],"work_methods":[],"application_areas":[],"brands":[],'
        '"commercial_category_hypotheses":[{'
        '"category_code":"flooring","subcategory_code":"SUBCATEGORY_NOT_ASSIGNED",'
        '"opportunity_track":"DIRECT_SUPPLY","confidence":0.8,'
        '"research_action":"LIGHT_RESEARCH","reason_codes":["title_product_match"],'
        '"evidence_role":"DIRECT_CATEGORY_EVIDENCE","confirmation_required":false}],'
        '"object_classification":{"object_sector":"SUPPLY","object_type":"GOODS",'
        '"object_subtype":"FLOORING","object_context":[],"work_stage":"SUPPLY"},'
        '"document_research_priority":[],'
        '"empty_hypothesis_status":null,"preferred_opportunity_track":null,'
        '"empty_hypothesis_reason_codes":[],"discovery_required":false,'
        '"overall_research_action":"LIGHT_RESEARCH"}\n\n'
        "POSITIVE EXAMPLE cable_support_systems:\n"
        '{"source_contour":"PUBLIC_44FZ","procurement_form":"DIRECT_GOODS_PURCHASE",'
        '"analysis_modes":["DIRECT_PRODUCT"],'
        '"object_context":[],"material_signals":[],"work_methods":[],"application_areas":[],"brands":[],'
        '"commercial_category_hypotheses":[{'
        '"category_code":"cable_support_systems","subcategory_code":"SUBCATEGORY_NOT_ASSIGNED",'
        '"opportunity_track":"DIRECT_SUPPLY","confidence":0.75,'
        '"research_action":"LIGHT_RESEARCH","reason_codes":["title_product_match"],'
        '"evidence_role":"DIRECT_CATEGORY_EVIDENCE","confirmation_required":false}],'
        '"object_classification":{"object_sector":"SUPPLY","object_type":"GOODS",'
        '"object_subtype":"CABLE_SUPPORT","object_context":[],"work_stage":"SUPPLY"},'
        '"document_research_priority":[],'
        '"empty_hypothesis_status":null,"preferred_opportunity_track":null,'
        '"empty_hypothesis_reason_codes":[],"discovery_required":false,'
        '"overall_research_action":"LIGHT_RESEARCH"}\n\n'
        "NEGATIVE EXAMPLE (outside registry):\n"
        '{"source_contour":"PUBLIC_44FZ","procurement_form":"DIRECT_GOODS_PURCHASE",'
        '"analysis_modes":["DIRECT_PRODUCT"],'
        '"object_context":[],"material_signals":[],"work_methods":[],"application_areas":[],"brands":[],'
        '"commercial_category_hypotheses":[],'
        '"object_classification":{"object_sector":"SUPPLY","object_type":"GOODS",'
        '"object_subtype":"OTHER","object_context":[],"work_stage":"SUPPLY"},'
        '"document_research_priority":[],'
        '"empty_hypothesis_status":"NO_COMMERCIAL_ENTRY","preferred_opportunity_track":null,'
        '"empty_hypothesis_reason_codes":["product_outside_registry"],'
        '"discovery_required":false,"overall_research_action":"SKIP"}\n\n'
        "OBJECT EXAMPLE (contextual, confirmation required):\n"
        '{"source_contour":"PUBLIC_44FZ","procurement_form":"CONSTRUCTION_WORKS",'
        '"analysis_modes":["EMBEDDED_MATERIAL_DISCOVERY"],'
        '"object_context":[],"material_signals":[],"work_methods":[],"application_areas":[],"brands":[],'
        '"commercial_category_hypotheses":[{'
        '"category_code":"curbstone","subcategory_code":"SUBCATEGORY_NOT_ASSIGNED",'
        '"opportunity_track":"EMBEDDED_MATERIAL","confidence":0.4,'
        '"research_action":"LIGHT_RESEARCH","reason_codes":["object_context_plausible"],'
        '"evidence_role":"CONTEXTUAL_RESEARCH_PRIOR","confirmation_required":true}],'
        '"object_classification":{"object_sector":"TRANSPORT_INFRASTRUCTURE","object_type":"ROAD",'
        '"object_subtype":"ROAD_REPAIR","object_context":["REPAIR"],"work_stage":"REPAIR"},'
        '"document_research_priority":["LOCAL_ESTIMATE","SPECIFICATION"],'
        '"empty_hypothesis_status":null,"preferred_opportunity_track":null,'
        '"empty_hypothesis_reason_codes":[],"discovery_required":true,'
        '"overall_research_action":"LIGHT_RESEARCH"}\n\n'
        "REMINDER: empty hypotheses without empty_hypothesis_status is invalid JSON for this task.\n"
    )


def build_v6_1_prompt(
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
        return build_v6_1_prompt_from_model_input(
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
    return build_v6_1_prompt_from_model_input(
        thin,
        registry=registry,
        okpd_priors=okpd_priors,
        procurement_form_prior=procurement_form_prior,
    )
