#!/usr/bin/env python3
"""
R3-4F Step 14: Run Current Production ContextValidator v2 ONCE on Frozen Holdout.
Saves evaluation results to /tmp/r3_4f_eval_results.json.
Does NOT mutate production DB.
"""
import os
import json
import time
import hashlib
from collections import Counter
from decimal import Decimal
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    VALIDATOR_VERSION,
    VALIDATION_METHOD,
    DEFAULT_CONFIRM_THRESHOLD,
    DEFAULT_REJECT_THRESHOLD,
)

manifest_path = "/tmp/r3_4f_holdout_manifest.json"
with open(manifest_path, "r", encoding="utf-8") as f:
    manifest_data = json.load(f)

records = manifest_data["records"]
frozen_sha = manifest_data["manifest_sha256"]

print("=" * 60)
print("R3-4F SINGLE MODEL EVALUATION RUN")
print("=" * 60)
print(f"HOLDOUT_RUN_STARTED=YES")
print(f"MANIFEST_SHA256={frozen_sha}")
print(f"VALIDATOR_VERSION={VALIDATOR_VERSION}")
print(f"VALIDATION_METHOD={VALIDATION_METHOD}")
print(f"CONFIRM_THRESHOLD={DEFAULT_CONFIRM_THRESHOLD}")
print(f"REJECT_THRESHOLD={DEFAULT_REJECT_THRESHOLD}")
print(f"TOTAL_CANDIDATES={len(records)}")

validator = ContextValidator()

print(f"RESOLVED_AI_CLIENT={type(validator._ai_caller)}")

eval_results = []
latencies = []
start_wall = time.time()

for idx, rec in enumerate(records, 1):
    c_start = time.time()
    candidate = {
        "detail_id": rec["detail_id"],
        "procurement_id": rec["procurement_id"],
        "category_code": rec["category_code"],
        "category_name": rec["category_name"],
        "subcategory_code": rec["subcategory_code"],
        "subcategory_name": rec["subcategory_name"],
        "matched_term": rec["matched_term"],
        "match_method": rec["match_method"],
        "score": rec["score"],
        "document_name": rec["document_name"],
        "matched_line": rec["matched_line"],
        "context_before": rec["context_before"],
        "context_after": rec["context_after"],
    }

    try:
        res = validator.validate_single(candidate)
    except Exception as e:
        res = {
            "decision": "UNKNOWN",
            "confidence": 0.0,
            "reason_code": "MODEL_EXCEPTION",
            "reason": str(e),
            "supporting_quote": "",
        }

    c_lat = time.time() - c_start
    latencies.append(c_lat)

    res_entry = {
        "detail_id": rec["detail_id"],
        "procurement_id": rec["procurement_id"],
        "cohort": rec["cohort"],
        "category_code": rec["category_code"],
        "subcategory_code": rec["subcategory_code"],
        "matched_term": rec["matched_term"],
        "document_name": rec["document_name"],
        "matched_line": rec["matched_line"],
        "context_before": rec["context_before"],
        "context_after": rec["context_after"],
        "gold_label": rec["gold_label"],
        "gold_reason": rec["gold_reason"],
        "model_decision": res["decision"],
        "model_confidence": res["confidence"],
        "reason_code": res.get("reason_code", ""),
        "reason": res.get("reason", ""),
        "supporting_quote": res.get("supporting_quote", ""),
        "latency_seconds": round(c_lat, 3),
    }
    eval_results.append(res_entry)
    print(f"[{idx}/{len(records)}] Detail {rec['detail_id']} (Cat: {rec['category_code']}): Gold={rec['gold_label']} -> Model={res['decision']} (conf={res['confidence']}, code={res.get('reason_code')}) in {c_lat:.2f}s", flush=True)

total_wall = time.time() - start_wall

# ==============================================================================
# CALCULATE METRICS & GATES
# ==============================================================================
pos_total = sum(1 for r in eval_results if r["gold_label"] == "CLEAR_POSITIVE")
pos_confirmed = sum(1 for r in eval_results if r["gold_label"] == "CLEAR_POSITIVE" and r["model_decision"] == "CONFIRMED")
pos_rejected = sum(1 for r in eval_results if r["gold_label"] == "CLEAR_POSITIVE" and r["model_decision"] == "REJECTED")
pos_unknown = sum(1 for r in eval_results if r["gold_label"] == "CLEAR_POSITIVE" and r["model_decision"] == "UNKNOWN")

neg_total = sum(1 for r in eval_results if r["gold_label"] == "CLEAR_NEGATIVE")
neg_rejected = sum(1 for r in eval_results if r["gold_label"] == "CLEAR_NEGATIVE" and r["model_decision"] == "REJECTED")
neg_confirmed = sum(1 for r in eval_results if r["gold_label"] == "CLEAR_NEGATIVE" and r["model_decision"] == "CONFIRMED")
neg_unknown = sum(1 for r in eval_results if r["gold_label"] == "CLEAR_NEGATIVE" and r["model_decision"] == "UNKNOWN")

amb_total = sum(1 for r in eval_results if r["gold_label"] == "AMBIGUOUS")
amb_unknown = sum(1 for r in eval_results if r["gold_label"] == "AMBIGUOUS" and r["model_decision"] == "UNKNOWN")
amb_confirmed = sum(1 for r in eval_results if r["gold_label"] == "AMBIGUOUS" and r["model_decision"] == "CONFIRMED")
amb_rejected = sum(1 for r in eval_results if r["gold_label"] == "AMBIGUOUS" and r["model_decision"] == "REJECTED")

tech_errors = sum(1 for r in eval_results if r["reason_code"] in ("MODEL_EXCEPTION", "INVALID_JSON"))

pos_confirm_rate = (pos_confirmed / pos_total) if pos_total else 1.0
neg_reject_rate = (neg_rejected / neg_total) if neg_total else 1.0

# Critical Errors Lists
false_confirm_negatives = [r for r in eval_results if r["gold_label"] == "CLEAR_NEGATIVE" and r["model_decision"] == "CONFIRMED"]
false_reject_positives = [r for r in eval_results if r["gold_label"] == "CLEAR_POSITIVE" and r["model_decision"] == "REJECTED"]
positive_unknowns = [r for r in eval_results if r["gold_label"] == "CLEAR_POSITIVE" and r["model_decision"] == "UNKNOWN"]
ambiguous_overconf = [r for r in eval_results if r["gold_label"] == "AMBIGUOUS" and r["model_decision"] != "UNKNOWN"]

# Evaluate Pass Gates
failed_gates = []

if neg_confirmed > 0:
    failed_gates.append(f"FALSE_CONFIRM_CLEAR_NEGATIVE ({neg_confirmed} > 0)")

if pos_rejected > 0:
    failed_gates.append(f"FALSE_REJECT_CLEAR_POSITIVE ({pos_rejected} > 0)")

if pos_confirm_rate < 0.90:
    failed_gates.append(f"CLEAR_POSITIVE_CONFIRM_RATE ({pos_confirm_rate:.2f} < 0.90)")

if neg_reject_rate < 0.90:
    failed_gates.append(f"CLEAR_NEGATIVE_REJECT_RATE ({neg_reject_rate:.2f} < 0.90)")

if amb_confirmed > 0:
    failed_gates.append(f"AMBIGUOUS_CONFIRMED ({amb_confirmed} > 0)")

if tech_errors > 1:
    failed_gates.append(f"TECHNICAL_ERRORS ({tech_errors} > 1)")

quality_gate = "PASS" if not failed_gates else "FAIL"

out_data = {
    "manifest_sha256": frozen_sha,
    "total_wall_seconds": round(total_wall, 2),
    "model_run_count": 1,
    "quality_gate": quality_gate,
    "failed_gates": failed_gates,
    "metrics": {
        "pos_total": pos_total,
        "pos_confirmed": pos_confirmed,
        "pos_rejected": pos_rejected,
        "pos_unknown": pos_unknown,
        "pos_confirm_rate": round(pos_confirm_rate, 4),
        "neg_total": neg_total,
        "neg_rejected": neg_rejected,
        "neg_confirmed": neg_confirmed,
        "neg_unknown": neg_unknown,
        "neg_reject_rate": round(neg_reject_rate, 4),
        "amb_total": amb_total,
        "amb_unknown": amb_unknown,
        "amb_confirmed": amb_confirmed,
        "amb_rejected": amb_rejected,
        "tech_errors": tech_errors,
    },
    "latencies": {
        "mean": round(sum(latencies) / len(latencies), 3),
        "min": round(min(latencies), 3),
        "max": round(max(latencies), 3),
        "p50": round(sorted(latencies)[len(latencies)//2], 3),
    },
    "critical_errors": {
        "false_confirm_negatives": false_confirm_negatives,
        "false_reject_positives": false_reject_positives,
        "positive_unknowns": positive_unknowns,
        "ambiguous_overconf": ambiguous_overconf,
    },
    "eval_results": eval_results,
}

out_path = "/tmp/r3_4f_eval_results.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(out_data, f, ensure_ascii=False, indent=2)

print("=" * 60)
print(f"EVALUATION COMPLETE IN {total_wall:.2f}s")
print(f"QUALITY_GATE={quality_gate}")
print(f"FAILED_GATES={failed_gates}")
print(f"RESULTS SAVED TO {out_path}")
print("=" * 60)
