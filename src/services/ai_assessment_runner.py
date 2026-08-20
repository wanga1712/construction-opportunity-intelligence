"""V2A Background AI Runner (Queue Shadow & CRM Live AI Projection).

Запускается по таймеру раз в 1 час.
Режимы работы:
1. --mode shadow: обход source-реестров и запись в queue_policy_shadow_results.
2. --mode live: AI-оценка готовых объектов crm_procurements в CRM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ai_assessment_runner")

# Advisory lock константа для защиты от параллельных запусков раннера
RUNNER_LOCK_ID = 892341235612349013

# Таймаут вызова Ollama (7B large prompt on GTX 1660 often exceeds 180s)
AI_TIMEOUT = float(os.getenv("CRM_AI_TIMEOUT", "600"))


# Глобальные fallback-медианы цен по законам (в рублях)
DEFAULT_MEDIAN_PRICES = {
    "44_FZ": 5000000.0,
    "223_FZ": 10000000.0,
    "615_PP": 15000000.0,
    "ALL": 7000000.0
}

def get_input_fingerprint(data: Dict[str, Any]) -> str:
    """Вычисляет хэш входных полей для детектирования изменений."""
    parts = [
        str(data.get("title") or ""),
        str(data.get("description") or ""),
        str(data.get("okpd_code") or ""),
        str(data.get("price") or ""),
        str(data.get("region") or ""),
        str(data.get("customer") or ""),
        str(data.get("law_type") or ""),
        str(data.get("lifecycle") or "")
    ]
    input_str = "|".join(parts)
    return hashlib.sha256(input_str.encode("utf-8")).hexdigest()

def match_okpd_rule(okpd_code: Optional[str], rules: List[Dict[str, Any]], law_scope: str, lifecycle_scope: str) -> Optional[Dict[str, Any]]:
    """Находит наиболее подходящее правило ОКПД на основе exact/prefix совпадений."""
    if not okpd_code:
        return None
        
    code_str = str(okpd_code).strip()
    
    # Фильтруем правила по law/lifecycle
    valid_rules = []
    for r in rules:
        if r["law_scope"] != "ALL" and r["law_scope"] != law_scope:
            continue
        if r["lifecycle_scope"] != "ALL" and r["lifecycle_scope"] != lifecycle_scope:
            continue
        valid_rules.append(r)

    # 1. Сначала ищем точное совпадение (EXACT)
    for r in valid_rules:
        if r["match_mode"] == "EXACT" and r["okpd_code"] == code_str:
            return r

    # 2. Ищем префиксное совпадение (PREFIX) от самых длинных к коротким
    matched_prefixes = []
    for r in valid_rules:
        if r["match_mode"] == "PREFIX":
            prefix = r["okpd_code"].rstrip(".")
            if code_str.startswith(prefix):
                matched_prefixes.append((len(prefix), r))
                
    if matched_prefixes:
        # Сортируем по длине префикса (по убыванию)
        matched_prefixes.sort(key=lambda x: x[0], reverse=True)
        return matched_prefixes[0][1]

    return None

def fetch_okpd_rules(tender_db) -> List[Dict[str, Any]]:
    """Load active OKPD route rules from tender_monitor (or CRM projection).

    Tender schema uses ``rule_key`` + ``version``; CRM read-projection uses
    ``authoritative_rule_key`` + ``authoritative_version``. Detect columns so
    callers can pass either DB without crashing.
    """
    col_rows = tender_db.execute_query(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'okpd_route_profiles'
        """
    ) or []
    cols = {
        (r[0] if not isinstance(r, dict) else r["column_name"])
        for r in col_rows
    }
    if "rule_key" in cols:
        rule_key_expr = "rule_key"
        version_expr = "version"
    elif "authoritative_rule_key" in cols:
        rule_key_expr = "authoritative_rule_key AS rule_key"
        version_expr = "authoritative_version AS version"
    else:
        return []

    rows = tender_db.execute_query(
        f"""
        SELECT
            id, {rule_key_expr}, okpd_code, match_mode, okpd_name,
            route_profile, prefilter_action, priority_weight,
            category_candidates, document_policy, law_scope,
            lifecycle_scope, region_scope, {version_expr}
        FROM okpd_route_profiles
        WHERE is_current = TRUE AND enabled = TRUE
        """
    ) or []

    def _cell(row, key, idx):
        if isinstance(row, dict):
            return row.get(key)
        return row[idx]

    rules = []
    for r in rows:
        pw = _cell(r, "priority_weight", 7)
        cats = _cell(r, "category_candidates", 8)
        rules.append({
            "id": _cell(r, "id", 0),
            "rule_key": _cell(r, "rule_key", 1),
            "okpd_code": _cell(r, "okpd_code", 2),
            "match_mode": _cell(r, "match_mode", 3),
            "okpd_name": _cell(r, "okpd_name", 4),
            "route_profile": _cell(r, "route_profile", 5),
            "prefilter_action": _cell(r, "prefilter_action", 6),
            "priority_weight": float(pw) if pw is not None else 1.0,
            "category_candidates": cats if isinstance(cats, list) else [],
            "document_policy": _cell(r, "document_policy", 9),
            "law_scope": _cell(r, "law_scope", 10),
            "lifecycle_scope": _cell(r, "lifecycle_scope", 11),
            "region_scope": _cell(r, "region_scope", 12),
            "version": _cell(r, "version", 13),
        })
    return rules

def fetch_cohort_medians(tender_db) -> Dict[str, Dict[str, Any]]:
    """Выгружает текущие когортные медианы."""
    rows = tender_db.execute_query(
        "SELECT cohort_key, median_price, median_duration_days, cohort_size FROM cohort_medians WHERE is_current = TRUE"
    ) or []
    
    medians = {}
    for r in rows:
        medians[r[0]] = {
            "median_price": float(r[1]) if r[1] is not None else 0.0,
            "median_duration_days": r[2],
            "cohort_size": r[3]
        }
    return medians

def check_egrz_expertise(tender_db, table_source: str, source_id: int) -> Dict[str, Any]:
    """Проверяет ЕГРЗ-заключение для закупки."""
    row = tender_db.execute_query(
        """
        SELECT id, score 
        FROM expertise_tender_window_score 
        WHERE matched_tender_table = %s AND matched_tender_id = %s
        LIMIT 1
        """,
        (table_source, source_id)
    )
    if row:
        r = row[0]
        # В RealDictCursor или обычном кортеже распаковываем безопасно
        r_id = list(r.values())[0] if isinstance(r, dict) else r[0]
        score = list(r.values())[1] if isinstance(r, dict) else r[1]
        
        confidence = float(score) if score is not None else 1.0
        if score is not None and score > 1.0:
            confidence = float(score) / 100.0
        confidence = min(max(confidence, 0.0), 1.0)
        
        return {
            "status": "YES",
            "source": "expertise_tender_window_score",
            "record_id": str(r_id),
            "match_method": "score_match",
            "match_confidence": confidence
        }
    return {
        "status": "UNKNOWN",
        "source": None,
        "record_id": None,
        "match_method": None,
        "match_confidence": 0.0
    }

class OllamaJsonParseError(ValueError):
    """Model returned text that is not a JSON object — not a transport timeout."""


def call_ollama_qwen(
    prompt: str,
    *,
    procurement_id: Any = None,
    crm_db: Any = None,
    input_hash: str | None = None,
    prompt_version: str | None = None,
    persist_dry_run: bool = False,
    acquire_gpu: bool = True,
) -> Optional[Dict[str, Any]]:
    """Production V3 path: qwen2.5:7b + structured JSON + bounded retry (locked stack).

    Returns None only for transport/timeouts/unavailable.
    Raises OllamaJsonParseError when all attempts fail JSON extraction
    (must NOT be labeled OLLAMA_TIMEOUT).
    Persists attempt_history to crm_v3_inference_attempts when crm_db is set.
    """
    from datetime import datetime, timezone

    from src.services.ai_client import generate_v3_routing_with_bounded_retry
    from src.services.commercial_routing_v3.gpu_arbiter import (
        WORKLOAD_ROUTING,
        acquire_gpu_inference,
    )
    from src.services.commercial_routing_v3.model_json import ModelInferenceFormatFailed
    from src.services.commercial_routing_v3.opportunity_persistence import (
        persist_inference_attempt,
    )

    def _persist(state: Dict[str, Any]) -> None:
        if crm_db is None or procurement_id is None:
            return
        try:
            persist_inference_attempt(crm_db, state, dry_run=persist_dry_run)
        except Exception as exc:
            logger.error("persist_inference_attempt failed: %s", exc)

    def _run():
        return generate_v3_routing_with_bounded_retry(
            prompt,
            timeout=int(AI_TIMEOUT),
            format_json=True,
            procurement_id=procurement_id,
            input_hash=input_hash,
            prompt_version=prompt_version or "v3_routing",
        )

    try:
        if acquire_gpu:
            with acquire_gpu_inference(WORKLOAD_ROUTING) as _slot:
                parsed, meta, retries = _run()
        else:
            parsed, meta, retries = _run()
        logger.info(
            "V3 Ollama model=%s request_model=%s retries=%s total_s=%s",
            meta.get("model"),
            meta.get("request_model"),
            retries,
            meta.get("total_duration_sec"),
        )
        _persist(
            {
                "status": "COMPLETED",
                "procurement_id": procurement_id,
                "attempt_count": meta.get("attempt_count") or (retries + 1),
                "last_attempt_at": datetime.now(timezone.utc).isoformat(),
                "next_retry_at": None,
                "retry_eligible": False,
                "input_hash": input_hash or meta.get("input_hash") or "",
                "prompt_version": prompt_version or "v3_routing",
                "prompt_sha256": meta.get("prompt_sha256"),
                "model": meta.get("model"),
                "failure_reason": None,
                "failure_class": None,
                "attempt_history": meta.get("attempt_history") or [],
                "workload_type": "ROUTING",
            }
        )
    except ModelInferenceFormatFailed as exc:
        logger.error("V3 model format failed after bounded retry: %s", exc)
        durable = dict(exc.durable_state or {})
        durable["attempt_history"] = list(exc.attempt_history or [])
        if exc.meta:
            durable.setdefault("prompt_sha256", exc.meta.get("prompt_sha256"))
        _persist(durable)
        raise OllamaJsonParseError(str(exc)) from exc
    except Exception as e:
        msg = str(e).lower()
        logger.error("Ollama call exception: %s", e)
        if "timeout" in msg or "timed out" in msg:
            return None
        return None

    if isinstance(parsed, dict):
        parsed["_ollama_meta"] = meta
        parsed["_model_format_retry_count"] = retries
        return parsed
    raise OllamaJsonParseError("model response is not a JSON object")

def build_ai_prompt(item: Dict[str, Any]) -> str:
    """Формирует промпт для классификации закупки."""
    return (
        "Ты — эксперт по анализу тендеров и строительных закупок. Твоя задача — классифицировать закупку по ОКПД2 и описанию.\n"
        "Ответь строго в формате JSON, без markdown разметки и без пояснений.\n\n"
        "Правила классификации:\n"
        "1. Оцени предлагаемый профиль маршрутизации (proposed_route_profile) из списка:\n"
        "   - CONSTRUCTION_BUILDING (строительство и ремонт зданий)\n"
        "   - CONSTRUCTION_INFRASTRUCTURE (дороги, мосты, инженерные сети)\n"
        "   - DESIGN_ENGINEERING (проектирование, изыскания, архитектура)\n"
        "   - COMPUTERS_IT (серверы, компьютеры, ИТ-оборудование)\n"
        "   - DIRECT_SUPPLY (мебель, серийные товары)\n"
        "   - EXCLUDED (непрофильные закупки: медицина, продукты питания, охрана)\n"
        "2. Укажи тип объекта (proposed_object_type), например: школа, мост, дорога, компьютер, мебель, прочее.\n"
        "3. Укажи вид закупки (proposed_procurement_type), например: строительство, проектирование, поставка, изыскания, прочее.\n"
        "4. Выдели ключевые релевантные категории (proposed_categories) в виде массива строк.\n"
        "5. Определи уровень кандидата (proposed_level) из списка: GOLD, SILVER, BRONZE, WOOD.\n"
        "   - Критерии уровня: GOLD для крупных строек/проектирования с высокой ценой; WOOD для мелкого текущего ремонта и поставок.\n"
        "6. Укажи уровень уверенности (confidence) от 0.0 до 1.0.\n"
        "7. В reasons дай короткое пояснение на русском языке.\n"
        "8. В reason_codes перечисли коды причин, например: ['okpd_match', 'high_price', 'custom_rule'].\n\n"
        "Входные данные закупки:\n"
        f"Название: {item.get('title')}\n"
        f"Описание: {item.get('description') or 'нет описания'}\n"
        f"Код ОКПД2: {item.get('okpd_code')}\n"
        f"Название ОКПД2: {item.get('okpd_name')}\n"
        f"Начальная цена: {item.get('price')} руб.\n"
        f"Регион: {item.get('region')}\n"
        f"Заказчик: {item.get('customer')}\n"
        f"Закон: {item.get('law_type')}\n\n"
        "JSON schema:\n"
        "{\n"
        '  "proposed_route_profile": "CONSTRUCTION_BUILDING|CONSTRUCTION_INFRASTRUCTURE|DESIGN_ENGINEERING|COMPUTERS_IT|DIRECT_SUPPLY|EXCLUDED",\n'
        '  "proposed_object_type": "школа|больница|дорога|сервер|мебель|...",\n'
        '  "proposed_procurement_type": "строительство|проектирование|поставка|изыскания|...",\n'
        '  "proposed_categories": ["категория1", "категория2"],\n'
        '  "proposed_level": "GOLD|SILVER|BRONZE|WOOD",\n'
        '  "confidence": 0.85,\n'
        '  "reasons": "Текст обоснования на русском",\n'
        '  "reason_codes": ["code1", "code2"]\n'
        "}"
    )

def run_queue_shadow(tender_db, limit: int = 300) -> Dict[str, Any]:
    """Выполняет теневой прогон (Queue Shadow) по новым объектам из реестров-источников."""
    logger.info(f"Запуск Queue Shadow runner. Лимит: {limit} объектов")
    
    # 1. Загружаем правила ОКПД и медианы
    rules = fetch_okpd_rules(tender_db)
    medians = fetch_cohort_medians(tender_db)
    
    # Создаем запись о запуске shadow run
    run_id = str(uuid.uuid4())
    
    # Считаем ревизию правил
    rev_row = tender_db.execute_query("SELECT revision, snapshot_hash FROM okpd_registry_revisions ORDER BY revision DESC LIMIT 1")
    if rev_row:
        rev_val = list(rev_row[0].values())[0] if isinstance(rev_row[0], dict) else rev_row[0][0]
        hash_val = list(rev_row[0].values())[1] if isinstance(rev_row[0], dict) else rev_row[0][1]
    else:
        rev_val = 0
        hash_val = "empty_hash"
        
    tender_db.execute_update(
        """
        INSERT INTO queue_policy_shadow_runs (run_id, status, rules_revision, rules_snapshot_hash, started_at)
        VALUES (%s, 'RUNNING', %s, %s, NOW())
        """,
        (run_id, rev_val, hash_val)
    )
    
    # 2. Выбираем объекты из источников
    # Выбираем объекты из reestr_contract_44_fz и reestr_contract_615_pp, которых еще нет в queue_policy_shadow_results
    query_sources = """
        SELECT 'reestr_contract_44_fz' as src_table, r.id, r.auction_name as title, 
               c.sub_code as okpd_code, c.name as okpd_name, r.initial_price as price, 
               r.delivery_region as region, r.customer, '44_FZ' as law_type, 'OPEN' as lifecycle
        FROM reestr_contract_44_fz r
        LEFT JOIN collection_codes_okpd c ON c.id = r.okpd_id
        WHERE NOT EXISTS (
            SELECT 1 FROM queue_policy_shadow_results 
            WHERE source_table = 'reestr_contract_44_fz' AND source_id = r.id
        )
        UNION ALL
        SELECT 'reestr_contract_615_pp' as src_table, r.id, r.auction_name as title, 
               c.sub_code as okpd_code, c.name as okpd_name, r.initial_price as price, 
               r.delivery_region as region, r.customer, '615_PP' as law_type, 'OPEN' as lifecycle
        FROM reestr_contract_615_pp r
        LEFT JOIN collection_codes_okpd c ON c.id = r.okpd_id
        WHERE NOT EXISTS (
            SELECT 1 FROM queue_policy_shadow_results 
            WHERE source_table = 'reestr_contract_615_pp' AND source_id = r.id
        )
        ORDER BY id DESC
        LIMIT %s
    """
    
    candidates = tender_db.execute_query(query_sources, (limit,)) or []
    logger.info(f"Найдено {len(candidates)} кандидатов для shadow run")
    
    success = failed = skipped = 0
    
    for c_raw in candidates:
        if isinstance(c_raw, dict):
            c = c_raw
        else:
            c = {
                "src_table": c_raw[0],
                "id": c_raw[1],
                "title": c_raw[2],
                "okpd_code": c_raw[3],
                "okpd_name": c_raw[4],
                "price": c_raw[5],
                "region": c_raw[6],
                "customer": c_raw[7],
                "law_type": c_raw[8],
                "lifecycle": c_raw[9]
            }
            
        src_table = c["src_table"]
        src_id = c["id"]
        okpd = c["okpd_code"]
        law = c["law_type"]
        lifecycle = c["lifecycle"]
        price = float(c["price"]) if c["price"] is not None else 0.0
        
        # 1. Deterministic Prefilter
        matched_rule = match_okpd_rule(okpd, rules, law, lifecycle)
        prefilter_res = "AI_REQUIRED"
        route_profile = "UNASSESSED"
        priority_weight = 1.0
        rules_ver = 1
        
        if matched_rule:
            prefilter_res = matched_rule["prefilter_action"]
            route_profile = matched_rule["route_profile"]
            priority_weight = matched_rule["priority_weight"]
            rules_ver = matched_rule["version"]
            
        if prefilter_res == "EXCLUDE":
            tender_db.execute_update(
                """
                INSERT INTO queue_policy_shadow_results (
                    policy_run_id, source_table, source_id, law_type, lifecycle,
                    prefilter_result, proposed_route_profile, status, rules_version, created_at
                ) VALUES (%s, %s, %s, %s, %s, 'EXCLUDE', 'EXCLUDED', 'SKIPPED', %s, NOW())
                """,
                (run_id, src_table, src_id, law, lifecycle, rules_ver)
            )
            skipped += 1
            continue
            
        # 2. EGRZ Check
        egrz = check_egrz_expertise(tender_db, src_table, src_id)
        
        # 3. AI Assessment
        ai_res = None
        if prefilter_res in ("AI_REQUIRED", "MANUAL_REVIEW"):
            prompt = build_ai_prompt(c)
            ai_res = call_ollama_qwen(prompt)
            
        if ai_res:
            route_profile = ai_res.get("proposed_route_profile") or "UNASSESSED"
            proposed_obj = ai_res.get("proposed_object_type")
            proposed_proc = ai_res.get("proposed_procurement_type")
            proposed_cats = ai_res.get("proposed_categories") or []
            cand_level = ai_res.get("proposed_level") or "WOOD"
            raw_conf = ai_res.get("confidence")
            # Preserve 0.0; missing/None does not become 1.0.
            confidence = float(raw_conf) if raw_conf is not None else 0.0
            reasons = ai_res.get("reasons")
            reason_codes = ai_res.get("reason_codes") or []
            status = "SUCCESS"
        else:
            proposed_obj = "строительство"
            proposed_proc = "строительство"
            proposed_cats = []
            cand_level = "WOOD"
            confidence = 0.5
            reasons = "AI классификация не удалась (таймаут или ошибка)"
            reason_codes = ["ai_failed"]
            status = "FAILED" if prefilter_res == "AI_REQUIRED" else "SUCCESS"
            
        if status == "FAILED":
            failed += 1
            tender_db.execute_update(
                """
                INSERT INTO queue_policy_shadow_results (
                    policy_run_id, source_table, source_id, law_type, lifecycle,
                    prefilter_result, proposed_route_profile, status, error, rules_version, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, 'UNASSESSED', 'FAILED', %s, %s, NOW())
                """,
                (run_id, src_table, src_id, law, lifecycle, prefilter_res, reasons, rules_ver)
            )
            continue
            
        # 4. Cohort Medians
        cohort_key = f"{law}_{lifecycle}_{route_profile}"
        median_info = medians.get(cohort_key)
        
        if median_info and median_info["cohort_size"] >= 10:
            median_price = median_info["median_price"]
        else:
            median_price = DEFAULT_MEDIAN_PRICES.get(law, DEFAULT_MEDIAN_PRICES["ALL"])
            
        # 5. Calculate proposed priority
        base_priority = 10.0
        if cand_level == "GOLD":
            base_priority = 100.0
        elif cand_level == "SILVER":
            base_priority = 70.0
        elif cand_level == "BRONZE":
            base_priority = 40.0
            
        proposed_priority = base_priority * priority_weight * confidence
        proposed_priority = min(max(proposed_priority, 0.0), 100.0)
        
        # Записываем результат shadow run
        tender_db.execute_update(
            """
            INSERT INTO queue_policy_shadow_results (
                policy_run_id, source_table, source_id, law_type, lifecycle,
                prefilter_result, proposed_route_profile, proposed_object_type,
                proposed_procurement_type, proposed_categories, candidate_level,
                proposed_priority, confidence, reasons, status, rules_version,
                reason_codes, expertise_status, expertise_source, expertise_record_id,
                expertise_match_method, expertise_match_confidence, created_at, completed_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, 'SUCCESS', %s,
                %s, %s, %s, %s,
                %s, %s, NOW(), NOW()
            )
            """,
            (
                run_id, src_table, src_id, law, lifecycle,
                prefilter_res, route_profile, proposed_obj,
                proposed_proc, json.dumps(proposed_cats), cand_level,
                proposed_priority, confidence, reasons, rules_ver,
                json.dumps(reason_codes), egrz["status"], egrz["source"], egrz["record_id"],
                egrz["match_method"], egrz["match_confidence"]
            )
        )
        success += 1
        
    tender_db.execute_update(
        """
        UPDATE queue_policy_shadow_runs SET
            status = %s,
            completed_at = NOW(),
            total_processed = %s,
            success_count = %s,
            failed_count = %s
        WHERE run_id = %s
        """,
        ("SUCCESS" if failed == 0 else "FAILED", len(candidates), success, failed, run_id)
    )
    
    logger.info(f"Теневой запуск {run_id} завершен. Успешно={success}, ошибок={failed}, пропущено={skipped}")
    return {
        "run_id": run_id,
        "processed": len(candidates),
        "success": success,
        "failed": failed,
        "skipped": skipped
    }

def run_crm_live_ai(tender_db, crm_db, limit: int = 100) -> Dict[str, Any]:
    """Сканирует CRM и проводит классификацию готовых объектов с выводом результатов."""
    logger.info(f"Запуск CRM Live AI runner. Лимит: {limit} объектов")
    
    # 1. Загружаем правила ОКПД
    rules = fetch_okpd_rules(tender_db)
    
    # 2. Выбираем объекты из crm_procurements для классификации
    query_crm = """
        SELECT id, auction_name, okpd_code, okpd_name, initial_price, 
               delivery_region, customer, source_table,
               ai_assessment_status, ai_assessment_version, ai_assessment_fingerprint
        FROM crm_procurements
        WHERE manual_override = FALSE 
          AND ai_assessment_status IN ('UNASSESSED', 'QUEUED', 'RUNNING', 'FAILED', 'STALE')
        LIMIT %s
    """
    candidates = crm_db.execute_query(query_crm, (limit,)) or []
    logger.info(f"Найдено {len(candidates)} кандидатов из CRM")
    
    assessed = reassessed = unchanged = manual_skipped = failed = 0
    
    for c in candidates:
        crm_id = c["id"]
        okpd = c["okpd_code"]
        source_table = c["source_table"] or ""
        
        # Определяем закон
        if "615" in source_table:
            law = "615_PP"
        elif "223" in source_table:
            law = "223_FZ"
        else:
            law = "44_FZ"
            
        # Определяем жизненный цикл
        lifecycle = "AWARDED" if "awarded" in source_table else "OPEN"
        
        # Формируем структуру данных закупки для промпта и хэша
        c_mapped = {
            "title": c["auction_name"],
            "description": "",
            "okpd_code": okpd,
            "okpd_name": c["okpd_name"],
            "price": float(c["initial_price"]) if c["initial_price"] is not None else 0.0,
            "region": c["delivery_region"],
            "customer": c["customer"],
            "law_type": law,
            "lifecycle": lifecycle
        }
        
        # Получаем fingerprint
        fp = get_input_fingerprint(c_mapped)
        
        # Если fingerprint совпадает, помечаем как неизмененный
        if c["ai_assessment_fingerprint"] == fp and c["ai_assessment_status"] == "COMPLETED":
            unchanged += 1
            crm_db.execute_update(
                "UPDATE crm_procurements SET ai_assessment_status = 'COMPLETED', ai_assessed_at = NOW() WHERE id = %s",
                (crm_id,)
            )
            continue
            
        # Обновляем статус в RUNNING перед вызовом модели
        crm_db.execute_update(
            "UPDATE crm_procurements SET ai_assessment_status = 'RUNNING', ai_assessed_at = NOW() WHERE id = %s",
            (crm_id,)
        )
        
        # Подбираем правило
        matched_rule = match_okpd_rule(okpd, rules, law, lifecycle)
        prefilter_res = "AI_REQUIRED"
        route_profile = "UNASSESSED"
        rules_ver = 1
        priority_weight = 1.0
        
        if matched_rule:
            prefilter_res = matched_rule["prefilter_action"]
            route_profile = matched_rule["route_profile"]
            rules_ver = matched_rule["version"]
            priority_weight = matched_rule["priority_weight"]
            
        # 3. AI Assessment
        ai_res = None
        if prefilter_res in ("AI_REQUIRED", "MANUAL_REVIEW"):
            prompt = build_ai_prompt(c_mapped)
            ai_res = call_ollama_qwen(prompt)
            
        if ai_res:
            route_profile = ai_res.get("proposed_route_profile") or "UNASSESSED"
            proposed_obj = ai_res.get("proposed_object_type")
            proposed_proc = ai_res.get("proposed_procurement_type")
            proposed_cats = ai_res.get("proposed_categories") or []
            cand_level = ai_res.get("proposed_level") or "WOOD"
            raw_conf = ai_res.get("confidence")
            # Preserve 0.0; missing/None does not become 1.0.
            confidence = float(raw_conf) if raw_conf is not None else 0.0
            reasons = ai_res.get("reasons")
            reason_codes = ai_res.get("reason_codes") or []
            status = "SUCCESS"
        else:
            proposed_obj = "строительство"
            proposed_proc = "строительство"
            proposed_cats = []
            cand_level = "WOOD"
            confidence = 0.5
            reasons = "AI классификация не удалась (таймаут или ошибка)"
            reason_codes = ["ai_failed"]
            status = "FAILED" if prefilter_res == "AI_REQUIRED" else "SUCCESS"
            
        if status == "FAILED":
            failed += 1
            crm_db.execute_update(
                "UPDATE crm_procurements SET ai_assessment_status = 'FAILED', ai_assessed_at = NOW() WHERE id = %s",
                (crm_id,)
            )
            continue
            
        v_tender = tender_db.execute_scalar(
            "SELECT MAX(assessment_version) FROM procurement_ai_assessments WHERE procurement_id = %s",
            (crm_id,)
        )
        v_crm = crm_db.execute_scalar(
            "SELECT MAX(assessment_version) FROM procurement_ai_assessments WHERE procurement_id = %s",
            (crm_id,)
        )
        new_version = max(v_tender or 0, v_crm or 0, c["ai_assessment_version"] or 0) + 1
        
        # 4. Записываем в authoritative procurement_ai_assessments (tender_monitor)
        # Сначала сбрасываем признак is_current у старых версий
        tender_db.execute_update(
            "UPDATE procurement_ai_assessments SET is_current = FALSE WHERE procurement_id = %s",
            (crm_id,)
        )
        
        tender_res = tender_db.execute_query(
            """
            INSERT INTO procurement_ai_assessments (
                procurement_id, assessment_version, is_current, status, input_fingerprint,
                model_version, prompt_version, rules_version, proposed_route_profile,
                proposed_object_type, proposed_procurement_type, proposed_categories,
                proposed_level, confidence, reasons, reason_codes, started_at, completed_at
            ) VALUES (%s, %s, TRUE, 'SUCCESS', %s, 'qwen2.5:7b', 'v2a_prompt', %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            RETURNING id
            """,
            (
                crm_id, new_version, fp, rules_ver, route_profile,
                proposed_obj, proposed_proc, json.dumps(proposed_cats),
                cand_level, confidence, reasons, json.dumps(reason_codes)
            )
        )
        
        auth_id = 0
        if tender_res:
            auth_id = list(tender_res[0].values())[0] if isinstance(tender_res[0], dict) else tender_res[0][0]
            
        # 5. Синхронизируем в crm read projection procurement_ai_assessments
        crm_db.execute_update(
            "UPDATE procurement_ai_assessments SET is_current = FALSE WHERE procurement_id = %s",
            (crm_id,)
        )
        crm_db.execute_update(
            """
            INSERT INTO procurement_ai_assessments (
                authoritative_id, procurement_id, assessment_version, is_current, status, input_fingerprint,
                model_version, prompt_version, rules_version, proposed_route_profile,
                proposed_object_type, proposed_procurement_type, proposed_categories,
                proposed_level, confidence, reasons, reason_codes, started_at, completed_at
            ) VALUES (%s, %s, %s, TRUE, 'SUCCESS', %s, 'qwen2.5:7b', 'v2a_prompt', %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            """,
            (
                auth_id, crm_id, new_version, fp, rules_ver, route_profile,
                proposed_obj, proposed_proc, json.dumps(proposed_cats),
                cand_level, confidence, reasons, json.dumps(reason_codes)
            )
        )
        
        # 6. Обновляем саму crm_procurements
        crm_db.execute_update(
            """
            UPDATE crm_procurements SET
                ai_assessment_status = 'COMPLETED',
                ai_assessment_version = %s,
                ai_assessment_fingerprint = %s,
                ai_assessed_at = NOW()
            WHERE id = %s
            """,
            (new_version, fp, crm_id)
        )
        
        if c["ai_assessment_version"]:
            reassessed += 1
        else:
            assessed += 1
            
    logger.info(f"CRM Live AI прогон завершен. Оценено={assessed}, переоценено={reassessed}, неизмененных={unchanged}, ошибок={failed}")
    return {
        "processed": len(candidates),
        "assessed": assessed,
        "reassessed": reassessed,
        "unchanged": unchanged,
        "failed": failed
    }

def main():
    parser = argparse.ArgumentParser(description="V2A Background AI Runner")
    parser.add_argument("--mode", choices=["shadow", "live", "both"], required=True, help="Режим работы")
    parser.add_argument("--limit", type=int, default=100, help="Лимит записей")
    args = parser.parse_args()
    
    sys.path.insert(0, "/opt/CRM_Streamlit")
    sys.path.insert(0, "/opt/pythonProject89")
    from src.services.db_bootstrap import connect_databases
    
    _r, tender_db, crm_db, warn = connect_databases()
    if warn:
        logger.warning(f"Connection warning: {warn}")
        
    conn_t = tender_db.get_connection()
    with conn_t:
        with conn_t.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (RUNNER_LOCK_ID,))
            locked = cur.fetchone()
            locked_val = list(locked.values())[0] if isinstance(locked, dict) else locked[0]
            if not locked_val:
                logger.warning("Не удалось получить advisory lock. Другой раннер уже запущен. Завершение.")
                sys.exit(0)
                
            if args.mode in ("shadow", "both"):
                last_run = tender_db.execute_query(
                    "SELECT started_at FROM queue_policy_shadow_runs WHERE status = 'RUNNING' ORDER BY started_at DESC LIMIT 1"
                )
                if last_run:
                    started_at = list(last_run[0].values())[0] if isinstance(last_run[0], dict) else last_run[0][0]
                    if (datetime.now(timezone.utc) - started_at.replace(tzinfo=timezone.utc)).total_seconds() < 10800:
                        logger.warning("Предыдущий shadow run все еще имеет статус RUNNING. Skipping.")
                        sys.exit(0)
                        
                run_queue_shadow(tender_db, args.limit)
                
            if args.mode in ("live", "both"):
                run_crm_live_ai(tender_db, crm_db, args.limit)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    main()
