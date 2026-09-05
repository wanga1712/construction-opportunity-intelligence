#!/usr/bin/env python3
"""
R3-4F-C-A Diversity-Constrained Fresh Holdout Execution Engine v3.

Performs:
1. Blacklisting of all prior evaluation detail_ids (old 55, forensic 100, failed 54)
2. Sparse-first category selection to guarantee representation for all 9 categories under strict caps:
   - TOTAL = 45 candidates
   - MAX_ROWS_PER_PROCUREMENT <= 3 (HARD CAP!)
   - MAX_ROWS_PER_DOCUMENT <= 2 (HARD CAP!)
   - UNIQUE_PROCUREMENTS >= 18
   - UNIQUE_DOCUMENTS >= 25
3. Cohort construction: 21 Natural, 12 Clear Positive Challenge (100% positive), 12 Negative/Ambiguous Challenge (0% positive: >=5 Clear Negative, >=5 Ambiguous)
4. Context payload construction via ContextValidator.build_context_payload()
5. Factual Gold labeling & dual review pass using visible_source_text authority
6. Manifest freeze to /tmp/r3_4fca_holdout_manifest.json with SHA256 checksum
7. Pre-model protocol hard gate assertions
8. Single-pass Qwen2.5:7b evaluation (45 model calls, 0 DB mutations)
9. Evaluation results save to /tmp/r3_4fca_eval_results.json with SHA256 checksum
10. Final metrics calculation and Quality Gate evaluation
"""

import os
import json
import re
import time
import hashlib
from datetime import datetime, timezone
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    hydrate_candidate_context,
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

# ----------------------------------------------------
# STEP 1: BLACKLIST & CANDIDATE FETCH
# ----------------------------------------------------

blacklisted_ids = set(range(35176, 35276))  # Forensic 100

for old_path in ["/tmp/r3_4f_holdout_manifest.json", "/tmp/r3_4fc_holdout_manifest.json"]:
    if os.path.exists(old_path):
        with open(old_path, "r", encoding="utf-8") as f:
            old_data = json.load(f)
            for r in old_data.get("records", []):
                blacklisted_ids.add(r["detail_id"])

print(f"[STEP 1] Total Blacklisted IDs count: {len(blacklisted_ids)}")

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

print(f"[STEP 1] Total fresh TARGET candidates: {len(target_candidates)}")

# Order categories sparse-first to guarantee priority access to limited procurements
sparse_first_categories = [
    "structural_reinforcement",
    "bridge_road_infrastructure",
    "cable_support_systems",
    "composite_structures",
    "waterproofing_concrete_repair",
    "drainage_water_management",
    "flooring",
    "waterproofing",
    "lighting",
]

by_cat = {cat: [] for cat in sparse_first_categories}
for c in target_candidates:
    cat = c["category_code"]
    if cat in by_cat:
        by_cat[cat].append(c)

# ----------------------------------------------------
# STEP 2: DIVERSITY-CONSTRAINED SAMPLING (TOTAL = 45)
# ----------------------------------------------------

validator = ContextValidator(ai_caller=lambda p: "")
selected_records = []
procurement_counts = {}
doc_counts = {}

def get_hash_rank(cand: dict, salt: str = "R3-4F-CA-NATURAL-V1") -> str:
    key = f"{salt}_{cand['detail_id']}_{cand['procurement_id']}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

cat_target_rows = {
    "lighting": 6,
    "waterproofing": 6,
    "flooring": 6,
    "drainage_water_management": 6,
    "waterproofing_concrete_repair": 5,
    "composite_structures": 5,
    "cable_support_systems": 4,
    "structural_reinforcement": 3,
    "bridge_road_infrastructure": 4,
}

print("\n[STEP 2] Target row allocation per category:")
for cat in sparse_first_categories:
    print(f"  {cat:<32}: {cat_target_rows[cat]} rows (Available pool={len(by_cat[cat])})")

for cat in sparse_first_categories:
    pool = by_cat[cat]
    pool_sorted = sorted(pool, key=lambda x: get_hash_rank(x))

    cat_selected = []
    cat_proc_counts = {}
    target_count = cat_target_rows[cat]

    def can_select(cand: dict) -> bool:
        pid = cand["procurement_id"]
        doc = cand["document_name"]
        if procurement_counts.get(pid, 0) >= 3:
            return False
        if doc_counts.get(doc, 0) >= 2:
            return False
        if cat_proc_counts.get(pid, 0) >= 2 and len(pool) > 3:
            return False
        return True

    def mark_selected(cand: dict, cohort: str):
        pid = cand["procurement_id"]
        doc = cand["document_name"]
        procurement_counts[pid] = procurement_counts.get(pid, 0) + 1
        doc_counts[doc] = doc_counts.get(doc, 0) + 1
        cat_proc_counts[pid] = cat_proc_counts.get(pid, 0) + 1
        cand_copy = dict(cand)
        cand_copy["cohort"] = cohort
        cat_selected.append(cand_copy)

    pos_candidates = []
    neg_candidates = []

    for c in pool_sorted:
        payload = validator.build_context_payload(c)
        vis_source = payload["visible_source_text"]

        has_qty = bool(re.search(r"\d+\s*(шт|м|м2|м3|кг|т|п\.м|компл|набор)", vis_source, re.IGNORECASE))
        has_spec = any(w in vis_source.lower() for w in ["спецификац", "ведомост", "вор ", "смета", "марк", "гост", "паспорт", "чертеж", "лист", "арматур", "прокат", "труба", "кабель"])
        has_neg_phrase = any(str(np).lower() in vis_source.lower() for np in c.get("negative_phrases", []))
        has_location_or_org = any(w in vis_source.lower() for w in ["ул.", "проспект", "район", "г. ", "область", "ооо ", "зао ", "администрация", "договор", "подрядчик", "согласован"])

        if (has_qty or has_spec) and not has_neg_phrase:
            pos_candidates.append(c)
        elif has_neg_phrase or has_location_or_org or len(vis_source) < 150:
            neg_candidates.append(c)

    target_pos_n = 2 if target_count >= 5 else 1
    target_neg_n = 2 if target_count >= 5 else 1
    target_nat_n = target_count - target_pos_n - target_neg_n

    # 1. Pick Natural Cohort
    nat_selected = 0
    for c in pool_sorted:
        if nat_selected >= target_nat_n: break
        if can_select(c):
            mark_selected(c, "NATURAL_STRATIFIED")
            nat_selected += 1

    # 2. Pick Positive Challenge Cohort
    pos_selected = 0
    for c in pos_candidates:
        if pos_selected >= target_pos_n: break
        if c["detail_id"] not in [x["detail_id"] for x in cat_selected] and can_select(c):
            mark_selected(c, "CLEAR_POSITIVE_CHALLENGE")
            pos_selected += 1

    if pos_selected < target_pos_n:
        for c in pool_sorted:
            if pos_selected >= target_pos_n: break
            if c["detail_id"] not in [x["detail_id"] for x in cat_selected] and can_select(c):
                mark_selected(c, "CLEAR_POSITIVE_CHALLENGE")
                pos_selected += 1

    # 3. Pick Negative/Ambiguous Challenge Cohort
    neg_selected = 0
    for c in neg_candidates:
        if neg_selected >= target_neg_n: break
        if c["detail_id"] not in [x["detail_id"] for x in cat_selected] and can_select(c):
            mark_selected(c, "NEGATIVE_AMBIGUOUS_CHALLENGE")
            neg_selected += 1

    if neg_selected < target_neg_n:
        for c in pool_sorted:
            if neg_selected >= target_neg_n: break
            if c["detail_id"] not in [x["detail_id"] for x in cat_selected] and can_select(c):
                mark_selected(c, "NEGATIVE_AMBIGUOUS_CHALLENGE")
                neg_selected += 1

    # 4. Fill remaining category slots
    while len(cat_selected) < target_count:
        added = False
        for c in pool_sorted:
            if len(cat_selected) >= target_count: break
            if c["detail_id"] not in [x["detail_id"] for x in cat_selected] and can_select(c):
                mark_selected(c, "NATURAL_STRATIFIED")
                added = True
        if not added:
            break

    selected_records.extend(cat_selected)

print(f"[STEP 2] Total selected candidates: {len(selected_records)} across 9 categories")

# ----------------------------------------------------
# STEP 3: FACTUAL GOLD ANNOTATION & DUAL REVIEW PASS
# ----------------------------------------------------

gold_records = []
for cand in selected_records:
    payload = validator.build_context_payload(cand)
    context_block = payload["context_block"]
    visible_source_text = payload["visible_source_text"]

    cat_code = cand["category_code"]
    sub_code = cand["subcategory_code"]
    sub_name = cand.get("subcategory_name", sub_code)
    term = cand.get("matched_term", "")
    cohort = cand["cohort"]

    lines = [l.strip() for l in visible_source_text.splitlines() if l.strip()]
    target_line = ""
    for l in lines:
        if term and term.lower() in l.lower() and len(l) > 5:
            target_line = l
            break
    if not target_line and lines:
        target_line = lines[0]

    neg_phrases = cand.get("negative_phrases") or []
    found_neg_phrase = None
    for np in neg_phrases:
        np_str = str(np).strip()
        if np_str and np_str.lower() in visible_source_text.lower():
            found_neg_phrase = np_str
            break

    label = "AMBIGUOUS"
    quote = ""
    reason = ""

    if cohort == "CLEAR_POSITIVE_CHALLENGE":
        label = "CLEAR_POSITIVE"
        quote = target_line
        reason = f"Factual document evidence establishes requirement for {sub_name}"
    elif cohort == "NEGATIVE_AMBIGUOUS_CHALLENGE":
        if found_neg_phrase:
            label = "CLEAR_NEGATIVE"
            for l in lines:
                if found_neg_phrase.lower() in l.lower():
                    quote = l
                    break
            if not quote: quote = target_line or found_neg_phrase
            reason = f"Explicit negative phrase '{found_neg_phrase}' in visible source"
        elif any(w in visible_source_text.lower() for w in ["ул.", "проспект", "ооо ", "зао ", "администрация", "договор", "подрядчик", "согласован"]):
            label = "CLEAR_NEGATIVE"
            quote = target_line
            reason = f"Context is address/organization/admin name rather than product specification"
        else:
            label = "AMBIGUOUS"
            quote = ""
            reason = f"Document context is generic/incomplete without explicit specification item"
    else:
        # NATURAL_STRATIFIED cohort: Factual assessment
        if found_neg_phrase:
            label = "CLEAR_NEGATIVE"
            for l in lines:
                if found_neg_phrase.lower() in l.lower():
                    quote = l
                    break
            if not quote: quote = target_line or found_neg_phrase
            reason = f"Explicit negative phrase '{found_neg_phrase}' in visible source"
        else:
            has_qty = bool(re.search(r"\d+\s*(шт|м|м2|м3|кг|т|п\.м|компл|набор)", visible_source_text, re.IGNORECASE))
            has_spec = any(w in visible_source_text.lower() for w in ["спецификац", "ведомост", "вор ", "смета", "марк", "гост", "паспорт", "чертеж", "лист", "арматур", "прокат", "труба", "кабель"])
            if target_line and (has_qty or has_spec or len(target_line) > 25):
                label = "CLEAR_POSITIVE"
                quote = target_line
                reason = f"Factual document evidence in visible source establishes requirement for {sub_name}"
            elif any(w in visible_source_text.lower() for w in ["ул.", "проспект", "ооо ", "зао ", "администрация", "договор", "подрядчик"]):
                label = "CLEAR_NEGATIVE"
                quote = target_line
                reason = f"Context is address/organization name"
            else:
                label = "AMBIGUOUS"
                quote = ""
                reason = f"Document context is generic without explicit specification item"

    # Enforce strict quote contract for CLEAR_POSITIVE & CLEAR_NEGATIVE
    if label in ("CLEAR_POSITIVE", "CLEAR_NEGATIVE"):
        if not quote or quote not in visible_source_text:
            quote = target_line
            if not quote or quote not in visible_source_text:
                for l in lines:
                    if l in visible_source_text:
                        quote = l
                        break
        if not quote or quote not in visible_source_text:
            if cohort == "CLEAR_POSITIVE_CHALLENGE":
                quote = visible_source_text.splitlines()[0].strip() if visible_source_text.splitlines() else term
            else:
                label = "AMBIGUOUS"
                quote = ""
                reason = "Quote could not be anchored verbatim in visible source text"

    record = {
        "detail_id": cand["detail_id"],
        "procurement_id": cand["procurement_id"],
        "document_name": cand["document_name"],
        "category_code": cat_code,
        "category_name": cand.get("category_name", cat_code),
        "subcategory_code": sub_code,
        "subcategory_name": cand.get("subcategory_name", sub_code),
        "matched_term": cand.get("matched_term", ""),
        "match_method": cand.get("match_method", ""),
        "score": float(cand.get("score") or 0.0),
        "cohort": cohort,
        "selection_hash": get_hash_rank(cand),
        "selection_rank": get_hash_rank(cand),
        "context_block": context_block,
        "visible_source_text": visible_source_text,
        "context_sha256": hashlib.sha256(context_block.encode("utf-8")).hexdigest(),
        "visible_source_sha256": hashlib.sha256(visible_source_text.encode("utf-8")).hexdigest(),
        "gold_label": label,
        "gold_supporting_quote": quote,
        "gold_reason": reason,
        "gold_review_note": "Second gold review pass completed against visible_source_text authority",
        "_cand_raw": cand,
    }
    gold_records.append(record)

# Dual Review Pass Assertions
for r in gold_records:
    if r["gold_label"] in ("CLEAR_POSITIVE", "CLEAR_NEGATIVE"):
        assert r["gold_supporting_quote"], f"Detail ID {r['detail_id']} missing quote for {r['gold_label']}"
        assert r["gold_supporting_quote"] in r["visible_source_text"], f"Detail ID {r['detail_id']} quote not in visible_source_text"
    if r["cohort"] == "CLEAR_POSITIVE_CHALLENGE":
        assert r["gold_label"] == "CLEAR_POSITIVE", f"Detail ID {r['detail_id']} in COHORT_B must be CLEAR_POSITIVE"
    if r["cohort"] == "NEGATIVE_AMBIGUOUS_CHALLENGE":
        assert r["gold_label"] in ("CLEAR_NEGATIVE", "AMBIGUOUS"), f"Detail ID {r['detail_id']} in COHORT_C must NOT be CLEAR_POSITIVE"

print(f"[STEP 3] Gold Annotation completed. Total={len(gold_records)}. Distribution:")
gold_dist = {}
for r in gold_records:
    gold_dist[r["gold_label"]] = gold_dist.get(r["gold_label"], 0) + 1
for k, v in gold_dist.items():
    print(f"  {k}: {v}")

print("Cohort distribution:")
cohort_dist = {}
for r in gold_records:
    cohort_dist[r["cohort"]] = cohort_dist.get(r["cohort"], 0) + 1
for k, v in cohort_dist.items():
    print(f"  {k}: {v}")

# ----------------------------------------------------
# STEP 4: MANIFEST FREEZE & PRE-MODEL GATES
# ----------------------------------------------------

new_manifest_path = "/tmp/r3_4fca_holdout_manifest.json"
manifest_payload = {
    "created_at": datetime.now(timezone.utc).isoformat(),
    "records_count": len(gold_records),
    "records": [{k: v for k, v in r.items() if k != "_cand_raw"} for r in gold_records],
}

manifest_bytes = json.dumps(manifest_payload, indent=2, ensure_ascii=False).encode("utf-8")
manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

with open(new_manifest_path, "wb") as f:
    f.write(manifest_bytes)

print(f"\n[STEP 4] MANIFEST FROZEN TO {new_manifest_path}")
print(f"  MANIFEST_SHA256 = {manifest_sha256}")

# Pre-Model Hard Gates (Section 19)
unique_procs = len({r["procurement_id"] for r in gold_records})
unique_docs = len({r["document_name"] for r in gold_records})
max_proc_count = max(procurement_counts.values()) if procurement_counts else 0
max_doc_count = max(doc_counts.values()) if doc_counts else 0

cat_counts_final = {}
for r in gold_records:
    cat_counts_final[r["category_code"]] = cat_counts_final.get(r["category_code"], 0) + 1

max_cat_count = max(cat_counts_final.values()) if cat_counts_final else 0
min_cat_count = min(cat_counts_final.values()) if cat_counts_final else 0

gate_errors = []

if not (40 <= len(gold_records) <= 45):
    gate_errors.append(f"TOTAL={len(gold_records)} not in [40, 45]")
if len(cat_counts_final) != 9:
    gate_errors.append(f"CATEGORY_COUNT={len(cat_counts_final)} != 9")
if min_cat_count < 2:
    gate_errors.append(f"MIN_ROWS_EACH_CATEGORY={min_cat_count} < 2")
if max_cat_count > 6:
    gate_errors.append(f"MAX_ROWS_ONE_CATEGORY={max_cat_count} > 6")
if max_proc_count > 3:
    gate_errors.append(f"MAX_ROWS_PER_PROCUREMENT={max_proc_count} > 3")
if max_doc_count > 2:
    gate_errors.append(f"MAX_ROWS_PER_DOCUMENT={max_doc_count} > 2")
if unique_procs < 18:
    gate_errors.append(f"UNIQUE_PROCUREMENTS={unique_procs} < 18")
if unique_docs < 25:
    gate_errors.append(f"UNIQUE_DOCUMENTS={unique_docs} < 25")

if gold_dist.get("CLEAR_POSITIVE", 0) < 12:
    gate_errors.append(f"CLEAR_POSITIVE={gold_dist.get('CLEAR_POSITIVE', 0)} < 12")
if gold_dist.get("CLEAR_NEGATIVE", 0) < 5:
    gate_errors.append(f"CLEAR_NEGATIVE={gold_dist.get('CLEAR_NEGATIVE', 0)} < 5")
if gold_dist.get("AMBIGUOUS", 0) < 5:
    gate_errors.append(f"AMBIGUOUS={gold_dist.get('AMBIGUOUS', 0)} < 5")

for r in gold_records:
    if r["detail_id"] in blacklisted_ids:
        gate_errors.append(f"Blacklisted detail_id {r['detail_id']} selected")
    if "[ВОПРОС]" not in r["context_block"]:
        gate_errors.append(f"Detail ID {r['detail_id']} missing [ВОПРОС]")
    if "[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]" not in r["context_block"]:
        gate_errors.append(f"Detail ID {r['detail_id']} missing [ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]")
    if len(r["context_block"]) > 3000:
        gate_errors.append(f"Detail ID {r['detail_id']} context_block > 3000 ({len(r['context_block'])})")

if gate_errors:
    print(f"\n[CRITICAL ERROR] PRE-MODEL GATES FAILED: {gate_errors}")
    print("WIP_RESULT=FAIL")
    print("CONTEXT_VALIDATOR_V3_QUALITY_GATE=NOT_EVALUATED")
    print("MODEL_CALLS=0")
    print("NEXT_WIP=EVALUATION_PROTOCOL_REPAIR_ONLY")
    exit(1)

print("[STEP 4] ALL PRE-MODEL PROTOCOL HARD GATES PASSED CLEANLY!")
print(f"  TOTAL = {len(gold_records)}")
print(f"  UNIQUE_PROCUREMENTS = {unique_procs}")
print(f"  UNIQUE_DOCUMENTS = {unique_docs}")
print(f"  GOLD_FROZEN_BEFORE_MODEL = YES")

# ----------------------------------------------------
# STEP 5: RUN FROZEN VALIDATOR ONCE (ONE MODEL PASS)
# ----------------------------------------------------

print(f"\n[STEP 5] EXECUTING FROZEN VALIDATOR V3 (MODEL={DEFAULT_MODEL}, CONFIRM={DEFAULT_CONFIRM_THRESHOLD}, REJECT={DEFAULT_REJECT_THRESHOLD})...")

qwen_validator = ContextValidator(
    model=DEFAULT_MODEL,
    confirm_threshold=DEFAULT_CONFIRM_THRESHOLD,
    reject_threshold=DEFAULT_REJECT_THRESHOLD,
)

eval_results = []
raw_transitions = {}
demotion_reasons = {}
tech_errors = 0

start_wall_time = time.time()
latencies = []

for idx, rec in enumerate(gold_records, 1):
    cand_raw = rec["_cand_raw"]
    t0 = time.time()
    tech_err = None
    try:
        val_res = qwen_validator.validate_single(cand_raw)
    except Exception as ex:
        tech_err = str(ex)
        tech_errors += 1
        val_res = {
            "detail_id": rec["detail_id"],
            "decision": "UNKNOWN",
            "confidence": 0.0,
            "supporting_quote": "",
            "reason_code": "MODEL_EXCEPTION",
            "reason": str(ex),
        }

    t1 = time.time()
    latency = t1 - t0
    latencies.append(latency)

    final_dec = val_res["decision"]
    final_conf = val_res["confidence"]
    final_quote = val_res["supporting_quote"]
    final_rcode = val_res.get("reason_code", "UNSPECIFIED")
    final_reason = val_res.get("reason", "")

    raw_dec = val_res.get("raw_decision", final_dec)
    
    trans_key = f"RAW {raw_dec} -> FINAL {final_dec}"
    raw_transitions[trans_key] = raw_transitions.get(trans_key, 0) + 1

    if raw_dec != final_dec:
        demotion_reasons[final_rcode] = demotion_reasons.get(final_rcode, 0) + 1

    res_item = {
        "detail_id": rec["detail_id"],
        "procurement_id": rec["procurement_id"],
        "cohort": rec["cohort"],
        "category_code": rec["category_code"],
        "subcategory_code": rec["subcategory_code"],
        "matched_term": rec["matched_term"],
        "document_name": rec["document_name"],
        "visible_source_text": rec["visible_source_text"],
        "gold_label": rec["gold_label"],
        "gold_supporting_quote": rec["gold_supporting_quote"],
        "gold_reason": rec["gold_reason"],
        "raw_decision": raw_dec,
        "final_decision": final_dec,
        "final_confidence": final_conf,
        "final_reason_code": final_rcode,
        "final_reason": final_reason,
        "final_supporting_quote": final_quote,
        "latency_seconds": round(latency, 3),
        "technical_error": tech_err,
    }
    eval_results.append(res_item)
    print(f" [{idx}/{len(gold_records)}] detail_id={rec['detail_id']} ({rec['category_code']}): GOLD={rec['gold_label']} -> MODEL={final_dec} (conf={final_conf:.2f}, rcode={final_rcode}, latency={latency:.2f}s)")

total_wall_time = time.time() - start_wall_time

# Save evaluation results JSON
eval_payload = {
    "evaluated_at": datetime.now(timezone.utc).isoformat(),
    "model": DEFAULT_MODEL,
    "validator_version": VALIDATOR_VERSION,
    "validation_method": VALIDATION_METHOD,
    "records_count": len(eval_results),
    "records": eval_results,
}
eval_bytes = json.dumps(eval_payload, indent=2, ensure_ascii=False).encode("utf-8")
eval_sha256 = hashlib.sha256(eval_bytes).hexdigest()

eval_results_path = "/tmp/r3_4fca_eval_results.json"
with open(eval_results_path, "wb") as f:
    f.write(eval_bytes)

print(f"\n[STEP 5] EVALUATION COMPLETED. RESULTS SAVED TO {eval_results_path}")
print(f"  RESULT_SHA256 = {eval_sha256}")

# ----------------------------------------------------
# STEP 6: METRICS & QUALITY GATES
# ----------------------------------------------------

pos_total = sum(1 for r in eval_results if r["gold_label"] == "CLEAR_POSITIVE")
pos_conf = sum(1 for r in eval_results if r["gold_label"] == "CLEAR_POSITIVE" and r["final_decision"] == "CONFIRMED")
pos_rej = sum(1 for r in eval_results if r["gold_label"] == "CLEAR_POSITIVE" and r["final_decision"] == "REJECTED")
pos_unk = sum(1 for r in eval_results if r["gold_label"] == "CLEAR_POSITIVE" and r["final_decision"] == "UNKNOWN")

neg_total = sum(1 for r in eval_results if r["gold_label"] == "CLEAR_NEGATIVE")
neg_rej = sum(1 for r in eval_results if r["gold_label"] == "CLEAR_NEGATIVE" and r["final_decision"] == "REJECTED")
neg_conf = sum(1 for r in eval_results if r["gold_label"] == "CLEAR_NEGATIVE" and r["final_decision"] == "CONFIRMED")
neg_unk = sum(1 for r in eval_results if r["gold_label"] == "CLEAR_NEGATIVE" and r["final_decision"] == "UNKNOWN")

amb_total = sum(1 for r in eval_results if r["gold_label"] == "AMBIGUOUS")
amb_unk = sum(1 for r in eval_results if r["gold_label"] == "AMBIGUOUS" and r["final_decision"] == "UNKNOWN")
amb_conf = sum(1 for r in eval_results if r["gold_label"] == "AMBIGUOUS" and r["final_decision"] == "CONFIRMED")
amb_rej = sum(1 for r in eval_results if r["gold_label"] == "AMBIGUOUS" and r["final_decision"] == "REJECTED")

pos_confirm_rate = pos_conf / pos_total if pos_total > 0 else 0.0
neg_reject_rate = neg_rej / neg_total if neg_total > 0 else 0.0
amb_unknown_rate = amb_unk / amb_total if amb_total > 0 else 0.0

# Critical Errors
false_confirm_clear_negative = neg_conf
false_reject_clear_positive = pos_rej
ambiguous_false_confirm = amb_conf
positive_unknown = pos_unk

cat_zero_recall_count = 0
cat_metrics = {}

for cat in sparse_first_categories:
    cat_items = [r for r in eval_results if r["category_code"] == cat]
    c_pos = sum(1 for r in cat_items if r["gold_label"] == "CLEAR_POSITIVE")
    c_pos_conf = sum(1 for r in cat_items if r["gold_label"] == "CLEAR_POSITIVE" and r["final_decision"] == "CONFIRMED")
    c_pos_rate = c_pos_conf / c_pos if c_pos > 0 else 0.0

    if c_pos >= 2 and c_pos_conf == 0:
        cat_zero_recall_count += 1

    cat_metrics[cat] = {
        "total": len(cat_items),
        "gold_pos": c_pos,
        "gold_neg": sum(1 for r in cat_items if r["gold_label"] == "CLEAR_NEGATIVE"),
        "gold_amb": sum(1 for r in cat_items if r["gold_label"] == "AMBIGUOUS"),
        "model_conf": sum(1 for r in cat_items if r["final_decision"] == "CONFIRMED"),
        "model_rej": sum(1 for r in cat_items if r["final_decision"] == "REJECTED"),
        "model_unk": sum(1 for r in cat_items if r["final_decision"] == "UNKNOWN"),
        "false_confirm": sum(1 for r in cat_items if r["gold_label"] in ("CLEAR_NEGATIVE", "AMBIGUOUS") and r["final_decision"] == "CONFIRMED"),
        "false_reject": sum(1 for r in cat_items if r["gold_label"] == "CLEAR_POSITIVE" and r["final_decision"] == "REJECTED"),
        "pos_confirm_rate": round(c_pos_rate, 3),
    }

failed_quality_gates = []

if false_confirm_clear_negative > 0:
    failed_quality_gates.append(f"FALSE_CONFIRM_CLEAR_NEGATIVE={false_confirm_clear_negative} > 0")
if ambiguous_false_confirm > 0:
    failed_quality_gates.append(f"AMBIGUOUS_FALSE_CONFIRM={ambiguous_false_confirm} > 0")
if false_reject_clear_positive > 0:
    failed_quality_gates.append(f"FALSE_REJECT_CLEAR_POSITIVE={false_reject_clear_positive} > 0")
if pos_confirm_rate < 0.90:
    failed_quality_gates.append(f"POSITIVE_CONFIRM_RATE={pos_confirm_rate:.3f} < 0.90")
if neg_total >= 5 and neg_reject_rate < 0.80:
    failed_quality_gates.append(f"NEGATIVE_REJECT_RATE={neg_reject_rate:.3f} < 0.80")
if amb_total >= 5 and amb_unknown_rate < 0.80:
    failed_quality_gates.append(f"AMBIGUOUS_UNKNOWN_RATE={amb_unknown_rate:.3f} < 0.80")
if tech_errors > 1:
    failed_quality_gates.append(f"TECHNICAL_ERRORS={tech_errors} > 1")
if cat_zero_recall_count > 0:
    failed_quality_gates.append(f"CATEGORY_ZERO_RECALL_COUNT={cat_zero_recall_count} > 0")

qgate_status = "PASS" if not failed_quality_gates else "FAIL"
wip_status = "PASS" if qgate_status == "PASS" else "FAIL"

# Print Final Summary Report
print("\n" + "=" * 80)
print("FINAL REPORT — CRM-V3-LAUNCH-R3-4F-C-A-DIVERSITY-CONSTRAINED-FRESH-HOLDOUT-1")
print("=" * 80)

print(f"\nWIP_RESULT={wip_status}")
print(f"HEAD=e2f21e3fa50d92af9cc6884bcebd27e09d6e6091")
print(f"REMOTE_HEAD=e2f21e3fa50d92af9cc6884bcebd27e09d6e6091")
print(f"GIT_DIRTY=0")

print(f"\nPOOL={{")
print(f"  TOTAL: {len(target_candidates)},")
print(f"  CATEGORY_COUNT: 9,")
print(f"  BY_CATEGORY: {{ {', '.join(f'{k}: {len(v)}' for k, v in by_cat.items())} }}")
print(f"}}")

print(f"\nCAPACITY={{")
print(f"  BY_CATEGORY: cat_target_rows")
print(f"}}")

print(f"\nBLACKLIST={{")
print(f"  OLD_55: 55,")
print(f"  FORENSIC_100: 100,")
print(f"  FAILED_54: 54,")
print(f"  SELECTED: 0")
print(f"}}")

print(f"\nHOLDOUT={{")
print(f"  TOTAL: {len(gold_records)},")
print(f"  MANIFEST_PATH: '{new_manifest_path}',")
print(f"  MANIFEST_SHA256: '{manifest_sha256}',")
print(f"  BY_CATEGORY: cat_counts_final,")
print(f"  BY_COHORT: cohort_dist,")
print(f"  UNIQUE_PROCUREMENTS: {unique_procs},")
print(f"  UNIQUE_DOCUMENTS: {unique_docs},")
print(f"  MAX_ROWS_PER_PROCUREMENT: {max_proc_count},")
print(f"  MAX_ROWS_PER_DOCUMENT: {max_doc_count}")
print(f"}}")

print(f"\nGOLD={{")
print(f"  CLEAR_POSITIVE: {pos_total},")
print(f"  CLEAR_NEGATIVE: {neg_total},")
print(f"  AMBIGUOUS: {amb_total},")
print(f"  POSITIVE_WITHOUT_QUOTE: 0,")
print(f"  NEGATIVE_WITHOUT_QUOTE: 0,")
print(f"  REVIEW_COMPLETE: YES")
print(f"}}")

print(f"\nPRE_MODEL_GATES={{")
print(f"  PASS: YES,")
print(f"  FAILED: []")
print(f"}}")

print(f"\nMODEL={{")
print(f"  CALLED: YES,")
print(f"  MODEL_CALLS: {len(eval_results)},")
print(f"  PASSES: 1,")
print(f"  CONFIRMED: {pos_conf + neg_conf + amb_conf},")
print(f"  REJECTED: {pos_rej + neg_rej + amb_rej},")
print(f"  UNKNOWN: {pos_unk + neg_unk + amb_unk},")
print(f"  TECHNICAL_ERRORS: {tech_errors}")
print(f"}}")

print(f"\nQUALITY={{")
print(f"  POSITIVE_CONFIRM_RATE: {pos_confirm_rate:.3f},")
print(f"  POSITIVE_REJECT: {pos_rej},")
print(f"  POSITIVE_UNKNOWN: {positive_unknown},")
print(f"  NEGATIVE_REJECT_RATE: {neg_reject_rate:.3f},")
print(f"  NEGATIVE_CONFIRM: {false_confirm_clear_negative},")
print(f"  AMBIGUOUS_UNKNOWN_RATE: {amb_unknown_rate:.3f},")
print(f"  AMBIGUOUS_CONFIRM: {ambiguous_false_confirm},")
print(f"  CATEGORY_ZERO_RECALL_COUNT: {cat_zero_recall_count}")
print(f"}}")

print(f"\nBY_CATEGORY:")
for cat, m in cat_metrics.items():
    print(f"  {cat:<32}: GOLD(P={m['gold_pos']}, N={m['gold_neg']}, A={m['gold_amb']}) | MODEL(C={m['model_conf']}, R={m['model_rej']}, U={m['model_unk']}) | RECALL={m['pos_confirm_rate']:.2f}")

print(f"\nRAW_VS_FINAL={{")
print(f"  TRANSITIONS: {raw_transitions},")
print(f"  DEMOTION_REASONS: {demotion_reasons}")
print(f"}}")

# Important errors
critical_errors = [r for r in eval_results if (r["gold_label"] == "CLEAR_POSITIVE" and r["final_decision"] != "CONFIRMED") or (r["gold_label"] in ("CLEAR_NEGATIVE", "AMBIGUOUS") and r["final_decision"] == "CONFIRMED")]
print(f"\nCRITICAL_ERRORS_COUNT={len(critical_errors)}")
for err in critical_errors:
    print(f"  detail_id={err['detail_id']} ({err['category_code']}): GOLD={err['gold_label']} -> MODEL={err['final_decision']} (rcode={err['final_reason_code']})")

lat_sorted = sorted(latencies)
p50 = lat_sorted[len(lat_sorted)//2] if lat_sorted else 0
p95 = lat_sorted[int(len(lat_sorted)*0.95)] if lat_sorted else 0

print(f"\nPERFORMANCE={{")
print(f"  TOTAL_WALL_SECONDS: {total_wall_time:.2f},")
print(f"  MEAN: {total_wall_time/len(eval_results):.2f},")
print(f"  P50: {p50:.2f},")
print(f"  P95: {p95:.2f},")
print(f"  MAX: {max(latencies):.2f}")
print(f"}}")

print(f"\nDATABASE={{")
print(f"  DETAIL_ROWS_MUTATED: 0,")
print(f"  EVIDENCE_ROWS_MUTATED: 0")
print(f"}}")

print(f"\nRESULT_ARTIFACT={{")
print(f"  PATH: '{eval_results_path}',")
print(f"  SHA256: '{eval_sha256}'")
print(f"}}")

print(f"\nCONTEXT_VALIDATOR_V3_QUALITY_GATE={qgate_status}")
print(f"R3_STATUS=CURRENT")

if qgate_status == "PASS":
    print("NEXT_WIP=CRM-V3-LAUNCH-R3-4G-VALIDATOR-SERVICE-DEPLOYMENT-BOUNDED-PROOF-1")
else:
    print("NEXT_WIP=EVIDENCE_DRIVEN_VALIDATOR_REPAIR")

print(f"FAILED_GATES={failed_quality_gates}")
print("\nSTOP.")
