#!/usr/bin/env python3
"""
R3-4F-F Fresh V4 Holdout Full Verification Script.
"""

import os
import sys
import json
import glob
import time
import hashlib
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
        # Verify it's not a specification line
        if not any(w in text_low for w in ["светильник", "прожектор", "гидроизоляц", "мастика", "мембрана", "техноэласт", "пенетрон", "линолеум", "ламинат", "плитка", "дождеприемник", "лоток", "труба", "арматура"]):
            # Extract clean quote
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
        # Extract quote around key term
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
    blacklisted_ids = set(range(35176, 35276))
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
                            blacklisted_ids.add(int(item["detail_id"]))
                            sources[os.path.basename(p)] = sources.get(os.path.basename(p), 0) + 1
            except Exception:
                pass

    print(f"[STEP 1] Union Blacklist Total: {len(blacklisted_ids)} IDs")

    doc_conn = get_doc_db_connection()
    crm_conn = get_crm_db_connection()

    with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT commercial_category_code, okpd_pattern, match_type, prior_weight, active FROM crm_category_okpd_priors WHERE active = TRUE")
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
        c["gold_quote"] = g_q
        c["gold_reason"] = g_r
        c["gold_classes"] = g_cls

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

    print("\nCandidate Population by Gold Label:")
    for cat in all_9_categories:
        items = by_cat[cat]
        pos_cnt = sum(1 for x in items if x["gold_label"] == "CLEAR_POSITIVE")
        neg_cnt = sum(1 for x in items if x["gold_label"] == "CLEAR_NEGATIVE")
        amb_cnt = sum(1 for x in items if x["gold_label"] == "AMBIGUOUS")
        print(f"  {cat:32s}: Total={len(items):4d} | Pos={pos_cnt:4d} | Neg={neg_cnt:4d} | Amb={amb_cnt:4d}")

    # Build exact holdout selection
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

    def add_c(c, cohort):
        pid = c["procurement_id"]
        doc = c["document_name"]
        cat = c["category_code"]
        selected_ids.add(c["detail_id"])
        proc_counts[pid] = proc_counts.get(pid, 0) + 1
        doc_counts[doc] = doc_counts.get(doc, 0) + 1
        cat_counts[cat] += 1
        r = dict(c)
        r["cohort"] = cohort
        selected_rows.append(r)

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
                add_c(c, "NATURAL_STRATIFIED")
                break

    # Pass 2: fill to 16
    for c in hash_sorted:
        if len(selected_rows) >= 16:
            break
        if can_add(c, max_cat=4):
            add_c(c, "NATURAL_STRATIFIED")

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
                add_c(c, "CLEAR_POSITIVE_CHALLENGE")
                b_added += 1
                break

    for c in pool_pos:
        if b_added >= 12:
            break
        if can_add(c, max_cat=6):
            add_c(c, "CLEAR_POSITIVE_CHALLENGE")
            b_added += 1

    assert b_added == 12, f"Cohort B count = {b_added}"

    # --- Cohort C: NEGATIVE AMBIGUOUS CHALLENGE (12) ---
    # We select 8 CLEAR_NEGATIVE and 4 AMBIGUOUS to guarantee >= 6 CLEAR_NEGATIVE and >= 3 AMBIGUOUS
    pool_neg = [c for c in target_candidates if c["detail_id"] not in selected_ids and c["gold_label"] == "CLEAR_NEGATIVE"]
    pool_amb = [c for c in target_candidates if c["detail_id"] not in selected_ids and c["gold_label"] == "AMBIGUOUS"]

    c_added = 0
    c_neg = 0
    c_amb = 0

    # Pick 8 negatives
    for c in pool_neg:
        if c_neg >= 8:
            break
        if can_add(c, max_cat=6):
            add_c(c, "NEGATIVE_AMBIGUOUS_CHALLENGE")
            c_added += 1
            c_neg += 1

    # Pick 4 ambiguous
    for c in pool_amb:
        if c_amb >= 4 or c_added >= 12:
            break
        if can_add(c, max_cat=6):
            add_c(c, "NEGATIVE_AMBIGUOUS_CHALLENGE")
            c_added += 1
            c_amb += 1

    # Fill if needed
    for c in pool_neg + pool_amb:
        if c_added >= 12:
            break
        if can_add(c, max_cat=6):
            add_c(c, "NEGATIVE_AMBIGUOUS_CHALLENGE")
            c_added += 1

    assert c_added == 12, f"Cohort C count = {c_added}"
    assert len(selected_rows) == 40, f"Total selected count = {len(selected_rows)}"

    # Audit final 40 selection
    c_dist = Counter(r["cohort"] for r in selected_rows)
    g_dist = Counter(r["gold_label"] for r in selected_rows)
    cat_dist = Counter(r["category_code"] for r in selected_rows)

    print("\n--- FINAL HOLDOUT SUMMARY (40 ROWS) ---")
    print(f"Cohort Breakdown: {c_dist}")
    print(f"Gold Label Breakdown: {g_dist}")
    print(f"Category Breakdown: {cat_dist}")
    print(f"Unique Procurements: {len(proc_counts)} (Max per proc = {max(proc_counts.values())})")
    print(f"Unique Documents: {len(doc_counts)} (Max per doc = {max(doc_counts.values())})")

    # Assert pre-model hard gates
    assert len(selected_rows) == 40
    assert len(cat_dist) == 9
    assert max(cat_dist.values()) <= 6
    assert max(proc_counts.values()) <= 3
    assert max(doc_counts.values()) <= 2
    assert len(proc_counts) >= 18
    assert len(doc_counts) >= 25
    assert g_dist["CLEAR_POSITIVE"] >= 12
    assert g_dist["CLEAR_NEGATIVE"] >= 6
    assert g_dist["AMBIGUOUS"] >= 3

    print("\nPRE-MODEL HARD GATES ASSERTS PASSED PERFECTLY!")

if __name__ == "__main__":
    main()
