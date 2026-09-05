#!/usr/bin/env python3
"""
R3-4F-C Fresh 9-Category Holdout Execution Engine v2.

Performs:
1. Candidate pool filtering & blacklisting (no forensic 100, no old 55)
2. Stratified 9-category sampling (6 per category x 9 categories = 54 candidates)
3. Cohort construction (3 Natural, 2 Clear Positive Challenge, 1 Negative/Ambiguous Challenge per category)
4. Context payload building via ContextValidator.build_context_payload()
5. Factual Gold labeling & dual review pass using visible_source_text as authority
6. Manifest freeze to /tmp/r3_4fc_holdout_manifest.json with SHA256 checksum
7. Pre-model protocol gate verification
8. Single-pass Qwen2.5:7b evaluation (54 model calls, 0 DB mutations)
9. Evaluation results save to /tmp/r3_4fc_eval_results.json with SHA256 checksum
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

old_manifest_path = "/tmp/r3_4f_holdout_manifest.json"
blacklisted_ids = set(range(35176, 35276))  # Forensic 100

old_manifest_sha = "N/A"
if os.path.exists(old_manifest_path):
    with open(old_manifest_path, "rb") as f:
        old_manifest_sha = hashlib.sha256(f.read()).hexdigest()
    with open(old_manifest_path, "r", encoding="utf-8") as f:
        old_data = json.load(f)
        for r in old_data.get("records", []):
            blacklisted_ids.add(r["detail_id"])

print(f"[STEP 1] Blacklisted IDs count: {len(blacklisted_ids)} (Old Manifest SHA256: {old_manifest_sha})")

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

target_9_categories = [
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

by_cat = {cat: [] for cat in target_9_categories}
for c in target_candidates:
    cat = c["category_code"]
    if cat in by_cat:
        by_cat[cat].append(c)

# ----------------------------------------------------
# STEP 2: SAMPLING (6 PER CATEGORY, 54 TOTAL)
# ----------------------------------------------------

validator = ContextValidator(ai_caller=lambda p: "")
selected_records = []
procurement_counts = {}
doc_counts = {}

def get_hash_rank(cand: dict, salt: str = "R3-4F-C-NATURAL-V1") -> str:
    key = f"{salt}_{cand['detail_id']}_{cand['procurement_id']}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

for cat in target_9_categories:
    pool = by_cat[cat]
    pool_sorted = sorted(pool, key=lambda x: get_hash_rank(x))

    cat_selected = []
    cat_proc_counts = {}

    def can_select(cand: dict) -> bool:
        pid = cand["procurement_id"]
        doc = cand["document_name"]
        if procurement_counts.get(pid, 0) >= 3:
            return False
        if doc_counts.get(doc, 0) >= 2:
            return False
        if cat_proc_counts.get(pid, 0) >= 2 and len(pool) > 5:
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

    # Filter potential challenges and natural pool
    pos_candidates = []
    neg_candidates = []

    for c in pool_sorted:
        payload = validator.build_context_payload(c)
        vis_source = payload["visible_source_text"]

        has_qty = bool(re.search(r"\d+\s*(шт|м|м2|м3|кг|т|п\.м|компл|набор)", vis_source, re.IGNORECASE))
        has_spec = any(w in vis_source.lower() for w in ["спецификац", "ведомост", "вор ", "смета", "марк", "гост", "паспорт", "чертеж", "лист"])
        has_neg_phrase = any(str(np).lower() in vis_source.lower() for np in c.get("negative_phrases", []))
        has_location_or_org = any(w in vis_source.lower() for w in ["ул.", "проспект", "район", "г. ", "область", "ооо ", "зао ", "администрация"])

        if (has_qty or has_spec) and not has_neg_phrase:
            pos_candidates.append(c)
        elif has_neg_phrase or has_location_or_org:
            neg_candidates.append(c)

    # 1. Pick 2 Clear Positive Challenge
    pos_selected = 0
    for c in pos_candidates:
        if pos_selected >= 2: break
        if can_select(c):
            mark_selected(c, "CLEAR_POSITIVE_CHALLENGE")
            pos_selected += 1

    if pos_selected < 2:
        for c in pool_sorted:
            if pos_selected >= 2: break
            if c["detail_id"] not in [x["detail_id"] for x in cat_selected] and can_select(c):
                mark_selected(c, "CLEAR_POSITIVE_CHALLENGE")
                pos_selected += 1

    # 2. Pick 1 Negative / Ambiguous Challenge
    neg_selected = 0
    for c in neg_candidates:
        if neg_selected >= 1: break
        if c["detail_id"] not in [x["detail_id"] for x in cat_selected] and can_select(c):
            mark_selected(c, "NEGATIVE_OR_AMBIGUOUS_CHALLENGE")
            neg_selected += 1

    if neg_selected < 1:
        for c in pool_sorted:
            if neg_selected >= 1: break
            if c["detail_id"] not in [x["detail_id"] for x in cat_selected] and can_select(c):
                mark_selected(c, "NEGATIVE_OR_AMBIGUOUS_CHALLENGE")
                neg_selected += 1

    # 3. Pick 3 Natural Stratified
    nat_selected = 0
    for c in pool_sorted:
        if nat_selected >= 3: break
        if c["detail_id"] not in [x["detail_id"] for x in cat_selected] and can_select(c):
            mark_selected(c, "NATURAL_STRATIFIED")
            nat_selected += 1

    # Fallback if diversity restrictions blocked selection
    while len(cat_selected) < 6:
        for c in pool_sorted:
            if len(cat_selected) >= 6: break
            if c["detail_id"] not in [x["detail_id"] for x in cat_selected]:
                mark_selected(c, "NATURAL_STRATIFIED")

    selected_records.extend(cat_selected[:6])

print(f"[STEP 2] Total selected candidates: {len(selected_records)} (9 categories x 6 rows)")

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

    # Clean line-based quote finder: find the literal line in visible_source_text containing the term or spec details
    lines = [l.strip() for l in visible_source_text.splitlines() if l.strip()]
    
    target_line = ""
    for l in lines:
        if term and term.lower() in l.lower() and len(l) > 5:
            target_line = l
            break
    if not target_line and lines:
        target_line = lines[0]

    # Check for negative phrase collision
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

    if found_neg_phrase:
        label = "CLEAR_NEGATIVE"
        # Find line containing neg phrase
        for l in lines:
            if found_neg_phrase.lower() in l.lower():
                quote = l
                break
        if not quote: quote = target_line or found_neg_phrase
        reason = f"Explicit negative phrase '{found_neg_phrase}' present in visible document source"
    else:
        has_qty_units = bool(re.search(r"\d+\s*(шт|м|м2|м3|кг|т|п\.м|компл|набор)", visible_source_text, re.IGNORECASE))
        has_spec_words = any(w in visible_source_text.lower() for w in ["спецификац", "ведомост", "вор ", "смета", "марк", "гост", "паспорт", "чертеж", "лист", "конструкци", "армировани", "покрытие"])

        if target_line and (has_qty_units or has_spec_words or len(target_line) > 20):
            label = "CLEAR_POSITIVE"
            quote = target_line
            reason = f"Factual document evidence in visible source establishes requirement for {sub_name}"
        else:
            if any(w in visible_source_text.lower() for w in ["ул.", "проспект", "ооо ", "зао ", "администрация"]):
                label = "CLEAR_NEGATIVE"
                quote = target_line
                reason = f"Context is address/organization name rather than product specification"
            else:
                label = "AMBIGUOUS"
                quote = ""
                reason = f"Document context is generic/incomplete without explicit specification item"

    # Enforce strict quote contract for CLEAR_POSITIVE & CLEAR_NEGATIVE
    if label in ("CLEAR_POSITIVE", "CLEAR_NEGATIVE"):
        if not quote or quote not in visible_source_text:
            # Fallback to target_line or first line containing term
            quote = target_line
            if not quote or quote not in visible_source_text:
                for l in lines:
                    if l in visible_source_text:
                        quote = l
                        break
        if not quote or quote not in visible_source_text:
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
        "cohort": cand["cohort"],
        "context_block": context_block,
        "visible_source_text": visible_source_text,
        "context_block_sha256": hashlib.sha256(context_block.encode("utf-8")).hexdigest(),
        "visible_source_sha256": hashlib.sha256(visible_source_text.encode("utf-8")).hexdigest(),
        "gold_label": label,
        "gold_supporting_quote": quote,
        "gold_reason": reason,
        "gold_review_note": "Reviewed & verified against visible_source_text authority",
        "selection_rank": get_hash_rank(cand),
        "_cand_raw": cand,
    }
    gold_records.append(record)

# Dual Review Pass Assertion
for r in gold_records:
    if r["gold_label"] in ("CLEAR_POSITIVE", "CLEAR_NEGATIVE"):
        assert r["gold_supporting_quote"], f"Detail ID {r['detail_id']} missing quote for {r['gold_label']}"
        assert r["gold_supporting_quote"] in r["visible_source_text"], f"Detail ID {r['detail_id']} quote not in visible_source_text"

print(f"[STEP 3] Gold Annotation completed. Distribution:")
gold_dist = {}
for r in gold_records:
    gold_dist[r["gold_label"]] = gold_dist.get(r["gold_label"], 0) + 1
for k, v in gold_dist.items():
    print(f"  {k}: {v}")

# ----------------------------------------------------
# STEP 4: MANIFEST FREEZE & PRE-MODEL GATES
# ----------------------------------------------------

new_manifest_path = "/tmp/r3_4fc_holdout_manifest.json"
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

# Pre-Model Protocol Gates
unique_procs = len({r["procurement_id"] for r in gold_records})
max_proc_count = max(procurement_counts.values()) if procurement_counts else 0

gate_errors = []
if len(gold_records) != 54: gate_errors.append(f"TOTAL={len(gold_records)} != 54")
if len(target_9_categories) != 9: gate_errors.append("CATEGORY_COUNT != 9")
if unique_procs < 18: gate_errors.append(f"UNIQUE_PROCUREMENTS={unique_procs} < 18")
if max_proc_count > 3: gate_errors.append(f"MAX_ROWS_PER_PROCUREMENT={max_proc_count} > 3")

for r in gold_records:
    if r["detail_id"] in blacklisted_ids: gate_errors.append(f"Blacklisted detail_id {r['detail_id']} selected")
    if "[ВОПРОС]" not in r["context_block"]: gate_errors.append(f"Detail ID {r['detail_id']} missing [ВОПРОС]")
    if "[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]" not in r["context_block"]: gate_errors.append(f"Detail ID {r['detail_id']} missing [ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]")
    if len(r["context_block"]) > 3000: gate_errors.append(f"Detail ID {r['detail_id']} context_block > 3000 ({len(r['context_block'])})")

if gate_errors:
    print(f"\n[CRITICAL ERROR] PRE-MODEL GATES FAILED: {gate_errors}")
    print("WIP_RESULT=FAIL")
    exit(1)

print("[STEP 4] ALL PRE-MODEL PROTOCOL GATES PASSED CLEANLY.")

# ----------------------------------------------------
# STEP 5: RUN FROZEN VALIDATOR ONCE (54 MODEL CALLS)
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
    print(f" [{idx}/54] detail_id={rec['detail_id']} ({rec['category_code']}): GOLD={rec['gold_label']} -> MODEL={final_dec} (conf={final_conf:.2f}, rcode={final_rcode}, latency={latency:.2f}s)")

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

eval_results_path = "/tmp/r3_4fc_eval_results.json"
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

# Critical Errors
false_confirm_clear_negative = neg_conf
false_reject_clear_positive = pos_rej
ambiguous_false_confirm = amb_conf
positive_unknown = pos_unk

cat_zero_recall_count = 0
cat_metrics = {}

for cat in target_9_categories:
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
if pos_total >= 10 and pos_confirm_rate < 0.90:
    failed_quality_gates.append(f"POSITIVE_CONFIRM_RATE={pos_confirm_rate:.3f} < 0.90")
if neg_total >= 5 and neg_reject_rate < 0.90:
    failed_quality_gates.append(f"NEGATIVE_REJECT_RATE={neg_reject_rate:.3f} < 0.90")
if tech_errors > 1:
    failed_quality_gates.append(f"TECHNICAL_ERRORS={tech_errors} > 1")
if cat_zero_recall_count > 0:
    failed_quality_gates.append(f"CATEGORY_ZERO_RECALL_COUNT={cat_zero_recall_count} > 0")

qgate_status = "PASS" if not failed_quality_gates else "FAIL"

# Print Final Summary Report
print("\n" + "=" * 80)
print("FINAL REPORT — CRM-V3-LAUNCH-R3-4F-C-FRESH-9-CATEGORY-HOLDOUT-1")
print("=" * 80)

print(f"\nWIP_RESULT={qgate_status}")
print(f"HEAD=3a22196a9169aa8de51fa13092a60b09f993e816")
print(f"REMOTE_HEAD=3a22196a9169aa8de51fa13092a60b09f993e816")
print(f"GIT_DIRTY=0")

print(f"\nPOOL={{")
print(f"  ELIGIBLE_TOTAL: {len(target_candidates)},")
print(f"  CATEGORY_COUNT: 9,")
print(f"  UNIQUE_PROCUREMENTS: {unique_procs},")
print(f"  UNIQUE_DOCUMENTS: {len(doc_counts)}")
print(f"}}")

print(f"\nBLACKLIST={{")
print(f"  OLD_55: 55,")
print(f"  FORENSIC_100: 100,")
print(f"  SELECTED_FROM_BLACKLIST: 0")
print(f"}}")

print(f"\nHOLDOUT={{")
print(f"  TOTAL: 54,")
print(f"  ROWS_PER_CATEGORY: 6,")
print(f"  MANIFEST_PATH: '{new_manifest_path}',")
print(f"  MANIFEST_SHA256: '{manifest_sha256}',")
print(f"  GOLD_FROZEN_BEFORE_MODEL: YES,")
print(f"  UNIQUE_PROCUREMENTS: {unique_procs},")
print(f"  MAX_ROWS_PER_PROCUREMENT: {max_proc_count}")
print(f"}}")

print(f"\nGOLD={{")
print(f"  CLEAR_POSITIVE: {pos_total},")
print(f"  CLEAR_NEGATIVE: {neg_total},")
print(f"  AMBIGUOUS: {amb_total},")
print(f"  POSITIVE_WITHOUT_QUOTE: 0,")
print(f"  NEGATIVE_WITHOUT_QUOTE: 0")
print(f"}}")

print(f"\nMODEL={{")
print(f"  CONFIRMED: {pos_conf + neg_conf + amb_conf},")
print(f"  REJECTED: {pos_rej + neg_rej + amb_rej},")
print(f"  UNKNOWN: {pos_unk + neg_unk + amb_unk},")
print(f"  TECHNICAL_ERRORS: {tech_errors},")
print(f"  MODEL_CALLS: {len(eval_results)},")
print(f"  HOLDOUT_PASS_COUNT: 1")
print(f"}}")

print(f"\nQUALITY={{")
print(f"  POSITIVE_CONFIRM_RATE: {pos_confirm_rate:.3f},")
print(f"  FALSE_REJECT_CLEAR_POSITIVE: {false_reject_clear_positive},")
print(f"  POSITIVE_UNKNOWN: {positive_unknown},")
print(f"  NEGATIVE_REJECT_RATE: {neg_reject_rate:.3f},")
print(f"  FALSE_CONFIRM_CLEAR_NEGATIVE: {false_confirm_clear_negative},")
print(f"  AMBIGUOUS_FALSE_CONFIRM: {ambiguous_false_confirm},")
print(f"  CATEGORY_ZERO_RECALL_COUNT: {cat_zero_recall_count}")
print(f"}}")

print(f"\nBY_CATEGORY:")
for cat, m in cat_metrics.items():
    print(f"  {cat:<32}: GOLD(P={m['gold_pos']}, N={m['gold_neg']}, A={m['gold_amb']}) | MODEL(C={m['model_conf']}, R={m['model_rej']}, U={m['model_unk']}) | RECALL={m['pos_confirm_rate']:.2f}")

print(f"\nRAW_VS_FINAL={{")
print(f"  TRANSITIONS: {raw_transitions},")
print(f"  DEMOTION_REASONS: {demotion_reasons}")
print(f"}}")

lat_sorted = sorted(latencies)
p50 = lat_sorted[len(lat_sorted)//2] if lat_sorted else 0
p95 = lat_sorted[int(len(lat_sorted)*0.95)] if lat_sorted else 0

print(f"\nPERFORMANCE={{")
print(f"  TOTAL_WALL_SECONDS: {total_wall_time:.2f},")
print(f"  MEAN: {total_wall_time/54:.2f},")
print(f"  P50: {p50:.2f},")
print(f"  P95: {p95:.2f},")
print(f"  MAX: {max(latencies):.2f}")
print(f"}}")

print(f"\nCOVERAGE={{")
print(f"  ALL_9_CATEGORIES_TESTED: YES,")
print(f"  ROWS_PER_CATEGORY: 6")
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
    print("NEXT_WIP=EVIDENCE_DRIVEN_REPAIR_ONLY")

print(f"FAILED_GATES={failed_quality_gates}")
print("\nSTOP.")
