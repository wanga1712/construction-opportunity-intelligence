"""V3 prompt v6.2 — Phase 7.1 residual calibration (SHADOW only).

Frozen baseline for comparison: prompt_v6_1.PROMPT_VERSION.
Production default remains prompt.py v5.

Minimal generalizable changes vs v6.1:
- explicit STEP 1–5 decision order (what procured → form → direct map / object context)
- stronger DIRECT positive guard (explicit product → no abstention)
- stronger negative guard (services / unrelated facility context ≠ category)
- object example uses empty+REVIEW for bare road (reduces curbstone/drainage leakage)
- monoblock / storm-sewer equipment named as general DIRECT map patterns
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from src.services.commercial_routing_v3.prompt import (
    allowed_category_codes_block,
    compact_registry_for_prompt,
)

PROMPT_VERSION = "v3_category_centric_routing_7b_v6_2"
NUM_PREDICT = 640

_FORMS = (
    "DIRECT_GOODS_PURCHASE | CONSTRUCTION_WORKS | DESIGN_AND_BUILD | "
    "DESIGN_EXPERTISE_AND_BUILD | DESIGN_ONLY | SURVEY_AND_DESIGN | "
    "WORKS_OTHER | SERVICES_OTHER | UNKNOWN"
)


def build_v6_2_prompt_from_model_input(
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
        "DECISION ORDER (mandatory):\n"
        "STEP 1 — What is actually being procured? Name the purchased item or the work/object.\n"
        "STEP 2 — Choose ONE procurement_form (never pipe-joined).\n"
        "  DIRECT_GOODS_PURCHASE = title is supply/purchase of a product.\n"
        "  CONSTRUCTION_WORKS / DESIGN_* / WORKS_OTHER = building/repair/design object.\n"
        "  SERVICES_OTHER = verification, maintenance-as-service, consulting, etc.\n"
        "STEP 3 — DIRECT_GOODS_PURCHASE only:\n"
        "  If the named purchased item itself maps to ONE active registry category → emit it "
        "(track=DIRECT_SUPPLY, confirmation_required=false, confidence usually 0.6–0.9).\n"
        "  Do NOT abstain merely because documents are absent — explicit product in title/OKPD is enough.\n"
        "  Direct map examples (general patterns, not ID-specific):\n"
        "    светильник/лампа → lighting\n"
        "    ноутбук/ПК/моноблок/персональн* компьютер → computers\n"
        "    линолеум/ламинат → flooring\n"
        "    гидроизоляция → waterproofing\n"
        "    кабельн* лоток/кабеленесущ → cable_support_systems\n"
        "    бордюр/поребрик → curbstone\n"
        "    дренаж / ливнев* / оборудование ливневой канализации → drainage_water_management\n"
        "  If product is clearly outside registry → hypotheses=[] "
        "empty_hypothesis_status=NO_COMMERCIAL_ENTRY overall_research_action=SKIP.\n"
        "  Do NOT invent adjacent categories. Spare parts FOR equipment ≠ the equipment category "
        "(use REVIEW_REQUIRED).\n"
        "STEP 4 — OBJECT / WORKS / DESIGN only:\n"
        "  Emit contextual hypotheses ONLY if a registry category is plausibly part of THIS "
        "object/work scope and worth document research "
        "(confirmation_required=true, evidence_role=CONTEXTUAL_RESEARCH_PRIOR).\n"
        "  Do NOT emit a category merely because it is common in construction, or because the "
        "customer facility might contain it.\n"
        "  Bare road/bridge/building repair without material evidence → hypotheses=[] "
        "empty_hypothesis_status=INSUFFICIENT_EVIDENCE or REVIEW_REQUIRED.\n"
        "STEP 5 — SERVICES_OTHER / unrelated metering/lab/medical services:\n"
        "  hypotheses=[] empty_hypothesis_status=NO_COMMERCIAL_ENTRY (never invent curbstone/"
        "lighting/drainage/flooring).\n"
        "STEP 6 — If hypotheses=[] then empty_hypothesis_status MUST be set "
        "(null is INVALID).\n"
        "overall_research_action ONE of: SKIP|METADATA_ONLY|LIGHT_RESEARCH|PRIORITY_DOCS|DEEP_RESEARCH.\n\n"
        f"Allowed procurement_form values: {_FORMS}\n"
        "Heuristic form prior (not dogma): "
        f"{procurement_form_prior}\n\n"
        "category_code MUST be copied exactly from ALLOWED_COMMERCIAL_CATEGORY_CODES.\n"
        "Never output candidate_medal or candidate_score.\n\n"
        f"{allowed_category_codes_block(registry)}\n"
        f"{registry_desc}\n"
        f"OKPD/title priors are HINTS only (not answers):\n"
        f"{json.dumps(priors, ensure_ascii=False, default=str)}\n\n"
        "INPUT (V3_ROUTING_MODEL_INPUT_V3):\n"
        f"{mi_json}\n\n"
        "POSITIVE EXAMPLE (computers / monoblock):\n"
        '{"source_contour":"PUBLIC_44FZ","procurement_form":"DIRECT_GOODS_PURCHASE",'
        '"analysis_modes":["DIRECT_PRODUCT"],'
        '"object_context":[],"material_signals":[],"work_methods":[],"application_areas":[],"brands":[],'
        '"commercial_category_hypotheses":[{'
        '"category_code":"computers","subcategory_code":"SUBCATEGORY_NOT_ASSIGNED",'
        '"opportunity_track":"DIRECT_SUPPLY","confidence":0.8,'
        '"research_action":"LIGHT_RESEARCH","reason_codes":["title_product_match"],'
        '"evidence_role":"DIRECT_CATEGORY_EVIDENCE","confirmation_required":false}],'
        '"object_classification":{"object_sector":"SUPPLY","object_type":"GOODS",'
        '"object_subtype":"COMPUTERS","object_context":[],"work_stage":"SUPPLY"},'
        '"document_research_priority":[],'
        '"empty_hypothesis_status":null,"preferred_opportunity_track":null,'
        '"empty_hypothesis_reason_codes":[],"discovery_required":false,'
        '"overall_research_action":"LIGHT_RESEARCH"}\n\n'
        "POSITIVE EXAMPLE (storm-sewer / drainage equipment supply):\n"
        '{"source_contour":"PUBLIC_44FZ","procurement_form":"DIRECT_GOODS_PURCHASE",'
        '"analysis_modes":["DIRECT_PRODUCT"],'
        '"object_context":[],"material_signals":[],"work_methods":[],"application_areas":[],"brands":[],'
        '"commercial_category_hypotheses":[{'
        '"category_code":"drainage_water_management","subcategory_code":"SUBCATEGORY_NOT_ASSIGNED",'
        '"opportunity_track":"DIRECT_SUPPLY","confidence":0.75,'
        '"research_action":"LIGHT_RESEARCH","reason_codes":["title_product_match"],'
        '"evidence_role":"DIRECT_CATEGORY_EVIDENCE","confirmation_required":false}],'
        '"object_classification":{"object_sector":"SUPPLY","object_type":"GOODS",'
        '"object_subtype":"STORM_SEWER_EQUIPMENT","object_context":[],"work_stage":"SUPPLY"},'
        '"document_research_priority":[],'
        '"empty_hypothesis_status":null,"preferred_opportunity_track":null,'
        '"empty_hypothesis_reason_codes":[],"discovery_required":false,'
        '"overall_research_action":"LIGHT_RESEARCH"}\n\n'
        "NEGATIVE EXAMPLE (service / metering verification — outside sellable registry):\n"
        '{"source_contour":"PUBLIC_44FZ","procurement_form":"SERVICES_OTHER",'
        '"analysis_modes":["DIRECT_PRODUCT"],'
        '"object_context":[],"material_signals":[],"work_methods":[],"application_areas":[],"brands":[],'
        '"commercial_category_hypotheses":[],'
        '"object_classification":{"object_sector":"SERVICES","object_type":"SERVICE",'
        '"object_subtype":"METERING_VERIFICATION","object_context":[],"work_stage":"SERVICE"},'
        '"document_research_priority":[],'
        '"empty_hypothesis_status":"NO_COMMERCIAL_ENTRY","preferred_opportunity_track":null,'
        '"empty_hypothesis_reason_codes":["service_outside_registry"],'
        '"discovery_required":false,"overall_research_action":"SKIP"}\n\n'
        "OBJECT EXAMPLE (bare road repair — no material words → empty + review):\n"
        '{"source_contour":"PUBLIC_44FZ","procurement_form":"CONSTRUCTION_WORKS",'
        '"analysis_modes":["EMBEDDED_MATERIAL_DISCOVERY"],'
        '"object_context":[],"material_signals":[],"work_methods":[],"application_areas":[],"brands":[],'
        '"commercial_category_hypotheses":[],'
        '"object_classification":{"object_sector":"TRANSPORT_INFRASTRUCTURE","object_type":"ROAD",'
        '"object_subtype":"ROAD_REPAIR","object_context":["REPAIR"],"work_stage":"REPAIR"},'
        '"document_research_priority":["LOCAL_ESTIMATE","SPECIFICATION"],'
        '"empty_hypothesis_status":"INSUFFICIENT_EVIDENCE","preferred_opportunity_track":null,'
        '"empty_hypothesis_reason_codes":["no_material_evidence_in_title"],'
        '"discovery_required":true,"overall_research_action":"LIGHT_RESEARCH"}\n\n'
        "REMINDER: empty hypotheses without empty_hypothesis_status is invalid.\n"
    )


def build_v6_2_prompt(
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
        return build_v6_2_prompt_from_model_input(
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
    return build_v6_2_prompt_from_model_input(
        thin,
        registry=registry,
        okpd_priors=okpd_priors,
        procurement_form_prior=procurement_form_prior,
    )
