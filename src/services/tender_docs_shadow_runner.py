"""Tender Docs Shadow Runner: Теневой расчет приоритетов по реестрам-источникам."""
from __future__ import annotations
import argparse
import json
import logging
import sys
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("tender_docs_shadow_runner")

LOCK_ID = 892341235612349013

def fetch_rules(tender_db) -> List[Dict[str, Any]]:
    from src.services.ai_assessment_runner import fetch_okpd_rules
    return fetch_okpd_rules(tender_db)

def fetch_medians(tender_db) -> Dict[str, Dict[str, Any]]:
    from src.services.ai_assessment_runner import fetch_cohort_medians
    return fetch_cohort_medians(tender_db)

def get_candidates(tender_db, limit: int) -> List[Dict[str, Any]]:
    query = """
        SELECT 'reestr_contract_44_fz' as src_table, r.id, r.auction_name as title, 
               c.sub_code as okpd_code, c.name as okpd_name, r.initial_price as price, 
               r.delivery_region as region, r.customer, '44_FZ' as law_type, 'OPEN' as lifecycle,
               r.end_date as end_date
        FROM reestr_contract_44_fz r
        LEFT JOIN collection_codes_okpd c ON c.id = r.okpd_id
        WHERE NOT EXISTS (
            SELECT 1 FROM queue_policy_shadow_results 
            WHERE source_table = 'reestr_contract_44_fz' AND source_id = r.id
        )
        UNION ALL
        SELECT 'reestr_contract_615_pp' as src_table, r.id, r.auction_name as title, 
               c.sub_code as okpd_code, c.name as okpd_name, r.initial_price as price, 
               r.delivery_region as region, r.customer, '615_PP' as law_type, 'OPEN' as lifecycle,
               r.end_date as end_date
        FROM reestr_contract_615_pp r
        LEFT JOIN collection_codes_okpd c ON c.id = r.okpd_id
        WHERE NOT EXISTS (
            SELECT 1 FROM queue_policy_shadow_results 
            WHERE source_table = 'reestr_contract_615_pp' AND source_id = r.id
        )
        ORDER BY id DESC
        LIMIT %s
    """
    rows = tender_db.execute_query(query, (limit,)) or []
    candidates = []
    for r in rows:
        candidates.append({
            "src_table": r[0] if not isinstance(r, dict) else r["src_table"],
            "id": r[1] if not isinstance(r, dict) else r["id"],
            "title": r[2] if not isinstance(r, dict) else r["title"],
            "okpd_code": r[3] if not isinstance(r, dict) else r["okpd_code"],
            "okpd_name": r[4] if not isinstance(r, dict) else r["okpd_name"],
            "price": r[5] if not isinstance(r, dict) else r["price"],
            "region": r[6] if not isinstance(r, dict) else r["region"],
            "customer": r[7] if not isinstance(r, dict) else r["customer"],
            "law_type": r[8] if not isinstance(r, dict) else r["law_type"],
            "lifecycle": r[9] if not isinstance(r, dict) else r["lifecycle"],
            "end_date": r[10] if not isinstance(r, dict) else r["end_date"]
        })
    return candidates

def run_shadow(tender_db, limit: int = 100) -> Dict[str, Any]:
    from src.services.ai_assessment_runner import match_okpd_rule, check_egrz_expertise, build_ai_prompt, call_ollama_qwen, DEFAULT_MEDIAN_PRICES
    from src.services.candidate_policy import CandidatePolicy

    rules = fetch_rules(tender_db)
    medians = fetch_medians(tender_db)
    candidates = get_candidates(tender_db, limit)
    logger.info(f"Queue Shadow: Found {len(candidates)} candidates.")

    run_id = str(uuid.uuid4())
    rev_row = tender_db.execute_query("SELECT revision, snapshot_hash FROM okpd_registry_revisions ORDER BY revision DESC LIMIT 1")
    rev_val, hash_val = (rev_row[0][0], rev_row[0][1]) if rev_row and not isinstance(rev_row[0], dict) else (0, "empty_hash")
    if rev_row and isinstance(rev_row[0], dict):
        rev_val = rev_row[0].get("revision", 0)
        hash_val = rev_row[0].get("snapshot_hash", "empty_hash")

    # Инициализация запуска с немедленным коммитом
    conn_t = tender_db.get_connection()
    with conn_t:
        with conn_t.cursor() as cur:
            cur.execute(
                "INSERT INTO queue_policy_shadow_runs (run_id, status, rules_revision, rules_snapshot_hash, started_at) VALUES (%s, 'RUNNING', %s, %s, NOW())",
                (run_id, rev_val, hash_val)
            )

    success = failed = skipped = 0
    for idx, c in enumerate(candidates):
        src_table, src_id = c["src_table"], c["id"]
        okpd, law, lifecycle = c["okpd_code"], c["law_type"], c["lifecycle"]
        price = float(c["price"]) if c["price"] is not None else 0.0

        matched_rule = match_okpd_rule(okpd, rules, law, lifecycle)
        prefilter_res = matched_rule["prefilter_action"] if matched_rule else "AI_REQUIRED"
        route_profile = matched_rule["route_profile"] if matched_rule else "UNASSESSED"
        rules_ver = matched_rule["version"] if matched_rule else 1
        priority_weight = float(matched_rule["priority_weight"]) if matched_rule else 1.0

        # Обработка в индивидуальных транзакциях
        try:
            if prefilter_res == "EXCLUDE":
                with conn_t:
                    with conn_t.cursor() as cur:
                        cur.execute(
                            "INSERT INTO queue_policy_shadow_results (policy_run_id, source_table, source_id, law_type, lifecycle, prefilter_result, proposed_route_profile, status, rules_version, created_at) VALUES (%s, %s, %s, %s, %s, 'EXCLUDE', 'EXCLUDED', 'SKIPPED', %s, NOW())",
                            (run_id, src_table, src_id, law, lifecycle, rules_ver)
                        )
                skipped += 1
                continue

            egrz = check_egrz_expertise(tender_db, src_table, src_id)
            ai_res = call_ollama_qwen(build_ai_prompt(c)) if prefilter_res in ("AI_REQUIRED", "MANUAL_REVIEW") else None

            if ai_res:
                route_profile = ai_res.get("proposed_route_profile") or "UNASSESSED"
                proposed_obj = ai_res.get("proposed_object_type")
                proposed_proc = ai_res.get("proposed_procurement_type")
                proposed_cats = ai_res.get("proposed_categories") or []
                raw_conf = ai_res.get("confidence")
                # Preserve 0.0; missing/None does not become 1.0.
                confidence = float(raw_conf) if raw_conf is not None else 0.0
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
                with conn_t:
                    with conn_t.cursor() as cur:
                        cur.execute(
                            "INSERT INTO queue_policy_shadow_results (policy_run_id, source_table, source_id, law_type, lifecycle, prefilter_result, proposed_route_profile, status, error, rules_version, created_at) VALUES (%s, %s, %s, %s, %s, %s, 'UNASSESSED', 'FAILED', %s, %s, NOW())",
                            (run_id, src_table, src_id, law, lifecycle, prefilter_res, reasons, rules_ver)
                        )
                failed += 1
                continue

            # Когортная медиана
            cohort_key = f"{law}_{lifecycle}_{route_profile}"
            median_info = medians.get(cohort_key)
            median_price = median_info["median_price"] if median_info and median_info["cohort_size"] >= 10 else DEFAULT_MEDIAN_PRICES.get(law, DEFAULT_MEDIAN_PRICES["ALL"])

            # Расчет через CandidatePolicy
            policy_res = CandidatePolicy.calculate(route_profile, lifecycle, c, ai_res or {"confidence": confidence}, median_price, egrz)
            proposed_priority = policy_res["candidate_score"]
            cand_level = policy_res["candidate_level"]

            with conn_t:
                with conn_t.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO queue_policy_shadow_results (
                            policy_run_id, source_table, source_id, law_type, lifecycle,
                            prefilter_result, proposed_route_profile, proposed_object_type,
                            proposed_procurement_type, proposed_categories, candidate_level,
                            proposed_priority, confidence, reasons, status, rules_version,
                            reason_codes, expertise_status, expertise_source, expertise_record_id,
                            expertise_match_method, expertise_match_confidence, created_at, completed_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'SUCCESS', %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                        """,
                        (
                            run_id, src_table, src_id, law, lifecycle, prefilter_res, route_profile, proposed_obj,
                            proposed_proc, json.dumps(proposed_cats), cand_level, proposed_priority, confidence, reasons,
                            rules_ver, json.dumps(reason_codes), egrz["status"], egrz["source"], egrz["record_id"],
                            egrz["match_method"], egrz["match_confidence"]
                        )
                    )
            success += 1
        except Exception as item_err:
            logger.error(f"Error processing candidate {src_table}:{src_id}: {item_err}")
            failed += 1

        # Инкрементальное обновление статуса рана после каждого объекта
        with conn_t:
            with conn_t.cursor() as cur:
                cur.execute(
                    "UPDATE queue_policy_shadow_runs SET total_processed = %s, success_count = %s, failed_count = %s WHERE run_id = %s",
                    (idx + 1, success, failed, run_id)
                )

    # Финальный статус рана
    with conn_t:
        with conn_t.cursor() as cur:
            cur.execute(
                "UPDATE queue_policy_shadow_runs SET status = %s, completed_at = NOW() WHERE run_id = %s",
                ("SUCCESS" if failed == 0 else ("FAILED" if success == 0 else "FAILED"), run_id)
            )

    logger.info(f"Shadow Run {run_id} finished. Success={success}, Failed={failed}, Skipped={skipped}")
    return {"run_id": run_id, "success": success, "failed": failed}

def main():
    parser = argparse.ArgumentParser(description="Tender Docs Shadow Runner")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    from src.services.db_bootstrap import connect_databases
    _r, tender_db, _c, warn = connect_databases()
    if warn:
        logger.warning(warn)

    conn = tender_db.get_connection()
    conn.set_session(autocommit=True)
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,))
        row = cur.fetchone()
        locked = list(row.values())[0] if isinstance(row, dict) else (row[0] if row else False)
        if not locked:
            logger.warning("Advisory lock busy. Exiting.")
            sys.exit(0)

    try:
        run_shadow(tender_db, args.limit)
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    main()
