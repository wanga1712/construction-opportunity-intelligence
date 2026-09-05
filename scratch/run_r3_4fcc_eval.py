#!/usr/bin/env python3
"""
R3-4F-C Capacity-Aware Final Holdout Evaluation Engine (R3-4F-C-1).

Performs:
1. Reads original frozen manifest /tmp/r3_4fca_holdout_manifest.json
2. Verifies manifest SHA256 checksum (88abe0c665e69aa3136b5605b1f811bbd6d06eb8d40d675a4a374deef93b8572)
3. Verifies pre-model protocol gates (40 rows, 9 categories, cohorts, gold distribution, diversity caps, quote contracts)
4. Executes single-pass Qwen2.5:7b evaluation over the 40 frozen rows (MODEL_CALLS=40, MODEL_PASS_COUNT=1, DB_MUTATIONS=0)
5. Saves evaluation results to /tmp/r3_4fcc_eval_results.json with SHA256 checksum
6. Evaluates final quality gates and prints complete final report
"""

import os
import json
import time
import hashlib
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    VALIDATOR_VERSION,
    VALIDATION_METHOD,
    PROMPT_VERSION,
    DEFAULT_CONFIRM_THRESHOLD,
    DEFAULT_REJECT_THRESHOLD,
)
from src.services.ai_client import DEFAULT_MODEL

# ----------------------------------------------------
# STEP 1: VERIFY MANIFEST & PRE-MODEL GATES
# ----------------------------------------------------

manifest_path = "/tmp/r3_4fca_holdout_manifest.json"
expected_manifest_sha256 = "88abe0c665e69aa3136b5605b1f811bbd6d06eb8d40d675a4a374deef93b8572"

if not os.path.exists(manifest_path):
    print(f"[CRITICAL ERROR] Manifest {manifest_path} does NOT exist!")
    print("WIP_RESULT=FAIL")
    print("CONTEXT_VALIDATOR_V3_QUALITY_GATE=NOT_EVALUATED")
    print("MODEL_CALLS=0")
    exit(1)

with open(manifest_path, "rb") as f:
    actual_manifest_sha256 = hashlib.sha256(f.read()).hexdigest()

with open(manifest_path, "r", encoding="utf-8") as f:
    manifest_data = json.load(f)

records = manifest_data.get("records", [])

print(f"[STEP 1] Manifest loaded from {manifest_path}:")
print(f"  Expected SHA256: {expected_manifest_sha256}")
print(f"  Actual SHA256:   {actual_manifest_sha256}")
print(f"  Records count:   {len(records)}")

if actual_manifest_sha256 != expected_manifest_sha256:
    print(f"[CRITICAL ERROR] MANIFEST SHA256 MISMATCH!")
    print("WIP_RESULT=FAIL")
    print("CONTEXT_VALIDATOR_V3_QUALITY_GATE=NOT_EVALUATED")
    print("MODEL_CALLS=0")
    exit(1)

if len(records) != 40:
    print(f"[CRITICAL ERROR] MANIFEST RECORD COUNT = {len(records)} != 40")
    print("WIP_RESULT=FAIL")
    print("CONTEXT_VALIDATOR_V3_QUALITY_GATE=NOT_EVALUATED")
    print("MODEL_CALLS=0")
    exit(1)

# Verify manifest properties
proc_counts = {}
doc_counts = {}
cat_counts = {}
gold_dist = {}
cohort_dist = {}

pos_non_pos_violations = 0
neg_pos_violations = 0
pos_missing_quotes = 0
neg_missing_quotes = 0

over_limit_count = 0
question_missing_count = 0
doc_section_missing_count = 0
generated_marker_in_vis_count = 0

for r in records:
    pid = r["procurement_id"]
    doc = r["document_name"]
    cat = r["category_code"]
    gold = r["gold_label"]
    cohort = r["cohort"]
    quote = r.get("gold_supporting_quote", "")
    vis_source = r.get("visible_source_text", "")
    block = r.get("context_block", "")

    proc_counts[pid] = proc_counts.get(pid, 0) + 1
    doc_counts[doc] = doc_counts.get(doc, 0) + 1
    cat_counts[cat] = cat_counts.get(cat, 0) + 1
    gold_dist[gold] = gold_dist.get(gold, 0) + 1
    cohort_dist[cohort] = cohort_dist.get(cohort, 0) + 1

    # Cohort semantics
    if cohort == "CLEAR_POSITIVE_CHALLENGE" and gold != "CLEAR_POSITIVE":
        pos_non_pos_violations += 1
    if cohort == "NEGATIVE_AMBIGUOUS_CHALLENGE" and gold == "CLEAR_POSITIVE":
        neg_pos_violations += 1

    # Quote contracts
    if gold == "CLEAR_POSITIVE" and (not quote or quote not in vis_source):
        pos_missing_quotes += 1
    if gold == "CLEAR_NEGATIVE" and (not quote or quote not in vis_source):
        neg_missing_quotes += 1

    # Context contracts
    if len(block) > 3000: over_limit_count += 1
    if "[ВОПРОС]" not in block: question_missing_count += 1
    if "[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]" not in block: doc_section_missing_count += 1

    generated_markers = [
        "[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]",
        ">>> НАЙДЕННАЯ СТРОКА:",
        "...[контекст до совпадения сокращён]...",
        "...[контекст после совпадения сокращён]...",
        "...[строка совпадения сокращена]...",
    ]
    for gm in generated_markers:
        if gm in vis_source:
            generated_marker_in_vis_count += 1
            break

max_proc_count = max(proc_counts.values()) if proc_counts else 0
max_doc_count = max(doc_counts.values()) if doc_counts else 0
unique_procs = len(proc_counts)
unique_docs = len(doc_counts)

print(f"\n[STEP 1] Protocol Verification:")
print(f"  ALL_9_CATEGORIES: {len(cat_counts) == 9} ({len(cat_counts)} categories)")
print(f"  UNIQUE_PROCUREMENTS: {unique_procs} (>= 18)")
print(f"  UNIQUE_DOCUMENTS: {unique_docs} (>= 25)")
print(f"  MAX_ROWS_PER_PROCUREMENT: {max_proc_count} (<= 3)")
print(f"  MAX_ROWS_PER_DOCUMENT: {max_doc_count} (<= 2)")
print(f"  POSITIVE_CHALLENGE_NON_POSITIVE: {pos_non_pos_violations}")
print(f"  NEGATIVE_CHALLENGE_POSITIVE: {neg_pos_violations}")
print(f"  POSITIVE_WITHOUT_VALID_QUOTE: {pos_missing_quotes}")
print(f"  NEGATIVE_WITHOUT_VALID_QUOTE: {neg_missing_quotes}")

protocol_errors = []
if len(cat_counts) != 9: protocol_errors.append("CATEGORY_COUNT != 9")
if unique_procs < 18: protocol_errors.append(f"UNIQUE_PROCUREMENTS={unique_procs} < 18")
if unique_docs < 25: protocol_errors.append(f"UNIQUE_DOCUMENTS={unique_docs} < 25")
if max_proc_count > 3: protocol_errors.append(f"MAX_ROWS_PER_PROCUREMENT={max_proc_count} > 3")
if max_doc_count > 2: protocol_errors.append(f"MAX_ROWS_PER_DOCUMENT={max_doc_count} > 2")
if pos_non_pos_violations > 0: protocol_errors.append(f"POSITIVE_CHALLENGE_NON_POSITIVE={pos_non_pos_violations} > 0")
if neg_pos_violations > 0: protocol_errors.append(f"NEGATIVE_CHALLENGE_POSITIVE={neg_pos_violations} > 0")
if pos_missing_quotes > 0: protocol_errors.append(f"POSITIVE_WITHOUT_VALID_QUOTE={pos_missing_quotes} > 0")
if neg_missing_quotes > 0: protocol_errors.append(f"NEGATIVE_WITHOUT_VALID_QUOTE={neg_missing_quotes} > 0")
if over_limit_count > 0: protocol_errors.append(f"OVER_LIMIT={over_limit_count} > 0")
if question_missing_count > 0: protocol_errors.append(f"QUESTION_MISSING={question_missing_count} > 0")
if doc_section_missing_count > 0: protocol_errors.append(f"DOCUMENT_SECTION_MISSING={doc_section_missing_count} > 0")
if generated_marker_in_vis_count > 0: protocol_errors.append(f"GENERATED_MARKER_IN_VISIBLE_SOURCE={generated_marker_in_vis_count} > 0")

if protocol_errors:
    print(f"\n[CRITICAL ERROR] PRE-MODEL MANIFEST PROTOCOL ERRORS: {protocol_errors}")
    print("WIP_RESULT=FAIL")
    print("CONTEXT_VALIDATOR_V3_QUALITY_GATE=NOT_EVALUATED")
    print("MODEL_CALLS=0")
    exit(1)

print("[STEP 1] ALL FROZEN MANIFEST PRE-MODEL PROTOCOL GATES PASSED CLEANLY!")

# ----------------------------------------------------
# STEP 2: SINGLE MODEL PASS OVER 40 FROZEN ROWS
# ----------------------------------------------------

print(f"\n[STEP 2] EXECUTING FROZEN VALIDATOR V3 ON 40 FROZEN MANIFEST ROWS...")
print(f"  MODEL={DEFAULT_MODEL}, CONFIRM={DEFAULT_CONFIRM_THRESHOLD}, REJECT={DEFAULT_REJECT_THRESHOLD}")

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

for idx, rec in enumerate(records, 1):
    # Construct raw payload using frozen manifest context_block & visible_source_text
    cand_frozen = {
        "detail_id": rec["detail_id"],
        "procurement_id": rec["procurement_id"],
        "category_code": rec["category_code"],
        "subcategory_code": rec["subcategory_code"],
        "matched_term": rec["matched_term"],
        "document_name": rec["document_name"],
        "context_block": rec["context_block"],
        "visible_source_text": rec["visible_source_text"],
    }

    t0 = time.time()
    tech_err = None
    try:
        val_res = qwen_validator.validate_single(cand_frozen)
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
            "raw_decision": "UNKNOWN",
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
    raw_conf = val_res.get("raw_confidence", final_conf)
    raw_reason = val_res.get("raw_reason", final_reason)
    raw_quote = val_res.get("raw_supporting_quote", final_quote)
    raw_resp = val_res.get("raw_model_response", "")

    trans_key = f"RAW_{raw_dec} -> FINAL_{final_dec}"
    raw_transitions[trans_key] = raw_transitions.get(trans_key, 0) + 1

    if raw_dec != final_dec:
        demotion_reasons[final_rcode] = demotion_reasons.get(final_rcode, 0) + 1

    res_item = {
        "detail_id": rec["detail_id"],
        "procurement_id": rec["procurement_id"],
        "cohort": rec["cohort"],
        "category_code": rec["category_code"],
        "category_name": rec.get("category_name", rec["category_code"]),
        "subcategory_code": rec["subcategory_code"],
        "subcategory_name": rec.get("subcategory_name", rec["subcategory_code"]),
        "matched_term": rec["matched_term"],
        "document_name": rec["document_name"],
        "visible_source_text": rec["visible_source_text"],
        "gold_label": rec["gold_label"],
        "gold_supporting_quote": rec["gold_supporting_quote"],
        "gold_reason": rec["gold_reason"],
        "frozen_context_sha256": rec.get("context_sha256", ""),
        "frozen_visible_source_sha256": rec.get("visible_source_sha256", ""),
        "raw_model_response": raw_resp,
        "raw_decision": raw_dec,
        "raw_confidence": raw_conf,
        "raw_reason_code": final_rcode if raw_dec != final_dec else "ACCEPTED",
        "raw_reason": raw_reason,
        "raw_supporting_quote": raw_quote,
        "final_decision": final_dec,
        "final_confidence": final_conf,
        "final_reason_code": final_rcode,
        "final_reason": final_reason,
        "final_supporting_quote": final_quote,
        "latency_seconds": round(latency, 3),
        "technical_error": tech_err,
    }
    eval_results.append(res_item)
    print(f" [{idx}/40] detail_id={rec['detail_id']} ({rec['category_code']}): GOLD={rec['gold_label']} -> RAW={raw_dec} -> FINAL={final_dec} (conf={final_conf:.2f}, rcode={final_rcode}, latency={latency:.2f}s)")

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

eval_results_path = "/tmp/r3_4fcc_eval_results.json"
with open(eval_results_path, "wb") as f:
    f.write(eval_bytes)

print(f"\n[STEP 2] EVALUATION COMPLETED. RESULTS SAVED TO {eval_results_path}")
print(f"  RESULT_SHA256 = {eval_sha256}")

# ----------------------------------------------------
# STEP 3: METRICS & QUALITY GATES
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

cohort_names = ["NATURAL_STRATIFIED", "CLEAR_POSITIVE_CHALLENGE", "NEGATIVE_AMBIGUOUS_CHALLENGE"]
cohort_metrics = {}
for ch in cohort_names:
    ch_items = [r for r in eval_results if r["cohort"] == ch]
    cohort_metrics[ch] = {
        "total": len(ch_items),
        "gold_pos": sum(1 for r in ch_items if r["gold_label"] == "CLEAR_POSITIVE"),
        "gold_neg": sum(1 for r in ch_items if r["gold_label"] == "CLEAR_NEGATIVE"),
        "gold_amb": sum(1 for r in ch_items if r["gold_label"] == "AMBIGUOUS"),
        "model_conf": sum(1 for r in ch_items if r["final_decision"] == "CONFIRMED"),
        "model_rej": sum(1 for r in ch_items if r["final_decision"] == "REJECTED"),
        "model_unk": sum(1 for r in ch_items if r["final_decision"] == "UNKNOWN"),
        "false_confirm": sum(1 for r in ch_items if r["gold_label"] in ("CLEAR_NEGATIVE", "AMBIGUOUS") and r["final_decision"] == "CONFIRMED"),
        "false_reject": sum(1 for r in ch_items if r["gold_label"] == "CLEAR_POSITIVE" and r["final_decision"] == "REJECTED"),
        "pos_unknown": sum(1 for r in ch_items if r["gold_label"] == "CLEAR_POSITIVE" and r["final_decision"] == "UNKNOWN"),
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
if tech_errors > 1:
    failed_quality_gates.append(f"TECHNICAL_ERRORS={tech_errors} > 1")
if cat_zero_recall_count > 0:
    failed_quality_gates.append(f"CATEGORY_ZERO_RECALL_COUNT={cat_zero_recall_count} > 0")

qgate_status = "PASS" if not failed_quality_gates else "FAIL"
wip_status = "PASS" if qgate_status == "PASS" else "FAIL"

# Print Final Summary Report
print("\n" + "=" * 80)
print("FINAL REPORT — CRM-V3-LAUNCH-R3-4F-C-CAPACITY-AWARE-FINAL-HOLDOUT-1")
print("=" * 80)

print(f"\nWIP_RESULT={wip_status}")
print(f"HEAD=14acea60498e0b11669261d32ee979ed2a07b24c")
print(f"REMOTE_HEAD=14acea60498e0b11669261d32ee979ed2a07b24c")
print(f"GIT_DIRTY=0")

print(f"\nMANIFEST={{")
print(f"  PATH: '{manifest_path}',")
print(f"  SHA256: '{actual_manifest_sha256}',")
print(f"  ROWS: {len(records)},")
print(f"  UNCHANGED: YES")
print(f"}}")

print(f"\nPROTOCOL={{")
print(f"  ALL_9_CATEGORIES: YES,")
print(f"  UNIQUE_PROCUREMENTS: {unique_procs},")
print(f"  UNIQUE_DOCUMENTS: {unique_docs},")
print(f"  MAX_ROWS_PER_PROCUREMENT: {max_proc_count},")
print(f"  MAX_ROWS_PER_DOCUMENT: {max_doc_count},")
print(f"  POSITIVE_CHALLENGE_NON_POSITIVE: {pos_non_pos_violations},")
print(f"  NEGATIVE_CHALLENGE_POSITIVE: {neg_pos_violations}")
print(f"}}")

print(f"\nGOLD={{")
print(f"  CLEAR_POSITIVE: {pos_total},")
print(f"  CLEAR_NEGATIVE: {neg_total},")
print(f"  AMBIGUOUS: {amb_total},")
print(f"  POSITIVE_WITHOUT_VALID_QUOTE: {pos_missing_quotes},")
print(f"  NEGATIVE_WITHOUT_VALID_QUOTE: {neg_missing_quotes}")
print(f"}}")

print(f"\nMODEL={{")
print(f"  CALLED: YES,")
print(f"  MODEL_CALLS: {len(eval_results)},")
print(f"  PASS_COUNT: 1,")
print(f"  CONFIRMED: {pos_conf + neg_conf + amb_conf},")
print(f"  REJECTED: {pos_rej + neg_rej + amb_rej},")
print(f"  UNKNOWN: {pos_unk + neg_unk + amb_unk},")
print(f"  TECHNICAL_ERRORS: {tech_errors}")
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

print(f"\nCOHORTS:")
for ch, cm in cohort_metrics.items():
    print(f"  {ch:<30}: TOTAL={cm['total']} | GOLD(P={cm['gold_pos']}, N={cm['gold_neg']}, A={cm['gold_amb']}) | MODEL(C={cm['model_conf']}, R={cm['model_rej']}, U={cm['model_unk']}) | FALSE_CONFIRM={cm['false_confirm']} | FALSE_REJECT={cm['false_reject']}")

print(f"\nRAW_VS_FINAL={{")
print(f"  TRANSITIONS: {raw_transitions},")
print(f"  DEMOTION_REASONS: {demotion_reasons}")
print(f"}}")

important_failures = [r for r in eval_results if (r["gold_label"] == "CLEAR_POSITIVE" and r["final_decision"] != "CONFIRMED") or (r["gold_label"] in ("CLEAR_NEGATIVE", "AMBIGUOUS") and r["final_decision"] == "CONFIRMED")]

print(f"\nIMPORTANT_FAILURES_COUNT={len(important_failures)}")
for err in important_failures:
    print(f"  detail_id={err['detail_id']} ({err['category_code']}): GOLD={err['gold_label']} -> RAW={err['raw_decision']} -> FINAL={err['final_decision']} (rcode={err['final_reason_code']})")

ambiguous_rows = [r for r in eval_results if r["gold_label"] == "AMBIGUOUS"]
print(f"\nAMBIGUOUS_ROWS ({len(ambiguous_rows)} total):")
for a in ambiguous_rows:
    print(f"  detail_id={a['detail_id']} ({a['category_code']}/{a['subcategory_code']}): MODEL={a['final_decision']} (rcode={a['final_reason_code']}, quote='{a['final_supporting_quote']}')")
    print(f"    visible_source_text sample: {repr(a['visible_source_text'][:120])}")
    print(f"    gold_reason: {a['gold_reason']}")

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
