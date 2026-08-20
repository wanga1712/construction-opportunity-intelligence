"""CRM Live AI Assessment Runner: Оценка и стабилизация CRM объектов."""
from __future__ import annotations
import argparse
import json
import logging
import sys
import os
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.services.commercial_routing_v3.decision_authorities import (
    qwen_candidate_inference_enabled,
    qwen_shadow_mode,
)

logger = logging.getLogger("crm_ai_assessment_runner")

LOCK_ID = 892341235612349014

_V3_SCHEMA_READINESS_CACHE: Optional[Any] = None


def should_run_legacy_ai_when_v3_enabled(use_v3_runtime: bool) -> bool:
    """Production never auto-falls back to V2. Legacy only via explicit non-prod entrypoints."""
    from src.services.commercial_routing_v3.routing_runtime_config import AUTOMATIC_V2_FALLBACK

    del use_v3_runtime
    return AUTOMATIC_V2_FALLBACK  # False

CURRENT_MODEL = "qwen2.5:7b"
CURRENT_PROMPT_VERSION = "v2a_live_prompt_v2"
CURRENT_SCHEMA_VERSION = "v2"

def get_input_fingerprint(data: Dict[str, Any]) -> str:
    from src.services.ai_assessment_runner import get_input_fingerprint
    return get_input_fingerprint(data)

def fetch_rules(tender_db) -> List[Dict[str, Any]]:
    from src.services.ai_assessment_runner import fetch_okpd_rules
    return fetch_okpd_rules(tender_db)

def fetch_medians(tender_db) -> Dict[str, Dict[str, Any]]:
    from src.services.ai_assessment_runner import fetch_cohort_medians
    return fetch_cohort_medians(tender_db)

def load_active_registry(crm_db) -> List[Dict[str, Any]]:
    cat_rows = crm_db.execute_query(
        "SELECT id, category_code, category_name FROM crm_product_categories WHERE is_active = TRUE"
    ) or []
    categories = {}
    for r in cat_rows:
        c_id = r[0] if not isinstance(r, dict) else r["id"]
        c_code = r[1] if not isinstance(r, dict) else r["category_code"]
        c_name = r[2] if not isinstance(r, dict) else r["category_name"]
        categories[c_id] = {
            "category_code": c_code,
            "category_name": c_name,
            "subcategories": []
        }
    
    sub_rows = crm_db.execute_query(
        "SELECT category_id, subcategory_code, subcategory_name FROM crm_product_subcategories WHERE is_active = TRUE"
    ) or []
    for r in sub_rows:
        cat_id = r[0] if not isinstance(r, dict) else r["category_id"]
        s_code = r[1] if not isinstance(r, dict) else r["subcategory_code"]
        s_name = r[2] if not isinstance(r, dict) else r["subcategory_name"]
        if cat_id in categories:
            categories[cat_id]["subcategories"].append({
                "subcategory_code": s_code,
                "subcategory_name": s_name
            })
    return list(categories.values())

def get_registry_hash(registry: List[Dict[str, Any]]) -> str:
    serialized = json.dumps(registry, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

def filter_registry_by_route(registry: List[Dict[str, Any]], route_profile: str) -> List[Dict[str, Any]]:
    allowed = []
    for cat in registry:
        code = cat["category_code"]
        if route_profile == "COMPUTERS_IT":
            if code == "computers":
                allowed.append(cat)
        elif route_profile == "EXCLUDED":
            pass
        else:
            if code != "computers":
                allowed.append(cat)
    return allowed

def load_approved_examples(tender_db) -> List[Dict[str, Any]]:
    rows = tender_db.execute_query(
        "SELECT input_snapshot, expected_route_profile, expected_object_type, expected_categories FROM training_examples WHERE review_status = 'APPROVED' LIMIT 10"
    ) or []
    examples = []
    for r in rows:
        inp = r[0] if not isinstance(r, dict) else r["input_snapshot"]
        route = r[1] if not isinstance(r, dict) else r["expected_route_profile"]
        obj_t = r[2] if not isinstance(r, dict) else r["expected_object_type"]
        cats = r[3] if not isinstance(r, dict) else r["expected_categories"]
        
        if isinstance(inp, str): inp = json.loads(inp)
        if isinstance(cats, str): cats = json.loads(cats)
        
        examples.append({
            "input": inp,
            "expected_route_profile": route,
            "expected_object_type": obj_t,
            "expected_categories": cats
        })
    return examples

def validate_ai_categories(ai_res: Dict[str, Any], allowed_registry: List[Dict[str, Any]]) -> Dict[str, Any]:
    valid_cats = {cat["category_code"]: [sub["subcategory_code"] for sub in cat["subcategories"]] for cat in allowed_registry}
    
    validated_expected = []
    for cat_code in ai_res.get("expected_categories", []):
        if cat_code in valid_cats:
            validated_expected.append(cat_code)
            
    validated_priorities = []
    for prio in ai_res.get("category_search_priorities", []):
        cat_code = prio.get("category_code")
        if cat_code in valid_cats:
            sub_code = prio.get("subcategory_code")
            if sub_code and sub_code not in valid_cats[cat_code]:
                prio["subcategory_code"] = ""
            
            role = prio.get("expected_role")
            if role not in ["PRIMARY_SUPPLY", "EMBEDDED_MATERIAL", "CONSUMABLE", "OBJECT_OF_RESEARCH", "AUXILIARY_CONTEXT", "ABSENT", "UNKNOWN"]:
                prio["expected_role"] = "UNKNOWN"
                
            cep = prio.get("commercial_entry_point")
            if cep not in ["DIRECT_SUPPLY", "SUPPLIER", "SUB_CONTRACTOR", "CONTRACTOR_PARTNER", "NO_ENTRY", "UNKNOWN"]:
                prio["commercial_entry_point"] = "UNKNOWN"
                
            validated_priorities.append(prio)
            
    ai_res["expected_categories"] = validated_expected
    ai_res["category_search_priorities"] = validated_priorities
    return ai_res

def build_live_prompt(item: Dict[str, Any], allowed_registry: List[Dict[str, Any]], examples: List[Dict[str, Any]]) -> str:
    registry_desc = "Допустимые категории и их подкатегории:\n"
    for cat in allowed_registry:
        sub_codes = [sub["subcategory_code"] for sub in cat["subcategories"]]
        sub_str = ", ".join(sub_codes) if sub_codes else "нет подкатегорий"
        registry_desc += f"- {cat['category_code']}: {sub_str}\n"
        
    selected_examples = []
    has_const = has_it = False
    for ex in examples:
        is_it = ex["expected_route_profile"] == "COMPUTERS_IT"
        if is_it and not has_it:
            selected_examples.append(ex)
            has_it = True
        elif not is_it and not has_const:
            selected_examples.append(ex)
            has_const = True
        if len(selected_examples) >= 2:
            break
            
    if len(selected_examples) < 2 and examples:
        selected_examples = examples[:2]

    examples_str = ""
    if selected_examples:
        examples_str = "Примеры успешной классификации:\n"
        for idx, ex in enumerate(selected_examples, 1):
            examples_str += (
                f"Пример {idx}:\n"
                f"Входные данные:\n"
                f"Название: {ex['input'].get('title')}\n"
                f"Код ОКПД2: {ex['input'].get('okpd_code')}\n"
                f"Название ОКПД2: {ex['input'].get('okpd_name')}\n"
                f"Ожидаемый ответ:\n"
                f"{json.dumps({'proposed_route_profile': ex['expected_route_profile'], 'proposed_object_type': ex['expected_object_type'], 'expected_categories': [c['category_code'] for c in ex['expected_categories']], 'category_search_priorities': ex['expected_categories']}, ensure_ascii=False)}\n\n"
            )

    return (
        "Ты — ведущий ИИ-эксперт по квалификации строительных и ИТ закупок.\n"
        "Проведи детальный анализ и классификацию закупки.\n"
        "Ответь строго в формате JSON, без markdown-разметки и пояснений.\n\n"
        "Допустимые значения proposed_route_profile:\n"
        "- CONSTRUCTION_BUILDING\n"
        "- CONSTRUCTION_INFRASTRUCTURE\n"
        "- DESIGN_ENGINEERING\n"
        "- COMPUTERS_IT\n"
        "- DIRECT_SUPPLY\n"
        "- EXCLUDED\n\n"
        "category_role для каждой категории (expected_categories):\n"
        "- PRIMARY_SUPPLY, EMBEDDED_MATERIAL, CONSUMABLE, OBJECT_OF_RESEARCH, AUXILIARY_CONTEXT, ABSENT, UNKNOWN\n"
        "Внимание: НЕ используй роль SUB_CONTRACTOR!\n\n"
        "commercial_entry_point:\n"
        "- DIRECT_SUPPLY, SUPPLIER, SUB_CONTRACTOR, CONTRACTOR_PARTNER, NO_ENTRY, UNKNOWN\n\n"
        f"{registry_desc}\n"
        f"{examples_str}\n"
        "Входные данные закупки:\n"
        f"Название: {item.get('title')}\n"
        f"Код ОКПД2: {item.get('okpd_code')}\n"
        f"Название ОКПД2: {item.get('okpd_name')}\n"
        f"Цена: {item.get('price')} руб.\n"
        f"Регион: {item.get('region')}\n"
        f"Заказчик: {item.get('customer')}\n"
        f"Закон: {item.get('law_type')}\n\n"
        "JSON schema:\n"
        "{\n"
        '  "proposed_route_profile": "CONSTRUCTION_BUILDING|CONSTRUCTION_INFRASTRUCTURE|...",\n'
        '  "object_domain": "гражданское строительство|дорожное строительство|ИТ|...",\n'
        '  "object_type": "школа|дорога|компьютеры|...",\n'
        '  "object_subtype": "капитальный ремонт|новое строительство|...",\n'
        '  "procurement_type": "строительство|проектирование|поставка|...",\n'
        '  "project_stage": "design|construction|execution|...",\n'
        '  "expected_categories": ["lighting", "flooring"],\n'
        '  "unlikely_categories": [],\n'
        '  "document_search_plan": ["проектная документация", "спецификация оборудования"],\n'
        '  "category_search_priorities": [\n'
        '    {\n'
        '      "category_code": "lighting",\n'
        '      "subcategory_code": "led_lamps",\n'
        '      "priority": 90,\n'
        '      "expected_role": "PRIMARY_SUPPLY",\n'
        '      "commercial_entry_point": "SUPPLIER",\n'
        '      "reason": "Замена светильников"\n'
        '    }\n'
        '  ],\n'
        '  "confidence": 0.90,\n'
        '  "reasons": "Обоснование классификации",\n'
        '  "reason_codes": ["okpd_match"]\n'
        "}"
    )

def fetch_candidates(tender_db, crm_db) -> List[Dict[str, Any]]:
    """Production selector — canonical evaluate_routing_eligibility only."""
    from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db
    from src.services.commercial_routing_v3.processing_lease import reclaim_stale_running
    from src.services.commercial_routing_v3.routing_eligibility import (
        LANE_ACTIVE_OPEN,
        LANE_AWARDED_ADMITTED,
        LANE_REVIEW_DISCOVERY,
        LANE_WAITING_HOLD,
        evaluate_routing_eligibility,
    )

    reclaim_stale_running(crm_db)
    try:
        priors = load_okpd_priors_from_db(crm_db)
    except Exception:
        priors = []

    query = """
        SELECT id, auction_name, okpd_code, okpd_name, initial_price,
               delivery_region, customer, source_table, source_id,
               ai_assessment_status, ai_assessment_version, ai_assessment_fingerprint,
               ai_assessment_stability, ai_stability_count, end_date, start_date, award_date,
               reassessment_requested, crm_stage, award_status, manual_override,
               coalesce(ai_routing_attempt_count, 0) AS ai_routing_attempt_count,
               ai_routing_error_class, ai_assessed_at
        FROM crm_procurements
        WHERE coalesce(manual_override, FALSE) = FALSE
    """
    rows = crm_db.execute_query(query) or []
    candidates = []
    lane_rank = {
        LANE_ACTIVE_OPEN: 0,
        LANE_WAITING_HOLD: 1,
        LANE_AWARDED_ADMITTED: 2,
        LANE_REVIEW_DISCOVERY: 3,
    }
    for r in rows:
        c = {
            "id": r["id"] if isinstance(r, dict) else r[0],
            "title": r["auction_name"] if isinstance(r, dict) else r[1],
            "auction_name": r["auction_name"] if isinstance(r, dict) else r[1],
            "okpd_code": r["okpd_code"] if isinstance(r, dict) else r[2],
            "okpd_name": r["okpd_name"] if isinstance(r, dict) else r[3],
            "price": float((r["initial_price"] if isinstance(r, dict) else r[4]) or 0),
            "initial_price": r["initial_price"] if isinstance(r, dict) else r[4],
            "region": r["delivery_region"] if isinstance(r, dict) else r[5],
            "customer": r["customer"] if isinstance(r, dict) else r[6],
            "source_table": r["source_table"] if isinstance(r, dict) else r[7],
            "source_id": r["source_id"] if isinstance(r, dict) else r[8],
            "ai_assessment_status": r["ai_assessment_status"] if isinstance(r, dict) else r[9],
            "ai_assessment_version": r["ai_assessment_version"] if isinstance(r, dict) else r[10],
            "ai_assessment_fingerprint": r["ai_assessment_fingerprint"] if isinstance(r, dict) else r[11],
            "ai_assessment_stability": r["ai_assessment_stability"] if isinstance(r, dict) else r[12],
            "ai_stability_count": r["ai_stability_count"] if isinstance(r, dict) else r[13],
            "end_date": r["end_date"] if isinstance(r, dict) else r[14],
            "start_date": r["start_date"] if isinstance(r, dict) else r[15],
            "award_date": r["award_date"] if isinstance(r, dict) else r[16],
            "reassessment_requested": r["reassessment_requested"] if isinstance(r, dict) else r[17],
            "crm_stage": r["crm_stage"] if isinstance(r, dict) else r[18],
            "award_status": r["award_status"] if isinstance(r, dict) else r[19],
            "manual_override": r["manual_override"] if isinstance(r, dict) else r[20],
            "ai_routing_attempt_count": r["ai_routing_attempt_count"] if isinstance(r, dict) else r[21],
            "ai_routing_error_class": r["ai_routing_error_class"] if isinstance(r, dict) else r[22],
            "ai_assessed_at": r["ai_assessed_at"] if isinstance(r, dict) else r[23],
        }
        st = c["source_table"] or ""
        c["law_type"] = "615_PP" if "615" in st else ("223_FZ" if "223" in st else "44_FZ")
        c["current_fingerprint"] = get_input_fingerprint(c)
        decision = evaluate_routing_eligibility(c, priors=priors, force_reassess=False)
        if not decision.selectable:
            continue
        c["routing_lane"] = decision.lane
        c["normalized_lifecycle"] = decision.normalized_lifecycle
        c["commercial_lane"] = decision.commercial_lane
        c["eligibility_reason"] = decision.reason
        c["lifecycle"] = decision.normalized_lifecycle
        c["priority_group"] = lane_rank.get(decision.lane or "", 9)
        candidates.append(c)

    from src.services.commercial_routing_v3.routing_priority import sort_lane_buckets

    # Deterministic lane preference + equal-weight category fair-share.
    return sort_lane_buckets(candidates, priors)


def ensure_v3_model_input(c: Dict[str, Any], crm_db) -> Dict[str, Any]:
    """Attach canonical_card + v3_model_input using the locked production path.

    CRM row → S7 enrich → canonical card → V3_ROUTING_MODEL_INPUT_V3.
    No reduced CRM-only prompt path.
    """
    if isinstance(c.get("v3_model_input"), dict) and c["v3_model_input"].get(
        "model_input_version"
    ):
        return c
    from src.services.commercial_routing_v3.canonical_card import build_canonical_card
    from src.services.commercial_routing_v3.model_input import (
        build_v3_routing_model_input,
        model_input_as_prompt_procurement,
        model_input_hash,
    )
    from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db
    from src.services.commercial_routing_v3.source_enrich import enrich_procurement_from_s7

    crm_id = c.get("id") or c.get("procurement_id")
    rows = crm_db.execute_query(
        "SELECT * FROM crm_procurements WHERE id = %s",
        (crm_id,),
    ) or []
    if not rows:
        return c
    full = dict(rows[0]) if isinstance(rows[0], dict) else {}
    if not full:
        return c
    full = enrich_procurement_from_s7(full)
    full["title"] = full.get("auction_name") or full.get("title") or c.get("title")
    full["price"] = float(full.get("initial_price") or c.get("price") or 0)
    full["region"] = full.get("delivery_region") or full.get("region_name") or c.get("region")
    st = full.get("source_table") or c.get("source_table") or ""
    full["law_type"] = "615_PP" if "615" in st else ("223_FZ" if "223" in st else "44_FZ")
    try:
        priors = load_okpd_priors_from_db(crm_db)
    except Exception:
        priors = []
    card = build_canonical_card(
        procurement=full, priors=priors, tender_db=None, resolve_links=True
    )
    model_input = build_v3_routing_model_input(card)
    shaped = model_input_as_prompt_procurement(model_input)
    # Preserve scheduler lane / eligibility metadata; overlay semantic fields.
    lane_meta = {
        k: c.get(k)
        for k in (
            "routing_lane",
            "commercial_lane",
            "normalized_lifecycle",
            "eligibility_reason",
            "lifecycle",
            "current_fingerprint",
            "ai_assessment_status",
            "ai_assessment_fingerprint",
            "ai_routing_attempt_count",
            "reassessment_requested",
            "force_reassess",
        )
        if k in c
    }
    c.update(full)
    c.update(shaped)
    c.update(lane_meta)
    c["id"] = crm_id
    c["canonical_card"] = card
    c["v3_model_input"] = model_input
    c["v3_model_input_hash"] = model_input_hash(model_input)
    return c


def fetch_procurement_for_controlled_reassess(crm_db, procurement_id: int) -> Optional[Dict[str, Any]]:
    """Load canonical card + V3_ROUTING_MODEL_INPUT_V3 for controlled reassess.

    Production semantic path: CRM row → S7 enrich → canonical card → model input.
    Do not pass the reduced CRM SELECT alone into the 7B prompt.
    """
    from src.services.commercial_routing_v3.canonical_card import build_canonical_card
    from src.services.commercial_routing_v3.model_input import (
        build_v3_routing_model_input,
        model_input_as_prompt_procurement,
        model_input_hash,
    )
    from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db
    from src.services.commercial_routing_v3.routing_eligibility import evaluate_routing_eligibility
    from src.services.commercial_routing_v3.source_enrich import enrich_procurement_from_s7

    rows = crm_db.execute_query(
        """
        SELECT *
        FROM crm_procurements WHERE id = %s
        """,
        (procurement_id,),
    ) or []
    if not rows:
        return None
    r = rows[0]
    c = dict(r) if isinstance(r, dict) else {}
    if not c:
        return None
    c = enrich_procurement_from_s7(c)
    c["title"] = c.get("auction_name") or c.get("title")
    c["price"] = float(c.get("initial_price") or 0)
    c["region"] = c.get("delivery_region") or c.get("region_name")
    st = c.get("source_table") or ""
    c["law_type"] = "615_PP" if "615" in st else ("223_FZ" if "223" in st else "44_FZ")
    try:
        priors = load_okpd_priors_from_db(crm_db)
    except Exception:
        priors = []
    card = build_canonical_card(
        procurement=c, priors=priors, tender_db=None, resolve_links=True
    )
    model_input = build_v3_routing_model_input(card)
    # Overlay prompt-shaped fields from model input (canonical contract).
    shaped = model_input_as_prompt_procurement(model_input)
    c.update(shaped)
    c["canonical_card"] = card
    c["v3_model_input"] = model_input
    c["v3_model_input_hash"] = model_input_hash(model_input)
    c["current_fingerprint"] = get_input_fingerprint(c)
    decision = evaluate_routing_eligibility(c, priors=priors, force_reassess=True)
    if not decision.source_valid:
        c["eligibility_blocked"] = decision.reason
        return c
    c["routing_lane"] = decision.lane
    c["normalized_lifecycle"] = decision.normalized_lifecycle or model_input.get(
        "normalized_lifecycle"
    )
    c["commercial_lane"] = decision.commercial_lane
    c["eligibility_reason"] = decision.reason
    c["lifecycle"] = c["normalized_lifecycle"]
    c["force_reassess"] = True
    return c

def fetch_candidates_for_group(crm_db, group_name: str) -> List[Dict[str, Any]]:
    query = """
        SELECT cp.id, cp.auction_name, cp.okpd_code, cp.okpd_name, cp.initial_price, 
               cp.delivery_region, cp.customer, cp.source_table, cp.source_id,
               cp.ai_assessment_status, cp.ai_assessment_version, cp.ai_assessment_fingerprint,
               cp.ai_assessment_stability, cp.ai_stability_count, cp.end_date, cp.start_date, cp.award_date,
               cp.reassessment_requested
        FROM crm_procurements cp
        JOIN quality_gate_samples q ON q.procurement_id = cp.id
        WHERE q.sample_group = %s
    """
    rows = crm_db.execute_query(query, (group_name,)) or []
    candidates = []
    for r in rows:
        c = {
            "id": r[0] if not isinstance(r, dict) else r["id"],
            "title": r[1] if not isinstance(r, dict) else r["auction_name"],
            "okpd_code": r[2] if not isinstance(r, dict) else r["okpd_code"],
            "okpd_name": r[3] if not isinstance(r, dict) else r["okpd_name"],
            "price": float(r["initial_price"] if isinstance(r, dict) else r[4]) if (r["initial_price"] if isinstance(r, dict) else r[4]) is not None else 0.0,
            "region": r[5] if not isinstance(r, dict) else r["delivery_region"],
            "customer": r[6] if not isinstance(r, dict) else r["customer"],
            "source_table": r[7] if not isinstance(r, dict) else r["source_table"],
            "source_id": r[8] if not isinstance(r, dict) else r["source_id"],
            "ai_assessment_status": r[9] if not isinstance(r, dict) else r["ai_assessment_status"],
            "ai_assessment_version": r[10] if not isinstance(r, dict) else r["ai_assessment_version"],
            "ai_assessment_fingerprint": r[11] if not isinstance(r, dict) else r["ai_assessment_fingerprint"],
            "ai_assessment_stability": r[12] if not isinstance(r, dict) else r["ai_assessment_stability"],
            "ai_stability_count": r[13] if not isinstance(r, dict) else r["ai_stability_count"],
            "end_date": r[14] if not isinstance(r, dict) else r["end_date"],
            "start_date": r[15] if not isinstance(r, dict) else r["start_date"],
            "award_date": r[16] if not isinstance(r, dict) else r["award_date"],
            "reassessment_requested": r[17] if not isinstance(r, dict) else r["reassessment_requested"]
        }
        st = c["source_table"] or ""
        c["law_type"] = "615_PP" if "615" in st else ("223_FZ" if "223" in st else "44_FZ")
        c["lifecycle"] = "AWARDED" if "awarded" in st else "OPEN"
        c["current_fingerprint"] = get_input_fingerprint(c)
        c["priority_group"] = 0
        candidates.append(c)
    return candidates

def apply_cheap_signals_first(crm_db, route_profile: str, proposed_object_type: str, auction_name: str, opportunities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Применяет registry-driven правила Cheap Signals First к списку возможностей.
    """
    try:
        rules = crm_db.execute_query(
            "SELECT category_code, positive_terms, negative_terms, applicable_routes, applicable_object_types, enabled FROM crm_category_signal_rules WHERE enabled = TRUE"
        )
    except Exception as e:
        logger.error(f"Failed to load category signal rules: {e}")
        rules = []

    rules_map = {r["category_code"]: r for r in rules}
    title = (auction_name or "").lower()

    processed = []
    for opp in opportunities:
        cat_code = opp["category_code"]
        opp_copy = dict(opp)
        
        rule = rules_map.get(cat_code)
        if rule:
            app_routes = rule.get("applicable_routes") or []
            app_objs = rule.get("applicable_object_types") or []
            
            route_matches = not app_routes or (route_profile in app_routes)
            obj_matches = not app_objs or (proposed_object_type in app_objs)
            
            if route_matches and obj_matches:
                pos_terms = rule.get("positive_terms") or []
                neg_terms = rule.get("negative_terms") or []
                
                # Ищем позитивные термины
                has_pos = not pos_terms or any(term.lower() in title for term in pos_terms)
                has_neg = any(term.lower() in title for term in neg_terms)
                
                if not has_pos:
                    opp_copy["opportunity_status"] = "POSSIBLE"
                    opp_copy["expected_volume"] = "LOW"
                    opp_copy["research_action"] = "METADATA_ONLY"
                    logger.info(f"Cheap Signals: Category {cat_code} demoted because no positive terms matched.")
                
                if has_neg:
                    opp_copy["opportunity_status"] = "ABSENT"
                    opp_copy["expected_volume"] = "LOW"
                    opp_copy["research_action"] = "SKIP"
                    logger.info(f"Cheap Signals: Category {cat_code} marked ABSENT because negative term matched.")
                    
        processed.append(opp_copy)
    return processed

def aggregate_research_action(opportunities: List[Dict[str, Any]]) -> str:
    ranks = {"DEEP_RESEARCH": 5, "PRIORITY_DOCS": 4, "LIGHT_RESEARCH": 3, "METADATA_ONLY": 2, "SKIP": 1}
    max_rank = 1
    max_action = "SKIP"
    for opp in opportunities:
        action = opp.get("research_action", "SKIP")
        rank = ranks.get(action, 1)
        if rank > max_rank:
            max_rank = rank
            max_action = action
    return max_action

def process_item(c: Dict[str, Any], rules: List[Any], medians: Dict[str, Any], registry: List[Dict[str, Any]], registry_hash: str, examples: List[Dict[str, Any]], tender_db, crm_db) -> bool:
    from src.services.ai_assessment_runner import match_okpd_rule, check_egrz_expertise, call_ollama_qwen, DEFAULT_MEDIAN_PRICES
    from src.services.candidate_policy import CandidatePolicy
    from src.services.commercial_routing_v3.routing_runtime_config import (
        MAX_ROUTING_ATTEMPTS,
        PRODUCTION_REQUIRES_V3,
        ROUTING_PROCESSING_LEASE_SEC,
        RoutingErrorClass,
        v3_runtime_enabled,
    )

    crm_id = c["id"]
    if not qwen_candidate_inference_enabled():
        logger.info("MODEL_V0 freeze: skip Qwen inference procurement_id=%s", crm_id)
        return True
    okpd, law, lifecycle = c["okpd_code"], c["law_type"], c.get("lifecycle") or c.get("normalized_lifecycle") or "OPEN"
    fp = c["current_fingerprint"]
    force = bool(c.get("force_reassess"))

    if force:
        crm_db.execute_update(
            """
            UPDATE crm_procurements
            SET ai_assessment_status = 'RUNNING',
                ai_assessed_at = NOW(),
                ai_routing_attempt_count = coalesce(ai_routing_attempt_count, 0) + 1,
                ai_routing_error_class = NULL
            WHERE id = %s
            """,
            (crm_id,),
        )
    else:
        crm_db.execute_update(
            """
            UPDATE crm_procurements
            SET ai_assessment_status = 'RUNNING',
                ai_assessed_at = NOW(),
                ai_routing_attempt_count = coalesce(ai_routing_attempt_count, 0) + 1,
                ai_routing_error_class = NULL
            WHERE id = %s
              AND (
                ai_assessment_status IN ('UNASSESSED', 'QUEUED', 'FAILED', 'STALE')
                OR coalesce(reassessment_requested, FALSE) = TRUE
                OR (
                  ai_assessment_status = 'COMPLETED'
                  AND ai_assessment_fingerprint IS DISTINCT FROM %s
                )
                OR (
                  ai_assessment_status = 'RUNNING'
                  AND (
                    ai_assessed_at IS NULL
                    OR ai_assessed_at < NOW() - (%s * INTERVAL '1 second')
                  )
                )
              )
            """,
            (crm_id, fp, ROUTING_PROCESSING_LEASE_SEC),
        )

    matched_rule = match_okpd_rule(okpd, rules, law, lifecycle)
    prefilter_res = matched_rule["prefilter_action"] if matched_rule else "AI_REQUIRED"
    route_profile = matched_rule["route_profile"] if matched_rule else "UNASSESSED"
    rules_ver = matched_rule["version"] if matched_rule else 1

    def _fail(error_class: str, *, terminal_review: bool = False) -> bool:
        attempts = int(
            crm_db.execute_scalar(
                "SELECT coalesce(ai_routing_attempt_count,0) FROM crm_procurements WHERE id=%s",
                (crm_id,),
            )
            or 0
        )
        if terminal_review:
            st = "NEEDS_REVIEW"
        elif attempts >= MAX_ROUTING_ATTEMPTS:
            st = "NEEDS_REVIEW"
            error_class = RoutingErrorClass.MAX_ATTEMPTS_EXCEEDED
        else:
            st = "FAILED"
        crm_db.execute_update(
            """
            UPDATE crm_procurements
            SET ai_assessment_status = %s,
                ai_assessed_at = NOW(),
                ai_routing_error_class = %s
            WHERE id = %s
            """,
            (st, error_class, crm_id),
        )
        return False

    try:
        # Defense-in-depth: re-check WAITING immediately before any model work.
        from src.services.commercial_routing_v3.routing_runtime_config import (
            WAITING_ROUTABLE,
        )
        from src.services.commercial_routing_v3.source_lifecycle import (
            normalize_source_lifecycle_event,
        )

        live_lc = normalize_source_lifecycle_event(
            source_table=str(c.get("source_table") or ""),
            crm_stage=str(c.get("crm_stage") or ""),
            award_status=str(c.get("award_status") or ""),
            end_date=c.get("end_date"),
        ).value
        if live_lc == "WAITING_SOURCE_OUTCOME" and not WAITING_ROUTABLE:
            logger.warning(
                "WAITING execution guard skip procurement_id=%s (no Qwen)",
                crm_id,
            )
            crm_db.execute_update(
                """
                UPDATE crm_procurements
                SET ai_assessment_status = 'UNASSESSED',
                    ai_assessed_at = NOW(),
                    ai_routing_error_class = %s,
                    ai_routing_attempt_count = GREATEST(coalesce(ai_routing_attempt_count,1) - 1, 0)
                WHERE id = %s
                """,
                ("WAITING_NOT_ROUTABLE_SKIP", crm_id),
            )
            return False

        egrz = check_egrz_expertise(tender_db, c["source_table"], c["source_id"])
        
        ai_res = None
        v3_normalized_result: Optional[Dict[str, Any]] = None
        v3_used = False
        v3_schema_ready = False
        v3_runtime_execution_allowed = False
        v3_schema_missing_components: List[str] = []
        use_v3_runtime = v3_runtime_enabled()

        # Production: V3 required; never automatic V2 fallback.
        if PRODUCTION_REQUIRES_V3 and not use_v3_runtime:
            logger.error("V3 runtime disabled — fail-closed (no V2 fallback)")
            return _fail(RoutingErrorClass.V3_DISABLED, terminal_review=True)

        if prefilter_res in ("AI_REQUIRED", "MANUAL_REVIEW"):
            try:
                from src.services.commercial_routing_v3.engine import (
                    CommercialRoutingV3Engine,
                )
                from src.services.commercial_routing_v3.runtime_adapter import (
                    decision_to_normalized_result,
                )
                from src.services.commercial_routing_v3.schema_readiness import (
                    check_v3_schema_readiness,
                    decide_v3_runtime_execution_allowed,
                )

                global _V3_SCHEMA_READINESS_CACHE
                if _V3_SCHEMA_READINESS_CACHE is None:
                    _V3_SCHEMA_READINESS_CACHE = check_v3_schema_readiness(crm_db)
                readiness = _V3_SCHEMA_READINESS_CACHE
                v3_schema_ready = bool(getattr(readiness, "ready", False))
                v3_schema_missing_components = list(
                    getattr(readiness, "missing", []) or []
                )

                allowed, _reason = decide_v3_runtime_execution_allowed(
                    feature_flag_enabled=True,
                    readiness=readiness,
                )
                v3_runtime_execution_allowed = bool(allowed)
                if not allowed:
                    logger.warning(
                        "V3 schema not ready; refusing V3 runtime execution: missing=%s",
                        v3_schema_missing_components,
                    )
                    return _fail(RoutingErrorClass.V3_NOT_READY)
                v3_engine = CommercialRoutingV3Engine(crm_db=crm_db)
                from src.services.commercial_routing_v3.model_input import (
                    model_input_as_prompt_procurement,
                )

                ensure_v3_model_input(c, crm_db)
                model_input = c.get("v3_model_input")
                if not isinstance(model_input, dict) or not model_input.get(
                    "model_input_version"
                ):
                    # Fail-closed: do not invent a reduced CRM prompt path.
                    logger.error(
                        "V3 model input missing for procurement_id=%s",
                        c.get("id") or c.get("procurement_id"),
                    )
                    return _fail(RoutingErrorClass.UNEXPECTED_EXCEPTION)
                procurement = model_input_as_prompt_procurement(model_input)
                procurement["routing_lane"] = c.get("routing_lane")
                procurement["commercial_lane"] = c.get("commercial_lane")
                procurement["normalized_lifecycle"] = (
                    model_input.get("normalized_lifecycle")
                    or c.get("normalized_lifecycle")
                    or lifecycle
                )
                # Re-check WAITING after enrich (source fields may have changed).
                enrich_lc = str(procurement.get("normalized_lifecycle") or "")
                if enrich_lc == "WAITING_SOURCE_OUTCOME" and not WAITING_ROUTABLE:
                    logger.warning(
                        "WAITING post-enrich guard skip procurement_id=%s", crm_id
                    )
                    crm_db.execute_update(
                        """
                        UPDATE crm_procurements
                        SET ai_assessment_status = 'UNASSESSED',
                            ai_assessed_at = NOW(),
                            ai_routing_error_class = %s,
                            ai_routing_attempt_count = GREATEST(coalesce(ai_routing_attempt_count,1) - 1, 0)
                        WHERE id = %s
                        """,
                        ("WAITING_NOT_ROUTABLE_SKIP", crm_id),
                    )
                    return False
                prompt = v3_engine.build_prompt_context(procurement)
                c["last_v3_prompt_chars"] = len(prompt)
                c["last_v3_model_input_json_chars"] = len(
                    __import__("json").dumps(model_input, ensure_ascii=False, default=str)
                )
                try:
                    from src.services.ai_assessment_runner import OllamaJsonParseError
                    import hashlib

                    input_hash = hashlib.sha256(
                        __import__("json")
                        .dumps(model_input, ensure_ascii=False, sort_keys=True, default=str)
                        .encode("utf-8")
                    ).hexdigest()
                    raw_ai = call_ollama_qwen(
                        prompt,
                        procurement_id=crm_id,
                        crm_db=crm_db,
                        input_hash=input_hash,
                        prompt_version="v3_routing",
                        persist_dry_run=False,
                        acquire_gpu=True,
                    )
                except OllamaJsonParseError as json_exc:
                    logger.warning("V3 Ollama JSON parse failed: %s", json_exc)
                    return _fail(RoutingErrorClass.INVALID_JSON)
                if raw_ai:
                    decision = v3_engine.route_with_ai(procurement, raw_ai)
                    v3_normalized_result = decision_to_normalized_result(
                        decision=decision, procurement=procurement
                    )
                    v3_used = True
                    rejected = list(v3_normalized_result.get("rejected_category_codes") or [])
                    empty_st = (v3_normalized_result.get("empty_hypothesis_status") or "").upper()
                    if rejected and empty_st == "REVIEW_REQUIRED":
                        return _fail(RoutingErrorClass.INVALID_CATEGORY, terminal_review=True)
                    if empty_st == "REVIEW_REQUIRED" and v3_normalized_result.get("review_required"):
                        # silent empty promoted to review — still terminal review, not COMPLETED empty
                        if not (v3_normalized_result.get("category_opportunities") or []):
                            return _fail(RoutingErrorClass.INVALID_CATEGORY, terminal_review=True)
                    if empty_st == "NO_COMMERCIAL_ENTRY":
                        pass
                    proposed_cats = [
                        o.get("category_code")
                        for o in v3_normalized_result.get("category_opportunities") or []
                        if o.get("category_code")
                    ]
                    confidence = 0.5
                    opps = v3_normalized_result.get("category_opportunities") or []
                    if opps:
                        confidence = max(
                            float(o.get("confidence") or 0.0) for o in opps
                        )
                    ai_res = {
                        "proposed_route_profile": route_profile,
                        "proposed_object_type": "unknown",
                        "proposed_procurement_type": procurement.get(
                            "procurement_form", route_profile
                        ),
                        "expected_categories": proposed_cats,
                        "confidence": confidence,
                        "reasons": "v3_routing_success",
                        "reason_codes": [],
                        "category_opportunities": opps,
                    }
                else:
                    return _fail(RoutingErrorClass.OLLAMA_TIMEOUT)
            except Exception as v3_exc:
                logger.warning("V3 runtime failed: %s", v3_exc)
                return _fail(RoutingErrorClass.UNEXPECTED_EXCEPTION)

            if ai_res is None:
                return _fail(
                    RoutingErrorClass.V3_NOT_READY
                    if not v3_runtime_execution_allowed
                    else RoutingErrorClass.UNEXPECTED_EXCEPTION
                )

            # AUTOMATIC_V2_FALLBACK is False — never call legacy here.
            if should_run_legacy_ai_when_v3_enabled(use_v3_runtime):
                logger.error("Invariant broken: legacy fallback requested")
                return _fail(RoutingErrorClass.UNEXPECTED_EXCEPTION, terminal_review=True)

        if ai_res:
            route_profile = ai_res.get("proposed_route_profile") or "UNASSESSED"
            proposed_obj = ai_res.get("proposed_object_type") or "unknown"
            proposed_proc = ai_res.get("proposed_procurement_type") or "unknown"
            proposed_cats = ai_res.get("expected_categories") or []
            confidence = float(ai_res.get("confidence") or 1.0)
            reasons = ai_res.get("reasons")
            reason_codes = ai_res.get("reason_codes") or []
            status = "SUCCESS"
        else:
            proposed_obj = proposed_proc = "строительство"
            proposed_cats = []
            confidence = 0.5
            reasons = "AI классификация не удалась (таймаут или ошибка)"
            reason_codes = ["ai_failed"]
            status = "FAILED" if prefilter_res == "AI_REQUIRED" else "SUCCESS"

        if status == "FAILED":
            return _fail(RoutingErrorClass.OLLAMA_UNAVAILABLE)

        # BUSINESS SCOPE GATE — model-explicit only. Do not infer IN_PROFILE
        # from proposed_cats / V3 discovery (those are not model scope).
        from src.services.business_scope import resolve_pipeline_scope

        download_action = "SKIP"
        business_scope_status = resolve_pipeline_scope(
            route_profile=route_profile,
            model_payload=ai_res if isinstance(ai_res, dict) else None,
        )
        category_fit = business_scope_status

        # Формируем ИИ-возможности
        cohort_key = f"{law}_{lifecycle}_{route_profile}"
        median_info = medians.get(cohort_key)
        median_price = median_info["median_price"] if median_info and median_info["cohort_size"] >= 10 else DEFAULT_MEDIAN_PRICES.get(law, DEFAULT_MEDIAN_PRICES["ALL"])

        if v3_used and v3_normalized_result:
            opps = v3_normalized_result.get("category_opportunities") or []
        else:
            opps = []
            for cat in proposed_cats:
                opp_status = "CONFIRMED_SOURCE" if confidence >= 0.7 else "POSSIBLE"
                expected_vol = (
                    "HIGH"
                    if float(c.get("price") or c.get("initial_price") or 0.0) >= median_price
                    else "MEDIUM"
                )
                opps.append(
                    {
                        "category_code": cat,
                        "subcategory_code": None,
                        "opportunity_status": opp_status,
                        "expected_role": "PRIMARY_SUPPLY",
                        "commercial_entry_point": "DIRECT_SUPPLY",
                        "expected_volume": expected_vol,
                        "confidence": confidence,
                        "priority": 1.0,
                        "research_action": "PRIORITY_DOCS"
                        if opp_status == "CONFIRMED_SOURCE"
                        else "LIGHT_RESEARCH",
                    }
                )

        # Legacy cheap-signals are allowed only for legacy V2 semantics.
        # For V3 runtime we must not reintroduce old stop-word hard skips.
        if not v3_used:
            opps = apply_cheap_signals_first(
                crm_db,
                route_profile,
                proposed_obj,
                c.get("auction_name"),
                opps,
            )
        
        # Обновленный расчет в CandidatePolicy
        ai_res_payload = {
            "confidence": confidence,
            "reasons": reasons,
            "category_opportunities": opps
        }
        policy_res = CandidatePolicy.calculate(
            route_profile, lifecycle, c, ai_res_payload, 
            median_price, egrz, business_scope_status=business_scope_status
        )
        cand_score = policy_res["candidate_score"]
        cand_level = policy_res["candidate_level"]

        # Назначаем aggregate research_action
        download_action = aggregate_research_action(policy_res.get("category_opportunities") or [])
        if business_scope_status == "OUT_OF_PROFILE":
            download_action = "SKIP"

        prev_row = crm_db.execute_query(
            "SELECT id, proposed_route_profile, proposed_object_type, proposed_procurement_type, proposed_categories, proposed_level, model_version, prompt_version, rules_version, assessment_stability, stability_count FROM procurement_ai_assessments WHERE procurement_id = %s AND is_current = TRUE ORDER BY id DESC LIMIT 1",
            (crm_id,)
        )

        stability_count = 1
        stability_status = "UNSTABLE"
        stable_since_clause = "NULL"
        changed = False
        change_fields = []
        prev_id = None

        if prev_row:
            p = prev_row[0]
            prev_id = p[0] if not isinstance(p, dict) else p["id"]
            p_route = p[1] if not isinstance(p, dict) else p["proposed_route_profile"]
            p_obj = p[2] if not isinstance(p, dict) else p["proposed_object_type"]
            p_proc = p[3] if not isinstance(p, dict) else p["proposed_procurement_type"]
            p_cats = p[4] if not isinstance(p, dict) else p["proposed_categories"]
            p_level = p[5] if not isinstance(p, dict) else p["proposed_level"]
            p_model = p[6] if not isinstance(p, dict) else p["model_version"]
            p_prompt = p[7] if not isinstance(p, dict) else p["prompt_version"]
            p_rules = p[8] if not isinstance(p, dict) else p["rules_version"]
            p_stab = p[9] if not isinstance(p, dict) else p["assessment_stability"]
            p_count = p[10] if not isinstance(p, dict) else p["stability_count"]

            if isinstance(p_cats, str):
                p_cats = json.loads(p_cats)

            versions_changed = (p_model != CURRENT_MODEL or p_prompt != CURRENT_PROMPT_VERSION or p_rules != rules_ver)
            if versions_changed:
                stability_count = 1
                stability_status = "UNSTABLE"
            else:
                sig_curr = (route_profile, proposed_obj, proposed_proc, sorted(proposed_cats), cand_level)
                sig_prev = (p_route, p_obj, p_proc, sorted(p_cats or []), p_level)

                if sig_curr == sig_prev:
                    stability_count = p_count + 1
                    if stability_count >= 3:
                        stability_status = "STABLE"
                        stable_since_clause = "NOW()"
                    else:
                        stability_status = "STABILIZING"
                else:
                    stability_count = 1
                    stability_status = "UNSTABLE"
                    changed = True
                    if p_route != route_profile: change_fields.append("route_profile")
                    if p_obj != proposed_obj: change_fields.append("object_type")
                    if p_proc != proposed_proc: change_fields.append("procurement_type")
                    if sorted(p_cats or []) != sorted(proposed_cats): change_fields.append("categories")
                    if p_level != cand_level: change_fields.append("candidate_level")

        normalized_result = {
            "route_profile": route_profile,
            "object_domain": ai_res.get("object_domain") if ai_res else "unknown",
            "object_type": proposed_obj,
            "object_subtype": ai_res.get("object_subtype") if ai_res else "unknown",
            "procurement_type": proposed_proc,
            "project_stage": ai_res.get("project_stage") if ai_res else "unknown",
            "expected_categories": proposed_cats,
            "unlikely_categories": ai_res.get("unlikely_categories") if ai_res else [],
            "document_search_plan": ai_res.get("document_search_plan") if ai_res else [],
            "category_opportunities": policy_res.get("category_opportunities") or [],
            "category_state": "CANDIDATE",
            "business_scope_status": business_scope_status,
            "category_fit": category_fit,
            "download_action": download_action,
            # V3/Discovery contract (safe for legacy as well).
            "discovery_required": bool(v3_normalized_result and v3_normalized_result.get("discovery_required")),
            "overall_research_action": (
                (v3_normalized_result.get("overall_research_action") if v3_normalized_result else None)
                or download_action
            ),
            "v3_schema_ready": v3_schema_ready,
            "v3_runtime_execution_allowed": v3_runtime_execution_allowed,
            "v3_schema_missing_components": v3_schema_missing_components,
            "registry_version": 1,
            "registry_hash": registry_hash,
            "candidate_level": cand_level,
            "candidate_score": cand_score,
            "cohort_key": cohort_key,
            "cohort_size": median_info["cohort_size"] if median_info else 0,
            "cohort_median": median_price,
            "confidence": confidence,
            "reason_codes": reason_codes,
            "normalized_summary": reasons,
            "model_version": CURRENT_MODEL,
            "prompt_version": CURRENT_PROMPT_VERSION,
            "schema_version": CURRENT_SCHEMA_VERSION,
            "rules_version": rules_ver,
            "assessment_version": (c["ai_assessment_version"] or 0) + 1,
            "assessment_changed": changed,
            "stability_count": stability_count
        }
        if v3_used and v3_normalized_result:
            for k in (
                "source_contour",
                "procurement_form",
                "analysis_mode",
                "analysis_modes",
                "object_context",
                "material_signals",
                "work_methods",
                "application_areas",
                "brands",
                "commercial_category_hypotheses",
                "registry_version",
                "registry_hash",
                "prompt_version",
                "routing_version",
                "model_name",
            ):
                if k in v3_normalized_result:
                    normalized_result[k] = v3_normalized_result[k]

        v_crm = crm_db.execute_scalar("SELECT MAX(assessment_version) FROM procurement_ai_assessments WHERE procurement_id = %s", (crm_id,))
        # S7 tender_monitor is SOURCE_DB_READONLY — never write assessments there.
        new_version = max(v_crm or 0, c.get("ai_assessment_version") or 0) + 1

        # Интеграция ручных переопределений для вычисления эффективного результата
        override_row = crm_db.execute_query(
            "SELECT business_relevance, overall_research_action FROM crm_manual_overrides WHERE procurement_id = %s",
            (crm_id,)
        )
        cat_overrides = crm_db.execute_query(
            "SELECT category_code, subcategory_code, opportunity_status, expected_role, commercial_entry_point, expected_volume, priority, research_action, manual_candidate_level FROM crm_manual_category_overrides WHERE procurement_id = %s",
            (crm_id,)
        )

        manual_exists = bool(override_row)
        if manual_exists:
            effective_relevance = override_row[0]["business_relevance"]
            effective_research_action = override_row[0]["overall_research_action"]
            
            cat_overrides_map = {co["category_code"]: co for co in cat_overrides}
            effective_opps = []
            for cat_code, co in cat_overrides_map.items():
                if co["opportunity_status"] != "ABSENT":
                    effective_opps.append({
                        "category_code": cat_code,
                        "subcategory_code": co["subcategory_code"],
                        "opportunity_status": co["opportunity_status"],
                        "expected_role": co["expected_role"],
                        "commercial_entry_point": co["commercial_entry_point"],
                        "expected_volume": co["expected_volume"],
                        "confidence": 1.0,
                        "priority": float(co["priority"] or 0.0),
                        "research_action": co["research_action"],
                        "candidate_level": co["manual_candidate_level"]
                    })
            for opp in policy_res.get("category_opportunities") or []:
                if opp["category_code"] not in cat_overrides_map:
                    effective_opps.append(opp)
                    
            level_ranks = {"GOLD": 4, "SILVER": 3, "BRONZE": 2, "WOOD": 1, None: 0}
            best_eff_level = None
            best_eff_score = None
            for opp in effective_opps:
                opp_lvl = opp.get("candidate_level")
                opp_scr = opp.get("candidate_score") or 0.0
                if level_ranks.get(opp_lvl, 0) > level_ranks.get(best_eff_level, 0):
                    best_eff_level = opp_lvl
                    best_eff_score = opp_scr
                elif level_ranks.get(opp_lvl, 0) == level_ranks.get(best_eff_level, 0) and best_eff_level is not None:
                    if opp_scr > (best_eff_score or 0.0):
                        best_eff_score = opp_scr
            effective_level = best_eff_level
            effective_score = best_eff_score
        else:
            from src.services.business_scope import effective_relevance_from_scope

            effective_relevance = effective_relevance_from_scope(business_scope_status)
            effective_research_action = download_action
            effective_level = cand_level
            effective_score = cand_score

        if effective_relevance == "OUT_OF_PROFILE":
            effective_level = None
            effective_score = None

        # S13 CRM is authoritative; S7 assessment dual-write removed (SOURCE_DB_READONLY).
        auth_id = 0
        conn_c = crm_db._connection
        crm_assessment_id: Optional[int] = None
        with conn_c:
            with conn_c.cursor() as cur:
                cur.execute("UPDATE procurement_ai_assessments SET is_current = FALSE WHERE procurement_id = %s", (crm_id,))
                cur.execute(
                    """
                    INSERT INTO procurement_ai_assessments (
                        authoritative_id, procurement_id, assessment_version, is_current, status, input_fingerprint,
                        model_version, prompt_version, rules_version, proposed_route_profile,
                        proposed_object_type, proposed_procurement_type, proposed_categories,
                        proposed_level, confidence, reasons, reason_codes, started_at, completed_at,
                        assessment_stability, stability_count, stable_since, assessment_changed,
                        previous_assessment_id, change_fields, normalized_result
                    ) VALUES (%s, %s, %s, TRUE, 'SUCCESS', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW(), %s, %s, """ + stable_since_clause + """, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        auth_id, crm_id, new_version, fp, CURRENT_MODEL, CURRENT_PROMPT_VERSION, rules_ver, route_profile,
                        proposed_obj, proposed_proc, json.dumps(proposed_cats), cand_level, confidence, reasons,
                        json.dumps(reason_codes), stability_status, stability_count, changed, prev_id,
                        json.dumps(change_fields), json.dumps(normalized_result)
                    )
                )
                row = cur.fetchone()
                crm_assessment_id = row[0] if not isinstance(row, dict) else row["id"]
                
                # Мапим effective_relevance в qualification_state
                if effective_relevance == "OUT_OF_PROFILE":
                    qual_state = "out_of_profile"
                elif effective_relevance == "UNKNOWN":
                    qual_state = "unassessed"
                else:
                    qual_state = "candidate"

                from src.services.commercial_routing_v3.opportunity_persistence import (
                    has_expert_lock,
                )

                if qwen_shadow_mode() or has_expert_lock(crm_db, crm_id):
                    cur.execute(
                        """
                        UPDATE crm_procurements SET
                            ai_assessment_status = 'COMPLETED',
                            ai_assessment_version = %s,
                            ai_assessment_fingerprint = %s,
                            ai_assessed_at = NOW(),
                            ai_assessment_stability = %s,
                            ai_stability_count = %s,
                            reassessment_requested = FALSE
                        WHERE id = %s
                        """,
                        (
                            new_version, fp, stability_status, stability_count,
                            crm_id
                        )
                    )
                else:
                    cur.execute(
                        """
                        UPDATE crm_procurements SET
                            ai_assessment_status = 'COMPLETED',
                            ai_assessment_version = %s,
                            ai_assessment_fingerprint = %s,
                            ai_assessed_at = NOW(),
                            ai_assessment_stability = %s,
                            ai_stability_count = %s,
                            reassessment_requested = FALSE,
                            qualification_state = %s,
                            commercial_score = %s,
                            manual_override = %s
                        WHERE id = %s
                        """,
                        (
                            new_version, fp, stability_status, stability_count,
                            qual_state, effective_score, manual_exists,
                            crm_id
                        )
                    )
        if v3_used:
            from src.services.commercial_routing_v3.opportunity_persistence import (
                persist_category_opportunities,
            )

            persist_dry_run = (
                os.getenv("COMMERCIAL_ROUTING_V3_PERSIST_OPPORTUNITIES_DRY_RUN", "1") == "1"
                or qwen_shadow_mode()
            )
            persist_category_opportunities(
                crm_db,
                procurement_id=crm_id,
                assessment_id=crm_assessment_id,
                normalized_result=normalized_result,
                category_opportunities=policy_res.get("category_opportunities") or [],
                dry_run=persist_dry_run,
            )
        return True
    except Exception as err:
        logger.error(f"Error processing CRM item {crm_id}: {err}")
        crm_db.execute_update(
            """
            UPDATE crm_procurements
            SET ai_assessment_status = 'FAILED',
                ai_assessed_at = NOW(),
                ai_routing_error_class = %s
            WHERE id = %s
            """,
            ("UNEXPECTED_EXCEPTION", crm_id),
        )
        return False

def run_live(
    tender_db,
    crm_db,
    limit: int = 100,
    group_name: Optional[str] = None,
    procurement_id: Optional[int] = None,
    produce_s13_queue: bool = False,
    force_reassess: bool = False,
    reassess_reason: str = "",
) -> Dict[str, Any]:
    from src.services.commercial_routing_v3.processing_lease import reclaim_stale_running

    if not qwen_candidate_inference_enabled():
        logger.warning("MODEL_V0 freeze: Qwen candidate inference disabled")
        return {"success": 0, "failed": 0, "frozen": True, "qwen_inference": False}

    reclaim_stale_running(crm_db)
    rules = fetch_rules(tender_db)
    medians = fetch_medians(tender_db)
    registry = load_active_registry(crm_db)
    registry_hash = get_registry_hash(registry)
    examples = load_approved_examples(tender_db)

    if procurement_id is not None and force_reassess:
        c = fetch_procurement_for_controlled_reassess(crm_db, procurement_id)
        if not c:
            logger.warning("force-reassess: procurement_id=%s not found", procurement_id)
            candidates = []
        elif c.get("eligibility_blocked"):
            logger.warning(
                "force-reassess blocked id=%s reason=%s",
                procurement_id,
                c.get("eligibility_blocked"),
            )
            candidates = []
        else:
            c["reassess_reason"] = reassess_reason or "controlled_reassess"
            candidates = [c]
        logger.info(
            "Controlled reassess mode: id=%s reason=%s found=%s",
            procurement_id,
            reassess_reason,
            len(candidates),
        )
    elif procurement_id is not None:
        candidates = fetch_candidates(tender_db, crm_db)
        candidates = [c for c in candidates if c["id"] == procurement_id]
        if not candidates:
            logger.warning(f"procurement_id={procurement_id} not found in candidates.")
        logger.info(f"Single-procurement mode: id={procurement_id}, found={len(candidates)}")
    elif group_name:
        candidates = fetch_candidates_for_group(crm_db, group_name)
        logger.info(f"Live AI Scheduler: Found {len(candidates)} candidates in group {group_name}.")
    else:
        candidates = fetch_candidates(tender_db, crm_db)
        from src.services.commercial_routing_v3.routing_ready import (
            allocate_production_routing_batch,
        )

        before = len(candidates)
        candidates = allocate_production_routing_batch(candidates, total=limit)
        waiting_routed = sum(
            1
            for c in candidates
            if c.get("routing_lane") == "WAITING_HOLD"
            or c.get("normalized_lifecycle") == "WAITING_SOURCE_OUTCOME"
        )
        logger.info(
            "Live AI Scheduler: backlog=%s capacity_batch=%s waiting_routed=%s",
            before,
            len(candidates),
            waiting_routed,
        )

    batch = candidates[:limit]
    success = failed = 0
    for idx, c in enumerate(batch):
        logger.info(f"[{idx+1}/{len(batch)}] Processing CRM ID {c['id']}")
        if process_item(c, rules, medians, registry, registry_hash, examples, tender_db, crm_db):
            success += 1
        else:
            failed += 1

    result: Dict[str, Any] = {"success": success, "failed": failed}

    if produce_s13_queue and success > 0 and not qwen_shadow_mode():
        try:
            from src.services.s13_v2_queue_producer import S13V2QueueProducer
            producer = S13V2QueueProducer()
            report = producer.run(
                procurement_id=procurement_id,
                dry_run=False,
            )
            result["s13_queue"] = report
            logger.info(f"S13V2QueueProducer: {report}")
        except Exception as exc:
            logger.error(f"S13V2QueueProducer error: {exc}", exc_info=True)
            result["s13_queue_error"] = str(exc)

    logger.info(f"Live AI Run finished. {result}")
    return result

def main():
    try:
        from dotenv import load_dotenv

        load_dotenv("/opt/CRM_Streamlit/.env")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="CRM Live AI Assessment Runner")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--group", type=str, default=None)
    parser.add_argument(
        "--procurement-id", type=int, default=None, dest="procurement_id",
        help="Run AI assessment for a single procurement (acceptance test mode).",
    )
    parser.add_argument(
        "--force-reassess",
        action="store_true",
        default=False,
        dest="force_reassess",
        help="Controlled reassessment for explicit --procurement-id (does not mass-queue COMPLETED).",
    )
    parser.add_argument(
        "--reason",
        type=str,
        default="",
        dest="reassess_reason",
        help="Reason for controlled reassessment (e.g. golden_canary).",
    )
    parser.add_argument(
        "--produce-s13-queue", action="store_true", default=False,
        dest="produce_s13_queue",
        help="After assessment, write task to S13_V2 document_intelligence queue.",
    )
    parser.add_argument(
        "--drain",
        action="store_true",
        default=False,
        help="Backlog drain mode: loop bounded batches until empty or --max-runtime-sec.",
    )
    parser.add_argument(
        "--max-runtime-sec",
        type=int,
        default=3600,
        dest="max_runtime_sec",
        help="Safety ceiling for --drain (seconds). Exit 0 so timer can resume quickly.",
    )
    args = parser.parse_args()

    from src.services.db_bootstrap import connect_databases
    _r, tender_db, crm_db, warn = connect_databases()
    if warn:
        logger.warning(warn)

    conn = crm_db._connection
    conn.set_session(autocommit=True)
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,))
        row = cur.fetchone()
        locked = list(row.values())[0] if isinstance(row, dict) else (row[0] if row else False)
        if not locked:
            logger.warning("Advisory lock busy. Exiting.")
            sys.exit(0)

    try:
        if args.drain and args.procurement_id is None and not args.group:
            from src.services.commercial_routing_v3.routing_backlog import (
                classify_eligible_backlog,
            )
            from src.services.commercial_routing_v3.routing_drain import run_backlog_drain
            from src.services.commercial_routing_v3.routing_ready import (
                allocate_production_routing_batch,
            )

            run_backlog_drain(
                tender_db=tender_db,
                crm_db=crm_db,
                run_live_fn=run_live,
                fetch_candidates_fn=fetch_candidates,
                classify_fn=classify_eligible_backlog,
                allocate_fn=allocate_production_routing_batch,
                batch_size=args.limit,
                max_runtime_sec=args.max_runtime_sec,
            )
        else:
            run_live(
                tender_db, crm_db,
                limit=args.limit,
                group_name=args.group,
                procurement_id=args.procurement_id,
                produce_s13_queue=args.produce_s13_queue,
                force_reassess=args.force_reassess,
                reassess_reason=args.reassess_reason,
            )
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    main()
