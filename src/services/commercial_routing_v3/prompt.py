"""V3 preliminary AI prompt builder — dynamic registry, no hardcoded categories."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

PROMPT_VERSION = "v3_category_centric_routing_7b_v5"
# Bounded generation for compact structured JSON (schema + caps).
NUM_PREDICT = 512

_CATEGORY_CODE_CONTRACT = (
    "OUTPUT CONTRACT — category_code:\n"
    "category_code may contain ONLY an active sellable commercial category_code "
    "from the supplied commercial registry.\n"
    "NEVER put into category_code: OKPD, OKPD hierarchy codes, OKPD parent/root, "
    "numeric classifier, object type, work type, material family, display label, "
    "uppercase alias, arbitrary invented category, "
    "or the sentinel NO_COMMERCIAL_ENTRY.\n"
    "OKPD is evidence/context only. Exact OKPD is NEVER itself a commercial "
    "category_code unless the live registry explicitly contains that exact string.\n"
    "For DIRECT_GOODS_PURCHASE: title + exact OKPD describe what is purchased. "
    "Do not expand to adjacent commercial categories.\n"
    "If a live registry sellable category applies, emit 1–3 hypotheses with that "
    "registry category_code (never OKPD). "
    "If no registry commercial category is applicable:\n"
    "  commercial_category_hypotheses=[]\n"
    "  empty_hypothesis_status=NO_COMMERCIAL_ENTRY\n"
    "  overall_research_action=SKIP\n"
    "Do NOT create a fake hypothesis just to represent NO_COMMERCIAL_ENTRY.\n"
    "NEGATIVE EXAMPLE — DIRECT_GOODS_PURCHASE of a product outside the sellable "
    "registry (e.g. gas meters when gas meters are not a registry category):\n"
    '{"commercial_category_hypotheses":[],'
    '"empty_hypothesis_status":"NO_COMMERCIAL_ENTRY",'
    '"overall_research_action":"SKIP"}\n'
    "POSITIVE EXAMPLE — DIRECT_GOODS lighting:\n"
    '  title: Поставка светильников; OKPD=27.40 → category_code=lighting, track=DIRECT_SUPPLY\n'
    "NEGATIVE EXAMPLE — OKPD is NOT category_code:\n"
    '  road repair OKPD=42.11 → WRONG category_code=42.11; '
    "RIGHT: category_code=drainage_water_management track=EMBEDDED_MATERIAL "
    "evidence_role=CONTEXTUAL_RESEARCH_PRIOR confirmation_required=true\n"
    "NEGATIVE EXAMPLE — uppercase alias:\n"
    '  WRONG category_code=COMPUTERS; RIGHT category_code=computers (exact registry spelling)\n'
)

_OBJECT_MODE_CONTRACT = (
    "TWO-MODE ROUTING ARCHITECTURE:\n"
    "MODE A — DIRECT_GOODS_PURCHASE:\n"
    "  Title/exact OKPD describe the purchased product. Map to ONE sellable registry "
    "category with DIRECT_SUPPLY if in registry. If product outside registry => "
    "hypotheses=[] empty_hypothesis_status=NO_COMMERCIAL_ENTRY overall_research_action=SKIP.\n"
    "  CONTEXTUAL_RESEARCH_PRIOR must not become DIRECT_SUPPLY. "
    "Do NOT expand to adjacent categories.\n"
    "MODE B — OBJECT PROCUREMENT (CONSTRUCTION_WORKS, DESIGN_*):\n"
    "  Do NOT ask only 'what product is named in title?'. Determine:\n"
    "  1) WHAT OBJECT IS THIS? 2) WORK/PROJECT STAGE? 3) Which registry categories "
    "can appear in this object? 4) Which documents must be researched?\n"
    "  Output object_classification: object_sector, object_type, object_subtype, "
    "object_context, work_stage.\n"
    "  Multiple commercial_category_hypotheses are NORMAL (up to 5). Each is an "
    "object-level Candidate hypothesis — NOT a direct purchase claim.\n"
    "  Use tracks EMBEDDED_MATERIAL / DESIGN_REQUIREMENT / DESIGN_INFLUENCE — "
    "NOT DIRECT_SUPPLY unless direct goods evidence exists.\n"
    "  For each hypothesis: evidence_role=CONTEXTUAL_RESEARCH_PRIOR or "
    "DIRECT_CATEGORY_EVIDENCE; confirmation_required=YES for contextual priors.\n"
    "  CONTEXTUAL_RESEARCH_PRIOR means: commercially plausible for this object; "
    "MUST be confirmed in project/tender documents — NOT already purchased.\n"
    "  Genuine construction/design objects with relevant registry categories must "
    "NOT use NO_COMMERCIAL_ENTRY merely because title lacks product words.\n"
    "  Output document_research_priority[] (metadata plan only; no downloads).\n"
    "  CONSTRUCTION/REPAIR: LOCAL_ESTIMATE, SPECIFICATION, BILL_OF_QUANTITIES, "
    "TECHNICAL_ASSIGNMENT, PROJECT_DOCUMENTATION, OTHER_ATTACHMENTS.\n"
    "  DESIGN: DESIGN_TECHNICAL_ASSIGNMENT, DESIGN_REQUIREMENTS, SOURCE_INPUT_DATA, "
    "EXISTING_PROJECT_DOCUMENTATION, SPECIFICATIONS_AND_ATTACHMENTS.\n"
    "NEGATIVE EXAMPLE road repair (OKPD 42.11, no product in title): NOT NCE/SKIP; "
    "emit object_classification TRANSPORT_INFRASTRUCTURE/ROAD + contextual Candidate "
    "hypotheses (drainage, curbstone, lighting, etc.) with confirmation_required=YES.\n"
)

_MAX_HYPS = 3
_MAX_REASONS = 6
_MAX_SIGNALS = 8

_CAT_HINTS: List[Tuple[str, re.Pattern[str]]] = [
    ("lighting", re.compile(r"свет|освещ|прожектор|ламп|светильн", re.I)),
    ("computers", re.compile(r"ноутбук|компьютер|моноблок|сервер|\bпк\b|рабоч(ее|их)\s+мест", re.I)),
    ("waterproofing", re.compile(r"гидроизол|кровл|мембран|рулонн", re.I)),
    ("drainage_water_management", re.compile(r"дренаж|ливнев|водоотвед|ливневк", re.I)),
    ("curbstone", re.compile(r"бордюр|бортовой\s+камень|поребрик", re.I)),
    ("composite_structures", re.compile(r"композит|стеклопласт|композитн", re.I)),
]


def _matched_prior_categories(
    procurement: Dict[str, Any],
    okpd_priors: List[Dict[str, Any]],
) -> List[str]:
    code = (procurement.get("okpd_code") or "").strip()
    out: List[str] = []
    for p in okpd_priors:
        pat = str(p.get("okpd_pattern") or "")
        if not pat:
            continue
        if code == pat or (code and code.startswith(pat)):
            cat = p.get("commercial_category_code")
            if cat and cat not in out:
                out.append(str(cat))
    return out[:12]


def _title_hint_categories(procurement: Dict[str, Any]) -> List[str]:
    blob = " ".join(
        str(procurement.get(k) or "")
        for k in ("title", "auction_name", "okpd_name")
    )
    hits: List[str] = []
    for code, rx in _CAT_HINTS:
        if rx.search(blob) and code not in hits:
            hits.append(code)
    return hits


def compact_registry_for_prompt(
    registry: List[Dict[str, Any]],
    procurement: Dict[str, Any],
    okpd_priors: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int]:
    """All live categories; subcategories only for prior/hint-supported ones."""
    prior_cats = set(_matched_prior_categories(procurement, okpd_priors))
    hint_cats = set(_title_hint_categories(procurement))
    keep_subs_for = prior_cats | hint_cats
    compact: List[Dict[str, Any]] = []
    sub_count = 0
    for cat in registry:
        item = {
            "category_code": cat.get("category_code"),
            "category_name": cat.get("category_name", ""),
            "lifecycle_state": cat.get("lifecycle_state", "ACTIVE"),
            "subcategories": [],
        }
        code = str(cat.get("category_code") or "")
        if code in keep_subs_for:
            subs = list(cat.get("subcategories") or [])
            item["subcategories"] = [
                {"subcategory_code": s.get("subcategory_code") if isinstance(s, dict) else s}
                for s in subs
            ]
            sub_count += len(item["subcategories"])
        compact.append(item)
    return compact, sub_count


def allowed_category_codes_block(registry: List[Dict[str, Any]]) -> str:
    """Compact explicit allow-list for category_code contract."""
    codes = sorted(
        str(c.get("category_code"))
        for c in registry
        if c.get("category_code")
    )
    lines = "\n".join(f"- {code}" for code in codes)
    return (
        "ALLOWED_COMMERCIAL_CATEGORY_CODES (category_code MUST be copied exactly from this list):\n"
        f"{lines}\n"
        "If no listed category applies: use empty hypotheses + empty_hypothesis_status "
        "(NO_COMMERCIAL_ENTRY for direct goods outside registry; object-mode uses contextual "
        "registry categories with confirmation_required=YES).\n"
        "Do NOT output candidate_medal or candidate_score — scoring is deterministic downstream.\n"
    )


def build_v3_prompt(
    procurement: Dict[str, Any],
    *,
    registry: List[Dict[str, Any]],
    okpd_priors: List[Dict[str, Any]],
    routing_signals: List[Dict[str, Any]],
    procurement_form_prior: str,
) -> str:
    del routing_signals  # reserved; not embedded (noise)
    model_input = procurement.get("v3_model_input")
    if isinstance(model_input, dict) and model_input.get("model_input_version"):
        return build_v3_prompt_from_model_input(
            model_input,
            registry=registry,
            okpd_priors=okpd_priors,
            procurement_form_prior=procurement_form_prior,
        )

    compact_reg, _sub_count = compact_registry_for_prompt(registry, procurement, okpd_priors)

    registry_desc = "Коммерческие категории (live). Subcategories — только prior/hint-supported:\n"
    for cat in compact_reg:
        subs = cat.get("subcategories") or []
        if subs:
            sub_str = ", ".join(
                (s["subcategory_code"] if isinstance(s, dict) else str(s)) for s in subs
            )
        else:
            sub_str = "(subcategories omitted; use SUBCATEGORY_NOT_ASSIGNED if unsure)"
        registry_desc += (
            f"- {cat['category_code']}: {cat.get('category_name', '')} "
            f"[{cat.get('lifecycle_state', 'ACTIVE')}] subs: {sub_str}\n"
        )

    priors = [p for p in okpd_priors if str(p.get("okpd_pattern", "")) in (procurement.get("okpd_code") or "")]
    if not priors:
        code = procurement.get("okpd_code") or ""
        priors = [
            p for p in okpd_priors
            if code and str(p.get("okpd_pattern", "")) and code.startswith(str(p["okpd_pattern"]))
        ]

    return (
        "Ты — эксперт коммерческой маршрутизации закупок (V3).\n"
        "Ответь ТОЛЬКО компактным JSON без markdown и без прозы.\n"
        f"prompt_version={PROMPT_VERSION}\n\n"
        "Поля семантики (разделяй строго):\n"
        "- commercial_category_code = продаваемая товарная группа (не бренд, не метод работ, не объект)\n"
        "- commercial_subcategory_code = уточнение товара ИЛИ строка SUBCATEGORY_NOT_ASSIGNED\n"
        "- material_family / work_method / application_area / object_context / brands — отдельные массивы, НЕ category\n"
        "- opportunity_track = сценарий входа, НЕ subcategory\n"
        "- Do NOT output candidate_medal or candidate_score in JSON.\n\n"
        "procurement_form — классифицируй по title + okpd_code + okpd_name + контексту.\n"
        "НЕ выводи form только из OKPD. Допустимые значения:\n"
        "DIRECT_GOODS_PURCHASE | CONSTRUCTION_WORKS | DESIGN_AND_BUILD | "
        "DESIGN_EXPERTISE_AND_BUILD | DESIGN_ONLY | SURVEY_AND_DESIGN | "
        "WORKS_OTHER | SERVICES_OTHER | UNKNOWN\n\n"
        "Жёсткие правила opportunity_track:\n"
        "1) DIRECT_GOODS_PURCHASE + sellable product → DIRECT_SUPPLY\n"
        "2) CONSTRUCTION_WORKS / WORKS_* где наш материал в объёме работ → EMBEDDED_MATERIAL\n"
        "3) DESIGN_*/SURVEY_AND_DESIGN где продукт задаётся в будущем проекте → DESIGN_REQUIREMENT\n"
        "4) DESIGN_*/SURVEY_AND_DESIGN где цель — влиять на будущую спецификацию → DESIGN_INFLUENCE\n"
        "5) NO_COMMERCIAL_ENTRY только если нет правдоподобного коммерческого входа\n"
        "6) UNKNOWN если evidence недостаточно\n"
        "Критично: упоминание товара/материала в construction НЕ означает DIRECT_SUPPLY.\n"
        "Критично: упоминание товара/материала в design/PIR НЕ означает DIRECT_SUPPLY.\n"
        "Для CONSTRUCTION_WORKS запрещён opportunity_track=DIRECT_SUPPLY.\n"
        "Для DESIGN_ONLY/SURVEY_AND_DESIGN запрещён opportunity_track=DIRECT_SUPPLY.\n\n"
        "commercial_category_hypotheses (<=3):\n"
        "A) есть sellable category → гипотеза с category + track + subcategory_code|SUBCATEGORY_NOT_ASSIGNED\n"
        "B) category правдоподобна, evidence неполный → гипотеза + research_action учитывающий REVIEW\n"
        "C) информации мало → empty_hypothesis_status=INSUFFICIENT_EVIDENCE|REVIEW_REQUIRED "
        "+ preferred_opportunity_track + reason_codes\n"
        "D) реально нет входа → hypotheses=[] + empty_hypothesis_status=NO_COMMERCIAL_ENTRY "
        "+ overall_research_action=SKIP. Не клади OKPD/NCE в category_code.\n"
        "ЗАПРЕЩЕНО: пустой hypotheses без empty_hypothesis_status (silent empty = invalid).\n"
        f"{_CATEGORY_CODE_CONTRACT}"
        "Не выдумывай category без опоры на title/okpd_name/контекст. Priors не whitelist: "
        "можешь выбрать любую live category вне prior, если evidence есть.\n"
        "Если OKPD отсутствует — reason_code okpd_match запрещён.\n\n"
        "Лимиты массивов: hypotheses<=3, reason_codes<=6/hyp, "
        "material_signals|work_methods|application_areas|brands|object_context <=8.\n\n"
        f"Heuristic procurement_form prior (не догма): {procurement_form_prior}\n\n"
        f"{allowed_category_codes_block(registry)}\n"
        f"{registry_desc}\n"
        f"OKPD priors (подсказки, не whitelist):\n{json.dumps(priors[:20], ensure_ascii=False, default=str)}\n\n"
        "Вход:\n"
        f"title: {procurement.get('title')}\n"
        f"okpd_code: {procurement.get('okpd_code')}\n"
        f"okpd_name: {procurement.get('okpd_name')}\n"
        f"price: {procurement.get('price')}\n"
        f"customer: {procurement.get('customer')}\n"
        f"law_type: {procurement.get('law_type')}\n"
        f"source_table: {procurement.get('source_table')}\n"
        f"region: {procurement.get('region')}\n\n"
        "JSON schema (пример структуры; НЕ копируй category/track из примера):\n"
        "{\n"
        '  "source_contour": "PUBLIC_44FZ|CORPORATE_223FZ|UNKNOWN",\n'
        '  "procurement_form": "...",\n'
        '  "analysis_modes": ["DIRECT_PRODUCT|EMBEDDED_MATERIAL_DISCOVERY|FUTURE_REQUIREMENT_DISCOVERY|GENERAL_DISCOVERY"],\n'
        '  "object_context": [],\n'
        '  "material_signals": [],\n'
        '  "work_methods": [],\n'
        '  "application_areas": [],\n'
        '  "brands": [],\n'
        '  "commercial_category_hypotheses": [],\n'
        '  "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY|INSUFFICIENT_EVIDENCE|REVIEW_REQUIRED|null",\n'
        '  "preferred_opportunity_track": null,\n'
        '  "empty_hypothesis_reason_codes": [],\n'
        '  "discovery_required": false,\n'
        '  "overall_research_action": "SKIP|METADATA_ONLY|LIGHT_RESEARCH|PRIORITY_DOCS|DEEP_RESEARCH"\n'
        "}"
    )


def build_v3_prompt_from_model_input(
    model_input: Dict[str, Any],
    *,
    registry: List[Dict[str, Any]],
    okpd_priors: List[Dict[str, Any]],
    procurement_form_prior: str,
) -> str:
    """Prompt built from frozen V3_ROUTING_MODEL_INPUT_V3 only (no CRM row dump)."""
    from src.services.commercial_routing_v3.model_input import (
        model_input_as_prompt_procurement,
        model_input_json,
    )

    procurement = model_input_as_prompt_procurement(model_input)
    compact_reg, _ = compact_registry_for_prompt(registry, procurement, okpd_priors)
    registry_desc = "Коммерческие категории (live). Subcategories — только prior/hint-supported:\n"
    for cat in compact_reg:
        subs = cat.get("subcategories") or []
        if subs:
            sub_str = ", ".join(
                (s["subcategory_code"] if isinstance(s, dict) else str(s)) for s in subs
            )
        else:
            sub_str = "(subcategories omitted; use SUBCATEGORY_NOT_ASSIGNED if unsure)"
        registry_desc += (
            f"- {cat['category_code']}: {cat.get('category_name', '')} "
            f"[{cat.get('lifecycle_state', 'ACTIVE')}] subs: {sub_str}\n"
        )

    mi_json = model_input_json(model_input)
    return (
        "Ты — эксперт коммерческой маршрутизации закупок (V3).\n"
        "Ответь ТОЛЬКО компактным JSON без markdown и без прозы.\n"
        f"prompt_version={PROMPT_VERSION}\n"
        f"model_input_version={model_input.get('model_input_version')}\n\n"
        "PRIOR SEMANTICS (обязательно различай):\n"
        "COMMERCIAL_PRODUCT_PRIOR = прямое коммерческое product-evidence/prior.\n"
        "CONTEXTUAL_RESEARCH_PRIOR = search this object/context for the category. "
        "It does NOT mean the purchased product is this category.\n"
        "Для DIRECT_GOODS_PURCHASE: NEVER convert CONTEXTUAL_RESEARCH_PRIOR into "
        "DIRECT_SUPPLY. Identify the exact purchased product. If it is not an "
        "allowed sellable category → NO_COMMERCIAL_ENTRY or REVIEW. "
        "Do not add adjacent categories.\n"
        "Для OKPD 27.32 cable/wire: contextual cable-support/tray НЕ означает "
        "cable_support_systems / composite_cable_trays без явного product evidence.\n"
        "Broad works OKPD (41/42/43) → lighting/drainage/waterproofing/etc. обычно "
        "CONTEXTUAL_RESEARCH_PRIOR, не прямой товар.\n\n"
        "Поля семантики (разделяй строго):\n"
        "- commercial_category_code = продаваемая товарная группа\n"
        "- commercial_subcategory_code = уточнение ИЛИ SUBCATEGORY_NOT_ASSIGNED\n"
        "- opportunity_track = сценарий входа, НЕ subcategory\n"
        "- start/end = период процедуры; delivery_start/end = период поставки/работ — НЕ смешивай\n\n"
        "procurement_form — по title + exact OKPD + контексту. НЕ только из OKPD.\n"
        "Допустимые form: DIRECT_GOODS_PURCHASE | CONSTRUCTION_WORKS | DESIGN_AND_BUILD | "
        "DESIGN_EXPERTISE_AND_BUILD | DESIGN_ONLY | SURVEY_AND_DESIGN | "
        "WORKS_OTHER | SERVICES_OTHER | UNKNOWN\n\n"
        "Tracks: DIRECT_SUPPLY | EMBEDDED_MATERIAL | DESIGN_REQUIREMENT | DESIGN_INFLUENCE | "
        "NO_COMMERCIAL_ENTRY | UNKNOWN\n"
        "Для CONSTRUCTION_WORKS и DESIGN_ONLY/SURVEY_AND_DESIGN запрещён DIRECT_SUPPLY.\n"
        "hypotheses<=3; silent empty без empty_hypothesis_status запрещён.\n"
        f"{_CATEGORY_CODE_CONTRACT}\n"
        f"{_OBJECT_MODE_CONTRACT}\n"
        f"Heuristic procurement_form prior (не догма): {procurement_form_prior}\n\n"
        f"{allowed_category_codes_block(registry)}\n"
        f"{registry_desc}\n"
        "V3_ROUTING_MODEL_INPUT_V3 (единственный бизнес-вход; без URL-blob/document dump):\n"
        f"{mi_json}\n\n"
        "JSON schema (структура; НЕ копируй category/track из примера):\n"
        '{"source_contour":"...","procurement_form":"...","analysis_modes":[],'
        '"object_context":[],"material_signals":[],"work_methods":[],'
        '"application_areas":[],"brands":[],'
        '"commercial_category_hypotheses":[],'
        '"object_classification":{"object_sector":"...","object_type":"...",'
        '"object_subtype":"...","object_context":[],"work_stage":"..."},'
        '"document_research_priority":[],'
        '"empty_hypothesis_status":null,'
        '"preferred_opportunity_track":null,'
        '"empty_hypothesis_reason_codes":[],"discovery_required":true,'
        '"overall_research_action":"LIGHT_RESEARCH|PRIORITY_DOCS|SKIP"}'
    )


def prompt_subcategory_count(
    registry: List[Dict[str, Any]],
    procurement: Dict[str, Any],
    okpd_priors: List[Dict[str, Any]],
) -> int:
    _, n = compact_registry_for_prompt(registry, procurement, okpd_priors)
    return n
