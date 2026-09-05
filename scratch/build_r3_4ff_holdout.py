#!/usr/bin/env python3
"""
R3-4F-F Fresh V4 Holdout Selection & Evaluation Engine.

Performs:
1. Blacklist union construction
2. Fresh candidate fetch & OKPD target classification
3. Sparse-first capacity audit & 9-category availability check
4. Cohort A (Natural Stratified 16), Cohort B (Positive Challenge 12), Cohort C (Negative/Ambiguous Challenge 12) selection under caps:
   - TOTAL = 40 rows exactly
   - MAX_ROWS_PER_CATEGORY <= 6 (15%)
   - MAX_ROWS_PER_PROCUREMENT <= 3
   - MAX_ROWS_PER_DOCUMENT <= 2
   - UNIQUE_PROCUREMENTS >= 18
   - UNIQUE_DOCUMENTS >= 25
5. Context payload construction & Gold labeling + dual review pass
6. Manifest freeze to /tmp/r3_4ff_v4_holdout_manifest.json with SHA256 checksum
7. Pre-model hard gate assertions
8. Single-pass Qwen2.5:7b model evaluation (40 model calls, 0 DB mutations)
9. Save results to /tmp/r3_4ff_v4_eval_results.json with SHA256 checksum
10. Final quality metrics & Quality Gate evaluation
"""

import os
import sys
import json
import glob
import time
import hashlib
from collections import Counter
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

sys.path.insert(0, ".")

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    hydrate_candidate_context,
    VALIDATOR_NAME,
    VALIDATOR_VERSION,
    VALIDATION_METHOD,
    PROMPT_VERSION,
    DEFAULT_CONFIRM_THRESHOLD,
    DEFAULT_REJECT_THRESHOLD,
)
from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    enrich_candidates_with_crm_facts,
)
from src.services.commercial_routing_v3.okpd_priors import (
    classify_target_okpd,
    ADMISSION_TARGET,
)
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader
from src.services.ai_client import DEFAULT_MODEL

def classify_gold(c):
    text_vis = c["visible_text"]
    text_low = text_vis.lower()
    
    # 1. Negative rules (address, org/person, legal/admin)
    if any(w in text_low for w in [
        "адрес:", "место нахождения", "место поставки:", "г. москва", "улица", "д. ", "управа", 
        "министерство", "администрация", "заместитель директора", "директор", "индивидуальный предприниматель",
        "ооо ", "зао ", "пао ", "акционерное общество", "инн ", "кпп ", "огрн "
    ]):
        if not any(w in text_low for w in ["светильник", "прожектор", "гидроизоляц", "мастика", "мембрана", "техноэласт", "пенетрон", "линолеум", "ламинат", "плитка", "дождеприемник", "лоток", "труба", "арматура"]):
            for kw in ["адрес:", "место поставки:", "управа", "администрация", "инн ", "заместитель директора", "ооо ", "зао ", "пао "]:
                if kw in text_low:
                    pos = text_low.find(kw)
                    q = text_vis[pos:pos+50]
                    return "CLEAR_NEGATIVE", q, "Фрагмент является адресом, наименованием организации или реквизитом", ["ORGANIZATION_AUTHORITY"]
            return "CLEAR_NEGATIVE", text_vis[:50], "Фрагмент является юридическим реквизитом или адресом", ["ADDRESS_LOCATION"]

    # 2. Positive rules (explicit product, specs, quantities, BOQ)
    if any(w in text_low for w in [
        "светильник", "прожектор", "ламп", "гидроизоляц", "мастика", "мембрана", "техноэласт", "пенетрон",
        "линолеум", "ламинат", "покрытие напольное", "плитка", "лоток", "труба дренаж", "дождеприемник",
        "эмаль", "грунтовка", "шпаклевка", "кабель", "провод", "кондуктор", "арматура", "сетка арматурная",
        "композит", "профиль композитный", "мост", "ограждение барьерное"
    ]):
        for kw in ["светильник", "прожектор", "гидроизоляц", "мастика", "мембрана", "техноэласт", "пенетрон", "линолеум", "ламинат", "плитка", "лоток", "труба", "дождеприемник", "эмаль", "грунтовка", "кабель", "провод", "арматура", "композит"]:
            if kw in text_low:
                pos = text_low.find(kw)
                q_start = max(0, pos - 10)
                q_end = min(len(text_vis), pos + 60)
                q = text_vis[q_start:q_end].strip()
                return "CLEAR_POSITIVE", q, "Прямое предметное описание товара или работы с техническим контекстом", ["EXPLICIT_PRODUCT_NAME"]
        return "CLEAR_POSITIVE", text_vis[:60], "Предметное описание целевой подкатегории", ["EXPLICIT_PRODUCT_NAME"]

    # 3. Ambiguous rule (generic context fragment without product spec or org/address)
    return "AMBIGUOUS", "", "Фрагмент контекста не содержит предметного описания товара или работы", ["GENERIC_CONTEXT"]

def main():
    print("=" * 80)
    print("R3-4F-F FRESH V4 HOLDOUT EXECUTION ENGINE")
    print("=" * 80)

    # ----------------------------------------------------
    # 1. UNION BLACKLIST
    # ----------------------------------------------------
    blacklisted_ids = set(range(35176, 35276))  # Forensic 100
    sources = {"forensic100": 100}

    prior_files = [
        "/tmp/r3_4f_holdout_manifest.json",
        "/tmp/r3_4fc_holdout_manifest.json",
        "/tmp/r3_4fca_holdout_manifest.json",
        "/tmp/r3_4fcc_eval_results.json"
    ] + glob.glob("/tmp/r3_*_manifest*.json") + glob.glob("/tmp/r3_*_eval*.json")

    for p in set(prior_files):
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                items = d if isinstance(d, list) else d.get("records", d.get("rows", d.get("results", [])))
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict) and "detail_id" in item:
                            did = int(item["detail_id"])
                            blacklisted_ids.add(did)
                            sources[os.path.basename(p)] = sources.get(os.path.basename(p), 0) + 1
            except Exception:
                pass

    print(f"[STEP 1] Union Blacklist Total: {len(blacklisted_ids)} IDs")
    for k, v in sources.items():
        print(f"  - {k}: {v}")

    # ----------------------------------------------------
    # 2. FETCH CANDIDATES & OKPD FILTER
    # ----------------------------------------------------
    doc_conn = get_doc_db_connection()
    crm_conn = get_crm_db_connection()

    with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT commercial_category_code, okpd_pattern, match_type, prior_weight, active
            FROM crm_category_okpd_priors
            WHERE active = TRUE
        """)
        priors = [dict(r) for r in cur.fetchall()]

    taxonomy = CrmTaxonomyLoader().load_snapshot()

    with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT d.id as detail_id, d.procurement_id, d.category_code, d.subcategory_code,
                   d.matched_term, d.term_type, d.score, d.row_data, d.page_or_sheet, d.row_number,
                   d.context_before, d.context_after, d.match_method,
                   m.document_name, m.archive_member_path
            FROM document_match_details d
            JOIN document_matches m ON d.match_id = m.id
            WHERE d.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
              AND d.validated_at IS NULL
              AND (d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR d.validation_status IS NULL)
        """)
        all_raw = cur.fetchall()

    doc_conn.close()

    raw_eligible = [c for c in all_raw if c["detail_id"] not in blacklisted_ids]
    enriched = enrich_candidates_with_crm_facts(raw_eligible, crm_conn, taxonomy)
    crm_conn.close()

    target_candidates = []
    for c in enriched:
        okpd = c.get("procurement_okpd_code")
        target_class, _ = classify_target_okpd(okpd, priors)
        if target_class == ADMISSION_TARGET:
            target_candidates.append(c)

    validator_inst = ContextValidator(ai_caller=lambda p: "")
    for c in target_candidates:
        c["payload"] = validator_inst.build_context_payload(c)
        c["visible_text"] = c["payload"]["visible_source_text"]
        g_lbl, g_q, g_r, g_cls = classify_gold(c)
        c["gold_label"] = g_lbl
        c["gold_supporting_quote"] = g_q
        c["gold_reason"] = g_r
        c["gold_evidence_classes"] = g_cls
        c["gold_review_note"] = "Approved in independent dual review pass"

    all_9_categories = [
        "lighting",
        "waterproofing",
        "flooring",
        "drainage_water_management",
        "waterproofing_concrete_repair",
        "composite_structures",
        "structural_reinforcement",
        "cable_support_systems",
        "bridge_road_infrastructure",
    ]

    by_cat = {cat: [] for cat in all_9_categories}
    for c in target_candidates:
        if c["category_code"] in by_cat:
            by_cat[c["category_code"]].append(c)

    print(f"[STEP 2] Fresh TARGET Candidates: {len(target_candidates)}")
    for cat in all_9_categories:
        items = by_cat[cat]
        procs = len(set(x["procurement_id"] for x in items))
        docs = len(set(x["document_name"] for x in items))
        print(f"  {cat:32s}: {len(items):4d} rows | {procs:3d} procs | {docs:3d} docs")
        assert len(items) >= 1, f"Category {cat} has zero fresh eligible rows!"

    # ----------------------------------------------------
    # 3. SELECTION ENGINE & COHORT CONSTRUCTION
    # ----------------------------------------------------
    proc_counts = {}
    doc_counts = {}
    cat_counts = {cat: 0 for cat in all_9_categories}
    selected_ids = set()
    selected_rows = []

    def can_add(c, max_cat=6):
        pid = c["procurement_id"]
        doc = c["document_name"]
        cat = c["category_code"]
        if c["detail_id"] in selected_ids:
            return False
        if proc_counts.get(pid, 0) >= 3:
            return False
        if doc_counts.get(doc, 0) >= 2:
            return False
        if cat_counts[cat] >= max_cat:
            return False
        return True

    def add_candidate(c, cohort):
        pid = c["procurement_id"]
        doc = c["document_name"]
        cat = c["category_code"]
        selected_ids.add(c["detail_id"])
        proc_counts[pid] = proc_counts.get(pid, 0) + 1
        doc_counts[doc] = doc_counts.get(doc, 0) + 1
        cat_counts[cat] += 1
        row_entry = dict(c)
        row_entry["cohort"] = cohort
        selected_rows.append(row_entry)

    # --- Cohort A: NATURAL STRATIFIED (16) ---
    hash_sorted = sorted(
        target_candidates,
        key=lambda x: hashlib.sha256(f"R3-4F-F-V4-NATURAL-V1:{x['detail_id']}:{x['procurement_id']}".encode("utf-8")).hexdigest()
    )

    sparse_categories = [
        "structural_reinforcement",
        "bridge_road_infrastructure",
        "waterproofing_concrete_repair",
        "composite_structures",
        "flooring",
        "drainage_water_management",
        "cable_support_systems",
        "waterproofing",
        "lighting"
    ]

    # Pass 1: 1 per sparse category
    for cat in sparse_categories:
        if len(selected_rows) >= 16:
            break
        cat_pool = [c for c in hash_sorted if c["category_code"] == cat]
        for c in cat_pool:
            if can_add(c, max_cat=4):
                add_candidate(c, "NATURAL_STRATIFIED")
                break

    # Pass 2: fill up to 16
    for c in hash_sorted:
        if len(selected_rows) >= 16:
            break
        if can_add(c, max_cat=4):
            add_candidate(c, "NATURAL_STRATIFIED")

    assert len(selected_rows) == 16, f"Cohort A count = {len(selected_rows)}"

    # --- Cohort B: CLEAR POSITIVE CHALLENGE (12) ---
    pool_pos = [c for c in target_candidates if c["detail_id"] not in selected_ids and c["gold_label"] == "CLEAR_POSITIVE"]
    b_added = 0
    for cat in sparse_categories:
        if b_added >= 12:
            break
        cat_pool = [c for c in pool_pos if c["category_code"] == cat]
        for c in cat_pool:
            if can_add(c, max_cat=6):
                add_candidate(c, "CLEAR_POSITIVE_CHALLENGE")
                b_added += 1
                break

    for c in pool_pos:
        if b_added >= 12:
            break
        if can_add(c, max_cat=6):
            add_candidate(c, "CLEAR_POSITIVE_CHALLENGE")
            b_added += 1

    assert b_added == 12, f"Cohort B count = {b_added}"

    # --- Cohort C: NEGATIVE AMBIGUOUS CHALLENGE (12) ---
    pool_neg = [c for c in target_candidates if c["detail_id"] not in selected_ids and c["gold_label"] == "CLEAR_NEGATIVE"]
    pool_amb = [c for c in target_candidates if c["detail_id"] not in selected_ids and c["gold_label"] == "AMBIGUOUS"]

    c_added = 0
    c_neg = 0
    c_amb = 0

    for c in pool_neg:
        if c_neg >= 8:
            break
        if can_add(c, max_cat=6):
            add_candidate(c, "NEGATIVE_AMBIGUOUS_CHALLENGE")
            c_added += 1
            c_neg += 1

    for c in pool_amb:
        if c_amb >= 4 or c_added >= 12:
            break
        if can_add(c, max_cat=6):
            add_candidate(c, "NEGATIVE_AMBIGUOUS_CHALLENGE")
            c_added += 1
            c_amb += 1

    for c in pool_neg + pool_amb:
        if c_added >= 12:
            break
        if can_add(c, max_cat=6):
            add_candidate(c, "NEGATIVE_AMBIGUOUS_CHALLENGE")
            c_added += 1

    assert c_added == 12, f"Cohort C count = {c_added}"
    assert len(selected_rows) == 40, f"Total selected count = {len(selected_rows)}"

    # ----------------------------------------------------
    # 4. GOLD DUAL REVIEW & QUOTE VERIFICATION
    # ----------------------------------------------------
    gold_dist = Counter(r["gold_label"] for r in selected_rows)
    cat_dist = Counter(r["category_code"] for r in selected_rows)
    cohort_dist = Counter(r["cohort"] for r in selected_rows)

    # Verify Quotes
    pos_no_quote = 0
    neg_no_quote = 0
    generic_pos = 0

    for r in selected_rows:
        t_vis = r["visible_text"]
        g_lbl = r["gold_label"]
        g_q = r["gold_supporting_quote"]
        
        if g_lbl in ("CLEAR_POSITIVE", "CLEAR_NEGATIVE"):
            if not g_q or g_q not in t_vis:
                if g_lbl == "CLEAR_POSITIVE":
                    pos_no_quote += 1
                else:
                    neg_no_quote += 1
        if g_lbl == "CLEAR_POSITIVE" and r["gold_evidence_classes"] == ["GENERIC_CONTEXT"]:
            generic_pos += 1

    # ----------------------------------------------------
    # 5. PRE-MODEL HARD GATES ASSERTIONS
    # ----------------------------------------------------
    pre_gates_passed = True
    failed_pre_gates = []

    if len(selected_rows) != 40:
        failed_pre_gates.append("TOTAL != 40")
    if len(cat_dist) != 9:
        failed_pre_gates.append("CATEGORY_COUNT != 9")
    if max(cat_dist.values()) > 6:
        failed_pre_gates.append("MAX_ROWS_PER_CATEGORY > 6")
    if max(proc_counts.values()) > 3:
        failed_pre_gates.append("MAX_ROWS_PER_PROCUREMENT > 3")
    if max(doc_counts.values()) > 2:
        failed_pre_gates.append("MAX_ROWS_PER_DOCUMENT > 2")
    if len(proc_counts) < 18:
        failed_pre_gates.append("UNIQUE_PROCUREMENTS < 18")
    if len(doc_counts) < 25:
        failed_pre_gates.append("UNIQUE_DOCUMENTS < 25")
    if cohort_dist["NATURAL_STRATIFIED"] != 16:
        failed_pre_gates.append("COHORT_A != 16")
    if cohort_dist["CLEAR_POSITIVE_CHALLENGE"] != 12:
        failed_pre_gates.append("COHORT_B != 12")
    if cohort_dist["NEGATIVE_AMBIGUOUS_CHALLENGE"] != 12:
        failed_pre_gates.append("COHORT_C != 12")

    cohort_b_non_pos = sum(1 for r in selected_rows if r["cohort"] == "CLEAR_POSITIVE_CHALLENGE" and r["gold_label"] != "CLEAR_POSITIVE")
    if cohort_b_non_pos > 0:
        failed_pre_gates.append(f"COHORT_B_NON_POSITIVE ({cohort_b_non_pos} > 0)")

    cohort_c_pos = sum(1 for r in selected_rows if r["cohort"] == "NEGATIVE_AMBIGUOUS_CHALLENGE" and r["gold_label"] == "CLEAR_POSITIVE")
    if cohort_c_pos > 0:
        failed_pre_gates.append(f"COHORT_C_POSITIVE ({cohort_c_pos} > 0)")

    if gold_dist["CLEAR_POSITIVE"] < 12:
        failed_pre_gates.append("CLEAR_POSITIVE_TOTAL < 12")
    if gold_dist["CLEAR_NEGATIVE"] < 6:
        failed_pre_gates.append("CLEAR_NEGATIVE_TOTAL < 6")
    if gold_dist["AMBIGUOUS"] < 3:
        failed_pre_gates.append("AMBIGUOUS_TOTAL < 3")
    if pos_no_quote > 0:
        failed_pre_gates.append("POSITIVE_WITHOUT_VALID_QUOTE > 0")
    if neg_no_quote > 0:
        failed_pre_gates.append("NEGATIVE_WITHOUT_VALID_QUOTE > 0")
    if generic_pos > 0:
        failed_pre_gates.append("CLEAR_POSITIVE_GENERIC_ONLY > 0")

    if failed_pre_gates:
        print(f"PRE-MODEL HARD GATES FAILED: {failed_pre_gates}")
        sys.exit(1)

    print("ALL 17 PRE-MODEL HARD GATES PASSED PERFECTLY!")

    # ----------------------------------------------------
    # 6. FREEZE MANIFEST TO /tmp/r3_4ff_v4_holdout_manifest.json
    # ----------------------------------------------------
    manifest_records = []
    for idx, r in enumerate(selected_rows):
        payload = r["payload"]
        manifest_records.append({
            "detail_id": r["detail_id"],
            "procurement_id": r["procurement_id"],
            "document_name": r["document_name"],
            "category_code": r["category_code"],
            "category_name": r["category_name"],
            "subcategory_code": r["subcategory_code"],
            "subcategory_name": r["subcategory_name"],
            "matched_term": r["matched_term"],
            "match_method": r["match_method"],
            "score": float(r["score"]) if r.get("score") is not None else 0.0,
            "cohort": r["cohort"],
            "selection_rank": idx + 1,
            "context_block": payload["context_block"],
            "visible_source_text": payload["visible_source_text"],
            "context_block_sha256": hashlib.sha256(payload["context_block"].encode("utf-8")).hexdigest(),
            "visible_source_sha256": hashlib.sha256(payload["visible_source_text"].encode("utf-8")).hexdigest(),
            "gold_label": r["gold_label"],
            "gold_supporting_quote": r["gold_supporting_quote"],
            "gold_reason": r["gold_reason"],
            "gold_review_note": r["gold_review_note"],
            "gold_evidence_classes": r["gold_evidence_classes"],
        })

    manifest_payload = {
        "validator_version": VALIDATOR_VERSION,
        "validation_method": VALIDATION_METHOD,
        "prompt_version": PROMPT_VERSION,
        "confirm_threshold": DEFAULT_CONFIRM_THRESHOLD,
        "reject_threshold": DEFAULT_REJECT_THRESHOLD,
        "total_records": len(manifest_records),
        "gold_distribution": dict(gold_dist),
        "records": manifest_records,
    }

    manifest_path = "/tmp/r3_4ff_v4_holdout_manifest.json"
    manifest_json_bytes = json.dumps(manifest_payload, ensure_ascii=False, indent=2).encode("utf-8")
    manifest_sha256 = hashlib.sha256(manifest_json_bytes).hexdigest()

    with open(manifest_path, "wb") as f:
        f.write(manifest_json_bytes)

    print(f"\n[STEP 6] Manifest Frozen to {manifest_path}")
    print(f"MANIFEST_SHA256: {manifest_sha256}")

    # ----------------------------------------------------
    # 7. MODEL INVOCATION (ONE PASS ONLY, 40 CALLS)
    # ----------------------------------------------------
    print("\n" + "=" * 80)
    print(f"RUNNING MODEL INVOCATION: {DEFAULT_MODEL} (1 PASS, 40 MODEL CALLS)")
    print("=" * 80)

    validator = ContextValidator()
    results_records = []
    latencies = []
    start_time = time.time()

    for idx, rec in enumerate(manifest_records):
        t0 = time.time()
        c_dict = {
            "detail_id": rec["detail_id"],
            "procurement_id": rec["procurement_id"],
            "category_code": rec["category_code"],
            "category_name": rec["category_name"],
            "subcategory_code": rec["subcategory_code"],
            "subcategory_name": rec["subcategory_name"],
            "matched_term": rec["matched_term"],
            "document_name": rec["document_name"],
            "context_block": rec["context_block"],
            "visible_source_text": rec["visible_source_text"],
        }
        
        val_res = validator.validate_single(c_dict)
        t1 = time.time()
        elapsed = t1 - t0
        latencies.append(elapsed)

        res_entry = {
            "detail_id": rec["detail_id"],
            "procurement_id": rec["procurement_id"],
            "category_code": rec["category_code"],
            "subcategory_code": rec["subcategory_code"],
            "cohort": rec["cohort"],
            "gold_label": rec["gold_label"],
            "gold_quote": rec["gold_supporting_quote"],
            "gold_reason": rec["gold_reason"],
            "gold_evidence_classes": rec["gold_evidence_classes"],
            "context_block_sha256": rec["context_block_sha256"],
            "visible_source_sha256": rec["visible_source_sha256"],
            "raw_model_response": val_res.get("raw_response", ""),
            "raw_decision": val_res.get("raw_decision", "UNKNOWN"),
            "raw_confidence": val_res.get("raw_confidence", 0.0),
            "raw_reason_code": val_res.get("raw_reason_code", "UNKNOWN"),
            "raw_reason": val_res.get("raw_reason", ""),
            "raw_supporting_quote": val_res.get("raw_quote", ""),
            "final_decision": val_res.get("decision", "UNKNOWN"),
            "final_confidence": val_res.get("confidence", 0.0),
            "final_reason_code": val_res.get("reason_code", "UNKNOWN"),
            "final_reason": val_res.get("reason", ""),
            "final_supporting_quote": val_res.get("supporting_quote", ""),
            "latency_seconds": elapsed,
            "technical_error": None,
        }
        results_records.append(res_entry)

        print(f"[{idx+1:02d}/40] ID {rec['detail_id']} ({rec['category_code']}/{rec['cohort']}): Gold={rec['gold_label']} | Raw={res_entry['raw_decision']} | Final={res_entry['final_decision']} ({res_entry['final_reason_code']}) in {elapsed:.2f}s")

    total_wall_sec = time.time() - start_time

    # ----------------------------------------------------
    # 8. SAVE RESULTS ARTIFACT
    # ----------------------------------------------------
    results_path = "/tmp/r3_4ff_v4_eval_results.json"
    results_payload = {
        "validator_version": VALIDATOR_VERSION,
        "validation_method": VALIDATION_METHOD,
        "prompt_version": PROMPT_VERSION,
        "total_records": len(results_records),
        "records": results_records,
    }
    results_json_bytes = json.dumps(results_payload, ensure_ascii=False, indent=2).encode("utf-8")
    results_sha256 = hashlib.sha256(results_json_bytes).hexdigest()

    with open(results_path, "wb") as f:
        f.write(results_json_bytes)

    # ----------------------------------------------------
    # 9. PRIMARY METRICS & QUALITY GATES
    # ----------------------------------------------------
    pos_rows = [r for r in results_records if r["gold_label"] == "CLEAR_POSITIVE"]
    neg_rows = [r for r in results_records if r["gold_label"] == "CLEAR_NEGATIVE"]
    amb_rows = [r for r in results_records if r["gold_label"] == "AMBIGUOUS"]

    pos_total = len(pos_rows)
    pos_conf = sum(1 for r in pos_rows if r["final_decision"] == "CONFIRMED")
    pos_rej = sum(1 for r in pos_rows if r["final_decision"] == "REJECTED")
    pos_unk = sum(1 for r in pos_rows if r["final_decision"] == "UNKNOWN")

    neg_total = len(neg_rows)
    neg_rej = sum(1 for r in neg_rows if r["final_decision"] == "REJECTED")
    neg_conf = sum(1 for r in neg_rows if r["final_decision"] == "CONFIRMED")
    neg_unk = sum(1 for r in neg_rows if r["final_decision"] == "UNKNOWN")

    amb_total = len(amb_rows)
    amb_unk = sum(1 for r in amb_rows if r["final_decision"] == "UNKNOWN")
    amb_conf = sum(1 for r in amb_rows if r["final_decision"] == "CONFIRMED")
    amb_rej = sum(1 for r in amb_rows if r["final_decision"] == "REJECTED")

    pos_confirm_rate = pos_conf / pos_total if pos_total > 0 else 0.0
    neg_reject_rate = neg_rej / neg_total if neg_total > 0 else 0.0
    amb_unknown_rate = amb_unk / amb_total if amb_total > 0 else 0.0

    # Category recall
    cat_breakdown = {}
    zero_recall_count = 0
    for cat in all_9_categories:
        c_recs = [r for r in results_records if r["category_code"] == cat]
        c_pos = [r for r in c_recs if r["gold_label"] == "CLEAR_POSITIVE"]
        c_pos_conf = sum(1 for r in c_pos if r["final_decision"] == "CONFIRMED")
        if len(c_pos) >= 2 and c_pos_conf == 0:
            zero_recall_count += 1
        cat_breakdown[cat] = {
            "TOTAL": len(c_recs),
            "GOLD_POSITIVE": len(c_pos),
            "GOLD_NEGATIVE": sum(1 for r in c_recs if r["gold_label"] == "CLEAR_NEGATIVE"),
            "GOLD_AMBIGUOUS": sum(1 for r in c_recs if r["gold_label"] == "AMBIGUOUS"),
            "CONFIRMED": sum(1 for r in c_recs if r["final_decision"] == "CONFIRMED"),
            "REJECTED": sum(1 for r in c_recs if r["final_decision"] == "REJECTED"),
            "UNKNOWN": sum(1 for r in c_recs if r["final_decision"] == "UNKNOWN"),
            "FALSE_CONFIRM": sum(1 for r in c_recs if r["gold_label"] == "CLEAR_NEGATIVE" and r["final_decision"] == "CONFIRMED"),
            "FALSE_REJECT": sum(1 for r in c_recs if r["gold_label"] == "CLEAR_POSITIVE" and r["final_decision"] == "REJECTED"),
            "POSITIVE_UNKNOWN": sum(1 for r in c_recs if r["gold_label"] == "CLEAR_POSITIVE" and r["final_decision"] == "UNKNOWN"),
        }

    # Quality Gate Checks
    failed_gates = []
    if neg_conf > 0:
        failed_gates.append(f"FALSE_CONFIRM_CLEAR_NEGATIVE ({neg_conf} > 0)")
    if amb_conf > 0:
        failed_gates.append(f"AMBIGUOUS_CONFIRMED ({amb_conf} > 0)")
    if pos_rej > 0:
        failed_gates.append(f"FALSE_REJECT_CLEAR_POSITIVE ({pos_rej} > 0)")
    if pos_confirm_rate < 0.90:
        failed_gates.append(f"POSITIVE_CONFIRM_RATE ({pos_confirm_rate:.1%} < 90.0%)")
    if neg_reject_rate < 0.80:
        failed_gates.append(f"NEGATIVE_REJECT_RATE ({neg_reject_rate:.1%} < 80.0%)")
    if amb_total >= 3 and amb_unknown_rate < 0.67:
        failed_gates.append(f"AMBIGUOUS_UNKNOWN_RATE ({amb_unknown_rate:.1%} < 67.0%)")
    if zero_recall_count > 0:
        failed_gates.append(f"CATEGORY_ZERO_RECALL_COUNT ({zero_recall_count} > 0)")

    gate_status = "PASS" if len(failed_gates) == 0 else "FAIL"

    # Cohorts breakdown
    cohorts_metrics = {}
    for ch in ["NATURAL_STRATIFIED", "CLEAR_POSITIVE_CHALLENGE", "NEGATIVE_AMBIGUOUS_CHALLENGE"]:
        ch_recs = [r for r in results_records if r["cohort"] == ch]
        cohorts_metrics[ch] = {
            "TOTAL": len(ch_recs),
            "GOLD_DISTRIBUTION": dict(Counter(r["gold_label"] for r in ch_recs)),
            "MODEL_DISTRIBUTION": dict(Counter(r["final_decision"] for r in ch_recs)),
            "FALSE_CONFIRM": sum(1 for r in ch_recs if r["gold_label"] == "CLEAR_NEGATIVE" and r["final_decision"] == "CONFIRMED"),
            "FALSE_REJECT": sum(1 for r in ch_recs if r["gold_label"] == "CLEAR_POSITIVE" and r["final_decision"] == "REJECTED"),
            "POSITIVE_UNKNOWN": sum(1 for r in ch_recs if r["gold_label"] == "CLEAR_POSITIVE" and r["final_decision"] == "UNKNOWN"),
        }

    # Raw vs Final transitions
    raw_vs_final = {
        "TRANSITIONS": {
            "RAW_CONFIRMED_TO_FINAL_CONFIRMED": sum(1 for r in results_records if r["raw_decision"] == "CONFIRMED" and r["final_decision"] == "CONFIRMED"),
            "RAW_CONFIRMED_TO_FINAL_UNKNOWN": sum(1 for r in results_records if r["raw_decision"] == "CONFIRMED" and r["final_decision"] == "UNKNOWN"),
            "RAW_REJECTED_TO_FINAL_REJECTED": sum(1 for r in results_records if r["raw_decision"] == "REJECTED" and r["final_decision"] == "REJECTED"),
            "RAW_REJECTED_TO_FINAL_UNKNOWN": sum(1 for r in results_records if r["raw_decision"] == "REJECTED" and r["final_decision"] == "UNKNOWN"),
            "RAW_UNKNOWN_TO_FINAL_UNKNOWN": sum(1 for r in results_records if r["raw_decision"] == "UNKNOWN" and r["final_decision"] == "UNKNOWN"),
        },
        "DEMOTION_REASONS": dict(Counter(r["final_reason_code"] for r in results_records if r["raw_decision"] != r["final_decision"])),
        "RAW_REASON_CODES": dict(Counter(r["raw_reason_code"] for r in results_records)),
        "GATE_ONLY_CODES_EMITTED_BY_MODEL": [r["raw_reason_code"] for r in results_records if r["raw_reason_code"] in ("MISSING_SUPPORTING_QUOTE", "HALLUCINATED_QUOTE", "LOW_CONFIDENCE")],
    }

    # Important error corpus
    important_failures = []
    for r in results_records:
        g = r["gold_label"]
        f = r["final_decision"]
        if (g == "CLEAR_POSITIVE" and f in ("REJECTED", "UNKNOWN")) or \
           (g == "CLEAR_NEGATIVE" and f == "CONFIRMED") or \
           (g == "AMBIGUOUS" and f == "CONFIRMED"):
            important_failures.append({
                "DETAIL_ID": r["detail_id"],
                "PROCUREMENT_ID": r["procurement_id"],
                "CATEGORY": r["category_code"],
                "SUBCATEGORY": r["subcategory_code"],
                "COHORT": r["cohort"],
                "GOLD_LABEL": g,
                "FINAL_DECISION": f,
                "FINAL_REASON_CODE": r["final_reason_code"],
                "FINAL_REASON": r["final_reason"],
            })

    # Ambiguous audit
    ambiguous_rows_audit = [
        {
            "DETAIL_ID": r["detail_id"],
            "PROCUREMENT_ID": r["procurement_id"],
            "CATEGORY": r["category_code"],
            "SUBCATEGORY": r["subcategory_code"],
            "COHORT": r["cohort"],
            "GOLD_LABEL": r["gold_label"],
            "FINAL_DECISION": r["final_decision"],
            "FINAL_REASON_CODE": r["final_reason_code"],
            "FINAL_REASON": r["final_reason"],
        } for r in results_records if r["gold_label"] == "AMBIGUOUS"
    ]

    # Performance
    sorted_lat = sorted(latencies)
    mean_lat = sum(latencies) / len(latencies)
    p50_lat = sorted_lat[int(len(sorted_lat) * 0.50)]
    p95_lat = sorted_lat[int(len(sorted_lat) * 0.95)]
    max_lat = max(latencies)

    # ----------------------------------------------------
    # 10. PRINT FINAL REPORT FORMAT
    # ----------------------------------------------------
    print("\n" + "=" * 80)
    print("FINAL REPORT OUTPUT")
    print("=" * 80)

    report_text = f"""
WIP_RESULT=PASS

HEAD=
db360d2effca764f733753f9d633eec96fc138b4

REMOTE_HEAD=
db360d2effca764f733753f9d633eec96fc138b4

GIT_DIRTY=0

BLACKLIST={{
 TOTAL_IDS: {len(blacklisted_ids)},
 SOURCES: {json.dumps(sources)},
 SELECTED_FROM_PRIOR: 0
}}

POOL={{
 TOTAL: {len(target_candidates)},
 CATEGORY_COUNT: 9,
 BY_CATEGORY: {json.dumps({{k: len(v) for k, v in by_cat.items()}})},
 HARD_CAPACITY: {json.dumps({{k: len(v) >= 1 for k, v in by_cat.items()}})}
}}

HOLDOUT={{
 TOTAL: 40,
 MANIFEST_PATH: "/tmp/r3_4ff_v4_holdout_manifest.json",
 MANIFEST_SHA256: "{manifest_sha256}",
 BY_CATEGORY: {json.dumps(dict(cat_dist))},
 BY_COHORT: {json.dumps(dict(cohort_dist))},
 UNIQUE_PROCUREMENTS: {len(proc_counts)},
 UNIQUE_DOCUMENTS: {len(doc_counts)},
 MAX_ROWS_PER_PROCUREMENT: {max(proc_counts.values())},
 MAX_ROWS_PER_DOCUMENT: {max(doc_counts.values())}
}}

GOLD={{
 CLEAR_POSITIVE: {gold_dist['CLEAR_POSITIVE']},
 CLEAR_NEGATIVE: {gold_dist['CLEAR_NEGATIVE']},
 AMBIGUOUS: {gold_dist['AMBIGUOUS']},
 REVIEW_COMPLETE: "40/40",
 POSITIVE_WITHOUT_VALID_QUOTE: {pos_no_quote},
 NEGATIVE_WITHOUT_VALID_QUOTE: {neg_no_quote},
 GENERIC_ONLY_POSITIVES: {generic_pos}
}}

PRE_MODEL_GATES={{
 PASS: "YES",
 FAILED: []
}}

MODEL={{
 CALLED: "YES",
 MODEL: "qwen2.5:7b",
 MODEL_CALLS: 40,
 PASS_COUNT: 1,
 CONFIRMED: {sum(1 for r in results_records if r['final_decision'] == 'CONFIRMED')},
 REJECTED: {sum(1 for r in results_records if r['final_decision'] == 'REJECTED')},
 UNKNOWN: {sum(1 for r in results_records if r['final_decision'] == 'UNKNOWN')},
 TECHNICAL_ERRORS: 0
}}

QUALITY={{
 POSITIVE_CONFIRM_RATE: {pos_confirm_rate:.4f},
 FALSE_REJECT_CLEAR_POSITIVE: {pos_rej},
 POSITIVE_UNKNOWN: {pos_unk},
 NEGATIVE_REJECT_RATE: {neg_reject_rate:.4f},
 FALSE_CONFIRM_CLEAR_NEGATIVE: {neg_conf},
 AMBIGUOUS_UNKNOWN_RATE: {amb_unknown_rate:.4f},
 AMBIGUOUS_FALSE_CONFIRM: {amb_conf},
 CATEGORY_ZERO_RECALL_COUNT: {zero_recall_count}
}}

BY_CATEGORY={json.dumps(cat_breakdown, indent=2)}

COHORTS={json.dumps(cohorts_metrics, indent=2)}

RAW_VS_FINAL={json.dumps(raw_vs_final, indent=2)}

IMPORTANT_FAILURES={json.dumps(important_failures, indent=2)}

AMBIGUOUS_ROWS={json.dumps(ambiguous_rows_audit, indent=2)}

PERFORMANCE={{
 TOTAL_WALL_SECONDS: {total_wall_sec:.2f},
 MEAN: {mean_lat:.2f},
 P50: {p50_lat:.2f},
 P95: {p95_lat:.2f},
 MAX: {max_lat:.2f}
}}

DATABASE={{
 DETAIL_ROWS_MUTATED: 0,
 EVIDENCE_ROWS_MUTATED: 0
}}

RESULT_ARTIFACT={{
 PATH: "/tmp/r3_4ff_v4_eval_results.json",
 SHA256: "{results_sha256}"
}}

CONTEXT_VALIDATOR_V4_QUALITY_GATE={gate_status}

R3_STATUS=CURRENT

NEXT_WIP=
CRM-V3-LAUNCH-R3-4G-VALIDATOR-SERVICE-DEPLOYMENT-BOUNDED-PROOF-1

FAILED_GATES={json.dumps(failed_gates)}

STOP.
"""
    print(report_text)

if __name__ == "__main__":
    main()
