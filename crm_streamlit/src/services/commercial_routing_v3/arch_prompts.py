"""Architecture A/B prompts — SHADOW category decomposition only.

Production remains Qwen2.5:7b + v3_category_centric_routing_7b_v5.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

PROMPT_A1 = "v3_arch_a1_semantic_extract_7b_v1"
PROMPT_A2 = "v3_arch_a2_category_only_7b_v1"
PROMPT_B_EXTRACT = "v3_arch_b_extract_7b_v1"


def build_a1_classify_prompt(*, title: str, okpd_code: str, okpd_name: str) -> str:
    """Pass A1: semantic extraction only — no commercial registry, no categories."""
    return (
        "SEMANTIC EXTRACTION ONLY for a public procurement.\n"
        f"prompt_version={PROMPT_A1}\n"
        "Do NOT emit commercial category codes.\n"
        "Do NOT receive or invent a commercial registry.\n"
        "Reply ONE JSON object with fields:\n"
        "- procurement_form: DIRECT_GOODS_PURCHASE|CONSTRUCTION_WORKS|"
        "DESIGN_AND_BUILD|DESIGN_ONLY|SURVEY_AND_DESIGN|WORKS_OTHER|SERVICES_OTHER|UNKNOWN\n"
        "- procured_items: list of short phrases for items actually purchased "
        "(empty for pure works/services)\n"
        "- explicit_goods: list of product nouns explicitly present in title/OKPD\n"
        "- object_type: GOODS|WORKS|SERVICE|STRUCTURAL_ELEMENT|UNKNOWN|null\n"
        "- object_subtype: short token or null\n"
        "- work_stage: SUPPLY|INSTALLATION|CONSTRUCTION|DESIGN|UNKNOWN|null\n"
        "- evidence_phrases: short literal phrases from title/OKPD supporting the above\n\n"
        f"title: {title}\n"
        f"okpd_code: {okpd_code}\n"
        f"okpd_name: {okpd_name}\n\n"
        "Example:\n"
        '{"procurement_form":"DIRECT_GOODS_PURCHASE","procured_items":["моноблок"],'
        '"explicit_goods":["моноблок"],"object_type":"GOODS","object_subtype":"COMPUTER",'
        '"work_stage":"SUPPLY","evidence_phrases":["Поставка моноблоков"]}'
    )


def build_a2_category_prompt(
    *,
    title: str,
    okpd_code: str,
    okpd_name: str,
    procurement_form: str,
    procured_items: List[str],
    explicit_goods: List[str],
    registry: List[Dict[str, Any]],
) -> str:
    """Pass A2: category decision only. A2_ONLY_CATEGORY_TASK=YES."""
    codes = sorted(str(c.get("category_code")) for c in registry if c.get("category_code"))
    lines = "\n".join(f"- {c}" for c in codes)
    reg_desc = "\n".join(
        f"- {c.get('category_code')}: {c.get('category_name','')}"
        for c in registry
        if c.get("category_code")
    )
    items_json = json.dumps(procured_items, ensure_ascii=False)
    goods_json = json.dumps(explicit_goods, ensure_ascii=False)
    return (
        "CATEGORY DECISION ONLY. Reply ONE JSON object.\n"
        f"prompt_version={PROMPT_A2}\n"
        "A2_ONLY_CATEGORY_TASK=YES\n"
        "Do NOT re-classify procurement_form or object.\n"
        "Do NOT use Python priors, medals, scores, or historical categories.\n\n"
        f"procurement_form (from Pass A1): {procurement_form}\n"
        f"procured_items (from Pass A1): {items_json}\n"
        f"explicit_goods (from Pass A1): {goods_json}\n"
        f"title: {title}\n"
        f"okpd_code: {okpd_code}\n"
        f"okpd_name: {okpd_name}\n\n"
        "ALLOWED_COMMERCIAL_CATEGORY_CODES:\n"
        f"{lines}\n"
        f"ACTIVE registry:\n{reg_desc}\n\n"
        "Rules:\n"
        "1) DIRECT_GOODS_PURCHASE: map purchased goods to one or more exact codes "
        "OR empty + empty_hypothesis_status=NO_COMMERCIAL_ENTRY.\n"
        "2) CONSTRUCTION_WORKS / DESIGN_* / WORKS_OTHER: emit 0–3 contextual "
        "hypotheses ONLY when a defensible semantic link exists; each must have "
        "confirmation_required=true. Empty is valid (FORCED_OBJECT_CATEGORY=NO).\n"
        "3) SERVICES_OTHER: [] + NO_COMMERCIAL_ENTRY.\n"
        "4) category_code MUST be from ALLOWED list exactly.\n"
        "5) empty list requires empty_hypothesis_status.\n\n"
        "Schema:\n"
        '{"commercial_category_hypotheses":[{"category_code":"...","opportunity_track":"DIRECT_SUPPLY",'
        '"confidence":0.7,"confirmation_required":false,"evidence_role":"DIRECT_CATEGORY_EVIDENCE",'
        '"reason_codes":["item_match"],"research_action":"LIGHT_RESEARCH",'
        '"subcategory_code":"SUBCATEGORY_NOT_ASSIGNED"}],'
        '"empty_hypothesis_status":null,"overall_research_action":"LIGHT_RESEARCH"}'
    )


def build_b_extract_prompt(*, title: str, okpd_code: str, okpd_name: str) -> str:
    return (
        "Extract procurement semantics only. Do NOT choose commercial category codes.\n"
        f"prompt_version={PROMPT_B_EXTRACT}\n"
        "Reply ONE JSON object:\n"
        "- procurement_form: DIRECT_GOODS_PURCHASE|CONSTRUCTION_WORKS|DESIGN_AND_BUILD|"
        "DESIGN_ONLY|SURVEY_AND_DESIGN|WORKS_OTHER|SERVICES_OTHER|UNKNOWN\n"
        "- procured_items: list of short product/item phrases actually purchased "
        "(empty if works/service)\n"
        "- materials: optional list of material phrases\n"
        "- object_type: short token or null\n"
        "- work_stage: short token or null\n"
        "- evidence: short phrases from title/OKPD supporting products/materials\n"
        "- is_service: true/false\n\n"
        f"title: {title}\n"
        f"okpd_code: {okpd_code}\n"
        f"okpd_name: {okpd_name}\n\n"
        "Example:\n"
        '{"procurement_form":"DIRECT_GOODS_PURCHASE","procured_items":["моноблок"],'
        '"materials":[],"object_type":"GOODS","work_stage":"SUPPLY",'
        '"evidence":["персонального настольного (моноблока)"],"is_service":false}'
    )
