"""Phase 9 SHADOW prompt — full ACTIVE registry + subject interpretation.

Production default remains prompt.py v5. This module is SHADOW-only.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from src.services.commercial_routing_v3.registry_prompt_payload import (
    PROMPT_REGISTRY_PAYLOAD_VERSION,
    SUBCATEGORY_ARCHITECTURE,
    build_active_registry_payload,
    registry_payload_json,
)

PROMPT_VERSION = "v3_full_registry_research_priority_7b_v9"
NUM_PREDICT = 768

_FORMS = (
    "DIRECT_GOODS_PURCHASE | CONSTRUCTION_WORKS | DESIGN_AND_BUILD | "
    "DESIGN_EXPERTISE_AND_BUILD | DESIGN_ONLY | SURVEY_AND_DESIGN | "
    "WORKS_OTHER | SERVICES_OTHER | UNKNOWN"
)

_PRIORITIES = "HIGH | MEDIUM | LOW"


def build_v9_prompt_from_model_input(
    model_input: Dict[str, Any],
    *,
    registry: Sequence[Dict[str, Any]],
    okpd_priors: List[Dict[str, Any]],
    procurement_form_prior: str,
    extra_shadow_categories: Optional[Sequence[Dict[str, Any]]] = None,
) -> str:
    payload, codes = build_active_registry_payload(
        registry,
        extra_shadow_categories=extra_shadow_categories,
        include_subcategories=False,
    )
    codes_block = "\n".join(f"- {c}" for c in codes)
    payload_json = registry_payload_json(payload)

    code = ""
    okpd_codes = model_input.get("okpd_codes") or []
    if okpd_codes:
        code = str(okpd_codes[0] or "")
    priors = [
        {
            "category": p.get("commercial_category_code") or p.get("category"),
            "okpd_pattern": p.get("okpd_pattern"),
            "prior_kind": p.get("prior_kind") or p.get("evidence_role"),
        }
        for p in okpd_priors
        if code
        and str(p.get("okpd_pattern") or "")
        and (
            code == str(p["okpd_pattern"])
            or code.startswith(str(p["okpd_pattern"]))
        )
    ][:12]

    mi_json = json.dumps(model_input, ensure_ascii=False, default=str)

    return (
        "You are a commercial routing expert for public procurements (V3 Phase 9).\n"
        "Reply with ONE compact JSON object only. No markdown. No prose.\n"
        f"prompt_version={PROMPT_VERSION}\n"
        f"registry_payload_version={PROMPT_REGISTRY_PAYLOAD_VERSION}\n"
        f"subcategory_architecture={SUBCATEGORY_ARCHITECTURE}\n"
        f"model_input_version={model_input.get('model_input_version')}\n\n"
        "AUTHORITIES (keep separate):\n"
        "1) subject_interpretation = what is actually being procured/built (semantic).\n"
        "2) commercial_category_candidates = ACTIVE registry codes worth researching "
        "(taxonomy selection). category_code MUST be copied exactly from "
        "ALLOWED_COMMERCIAL_CATEGORY_CODES.\n"
        "3) document_research_priority = plan only; you do NOT see document contents.\n"
        "4) Do NOT output candidate_medal, candidate_score, or business score.\n\n"
        "DECISION ORDER:\n"
        "A) Set procurement_form (ONE token from allowed list).\n"
        "B) Fill subject_interpretation BEFORE choosing registry codes.\n"
        "   - DIRECT goods: subject_type=GOODS + normalized_subject in Russian "
        "(short literal product phrase from title/OKPD).\n"
        "   - Construction/design: subject_type=OBJECT_WORKS + object_type + work_stage.\n"
        "   - Services outside sellable goods: subject_type=SERVICE.\n"
        "C) Select ZERO or more commercial_category_candidates from the FULL ACTIVE "
        "registry below. Priors/hints are optional evidence only — they must NOT "
        "restrict which codes you may choose.\n"
        "D) DIRECT_GOODS_PURCHASE: if title/OKPD clearly name a sellable registry "
        "product → candidate_role=DIRECT_PURCHASE, confirmation_required=false, "
        "research_priority=HIGH|MEDIUM, evidence_role=DIRECT_CATEGORY_EVIDENCE.\n"
        "   If product is outside registry → candidates=[] and "
        "empty_hypothesis_status=NO_COMMERCIAL_ENTRY, overall_research_action=SKIP.\n"
        "E) OBJECT modes (CONSTRUCTION_WORKS / DESIGN_*): candidates are RESEARCH "
        "CANDIDATES only (not document-confirmed). Use candidate_role=RESEARCH_CANDIDATE, "
        "confirmation_required=true, evidence_role=CONTEXTUAL_RESEARCH_CANDIDATE, "
        "research_priority=HIGH|MEDIUM|LOW. Emit ZERO candidates when no registry "
        "category has a defensible link — do NOT invent generic construction spam.\n"
        "F) If candidates=[] then empty_hypothesis_status MUST be one of "
        "NO_COMMERCIAL_ENTRY|INSUFFICIENT_EVIDENCE|REVIEW_REQUIRED.\n"
        "G) overall_research_action ONE of SKIP|METADATA_ONLY|LIGHT_RESEARCH|"
        "PRIORITY_DOCS|DEEP_RESEARCH.\n"
        "H) document_research_priority may list document type tokens only "
        "(LOCAL_ESTIMATE, BILL_OF_QUANTITIES, SPECIFICATION, TECHNICAL_ASSIGNMENT, "
        "PROJECT_DOCUMENTATION, OTHER_ATTACHMENTS, DESIGN_TECHNICAL_ASSIGNMENT, "
        "DESIGN_REQUIREMENTS, SOURCE_INPUT_DATA, EXISTING_PROJECT_DOCUMENTATION, "
        "SPECIFICATIONS_AND_ATTACHMENTS). This is NOT evidence.\n\n"
        f"Allowed procurement_form values: {_FORMS}\n"
        f"research_priority values: {_PRIORITIES}\n"
        "Heuristic form prior (not dogma): "
        f"{procurement_form_prior}\n\n"
        "ALLOWED_COMMERCIAL_CATEGORY_CODES (copy exactly; never invent):\n"
        f"{codes_block}\n\n"
        "FULL_ACTIVE_COMMERCIAL_REGISTRY (data-driven; newly ACTIVE codes appear "
        "automatically):\n"
        f"{payload_json}\n\n"
        "OKPD/title priors are HINTS only (not answers; do not restrict registry):\n"
        f"{json.dumps(priors, ensure_ascii=False, default=str)}\n\n"
        "INPUT (V3_ROUTING_MODEL_INPUT_V3):\n"
        f"{mi_json}\n\n"
        "OUTPUT SHAPE EXAMPLE (DIRECT goods):\n"
        '{"procurement_form":"DIRECT_GOODS_PURCHASE",'
        '"subject_interpretation":{"subject_type":"GOODS",'
        '"normalized_subject":"персональный настольный компьютер / моноблок"},'
        '"commercial_category_candidates":[{'
        '"category_code":"computers","candidate_role":"DIRECT_PURCHASE",'
        '"research_priority":"HIGH","confirmation_required":false,'
        '"evidence_role":"DIRECT_CATEGORY_EVIDENCE",'
        '"opportunity_track":"DIRECT_SUPPLY","confidence":0.8,'
        '"reason_codes":["title_product_match"]}],'
        '"commercial_category_hypotheses":[],'
        '"object_classification":{"object_type":"GOODS","object_subtype":"COMPUTER",'
        '"work_stage":"SUPPLY","object_sector":"SUPPLY","object_context":[]},'
        '"document_research_priority":[],'
        '"empty_hypothesis_status":null,"overall_research_action":"LIGHT_RESEARCH",'
        '"discovery_required":false,"analysis_modes":["DIRECT_PRODUCT"],'
        '"material_signals":[],"work_methods":[],"application_areas":[],"brands":[],'
        '"object_context":[],"preferred_opportunity_track":null,'
        '"empty_hypothesis_reason_codes":[]}\n\n'
        "OUTPUT SHAPE EXAMPLE (OBJECT research candidates; may be empty):\n"
        '{"procurement_form":"CONSTRUCTION_WORKS",'
        '"subject_interpretation":{"subject_type":"OBJECT_WORKS",'
        '"object_type":"ROAD","work_stage":"REPAIR","normalized_subject":'
        '"ремонт автомобильной дороги"},'
        '"commercial_category_candidates":[],'
        '"commercial_category_hypotheses":[],'
        '"object_classification":{"object_type":"ROAD","object_subtype":"ROAD_REPAIR",'
        '"work_stage":"REPAIR","object_sector":"TRANSPORT_INFRASTRUCTURE",'
        '"object_context":["REPAIR"]},'
        '"document_research_priority":["LOCAL_ESTIMATE","SPECIFICATION"],'
        '"empty_hypothesis_status":"INSUFFICIENT_EVIDENCE",'
        '"overall_research_action":"LIGHT_RESEARCH","discovery_required":true,'
        '"analysis_modes":["EMBEDDED_MATERIAL_DISCOVERY"],'
        '"material_signals":[],"work_methods":[],"application_areas":[],"brands":[],'
        '"object_context":[],"preferred_opportunity_track":null,'
        '"empty_hypothesis_reason_codes":["no_defensible_registry_link"]}\n'
    )


def build_v9_prompt(
    procurement: Dict[str, Any],
    *,
    registry: List[Dict[str, Any]],
    okpd_priors: List[Dict[str, Any]],
    routing_signals: List[Dict[str, Any]],
    procurement_form_prior: str,
    extra_shadow_categories: Optional[Sequence[Dict[str, Any]]] = None,
) -> str:
    del routing_signals
    model_input = procurement.get("v3_model_input")
    if isinstance(model_input, dict) and model_input.get("model_input_version"):
        return build_v9_prompt_from_model_input(
            model_input,
            registry=registry,
            okpd_priors=okpd_priors,
            procurement_form_prior=procurement_form_prior,
            extra_shadow_categories=extra_shadow_categories,
        )
    thin = {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "title": procurement.get("title") or procurement.get("auction_name"),
        "okpd_codes": [procurement.get("okpd_code")] if procurement.get("okpd_code") else [],
        "okpd_names": [procurement.get("okpd_name")] if procurement.get("okpd_name") else [],
        "COMMERCIAL_PRODUCT_PRIORS": procurement.get("COMMERCIAL_PRODUCT_PRIORS") or [],
        "CONTEXTUAL_RESEARCH_PRIORS": procurement.get("CONTEXTUAL_RESEARCH_PRIORS") or [],
        "DIRECT_CABLE_EXPECTED_RESULT": procurement.get("DIRECT_CABLE_EXPECTED_RESULT"),
        "document_link_count": procurement.get("document_link_count"),
        "unique_document_count": procurement.get("unique_document_count"),
    }
    return build_v9_prompt_from_model_input(
        thin,
        registry=registry,
        okpd_priors=okpd_priors,
        procurement_form_prior=procurement_form_prior,
        extra_shadow_categories=extra_shadow_categories,
    )
