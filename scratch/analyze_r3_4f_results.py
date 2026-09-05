#!/usr/bin/env python3
"""Analyze R3-4F evaluation results from /tmp/r3_4f_eval_results.json."""
import json
from collections import Counter

with open("/tmp/r3_4f_eval_results.json", "r", encoding="utf-8") as f:
    data = json.load(f)

results = data["eval_results"]
metrics = data["metrics"]
lat = data["latencies"]

print("=" * 60)
print("R3-4F EVALUATION ANALYSIS REPORT")
print("=" * 60)
print(f"MANIFEST_SHA256={data['manifest_sha256']}")
print(f"QUALITY_GATE={data['quality_gate']}")
print(f"FAILED_GATES={data['failed_gates']}")
print(f"TOTAL_WALL_SECONDS={data['total_wall_seconds']}")
print(f"LATENCIES: mean={lat['mean']}s, min={lat['min']}s, max={lat['max']}s, p50={lat['p50']}s")

print("\n--- OVERALL METRICS ---")
print(f"CLEAR_POSITIVE (47 total): CONFIRMED={metrics['pos_confirmed']} ({metrics['pos_confirm_rate']*100:.1f}%), REJECTED={metrics['pos_rejected']}, UNKNOWN={metrics['pos_unknown']}")
print(f"CLEAR_NEGATIVE (6 total): REJECTED={metrics['neg_rejected']} ({metrics['neg_reject_rate']*100:.1f}%), CONFIRMED={metrics['neg_confirmed']}, UNKNOWN={metrics['neg_unknown']}")
print(f"AMBIGUOUS (2 total): UNKNOWN={metrics['amb_unknown']}, CONFIRMED={metrics['amb_confirmed']}, REJECTED={metrics['amb_rejected']}")
print(f"TECHNICAL_ERRORS={metrics['tech_errors']}")

# By Cohort
print("\n--- BY COHORT ---")
for cohort in ["NATURAL_STRATIFIED", "CLEAR_POSITIVE_CHALLENGE", "NEGATIVE_AMBIGUOUS_CHALLENGE"]:
    c_rows = [r for r in results if r["cohort"] == cohort]
    c_dec = Counter(r["model_decision"] for r in c_rows)
    c_gold = Counter(r["gold_label"] for r in c_rows)
    print(f"Cohort {cohort} (total {len(c_rows)}): Gold={dict(c_gold)}, Model={dict(c_dec)}")

# By Category
print("\n--- BY CATEGORY ---")
cats = sorted(list(set(r["category_code"] for r in results)))
for c in cats:
    c_rows = [r for r in results if r["category_code"] == c]
    total_c = len(c_rows)
    pos_c = [r for r in c_rows if r["gold_label"] == "CLEAR_POSITIVE"]
    neg_c = [r for r in c_rows if r["gold_label"] == "CLEAR_NEGATIVE"]
    amb_c = [r for r in c_rows if r["gold_label"] == "AMBIGUOUS"]
    
    conf_c = sum(1 for r in c_rows if r["model_decision"] == "CONFIRMED")
    rej_c = sum(1 for r in c_rows if r["model_decision"] == "REJECTED")
    unk_c = sum(1 for r in c_rows if r["model_decision"] == "UNKNOWN")

    false_rej = sum(1 for r in pos_c if r["model_decision"] == "REJECTED")
    false_conf = sum(1 for r in neg_c if r["model_decision"] == "CONFIRMED")

    pos_rate = (sum(1 for r in pos_c if r["model_decision"] == "CONFIRMED") / len(pos_c)) if pos_c else 1.0
    neg_rate = (sum(1 for r in neg_c if r["model_decision"] == "REJECTED") / len(neg_c)) if neg_c else 1.0

    print(f"Category: {c} (total {total_c}) | Pos:{len(pos_c)}, Neg:{len(neg_c)}, Amb:{len(amb_c)} | Model: Conf:{conf_c}, Rej:{rej_c}, Unk:{unk_c} | FalseRej:{false_rej}, FalseConf:{false_conf} | PosRate:{pos_rate*100:.1f}%, NegRate:{neg_rate*100:.1f}%")

# Critical Errors Breakdown
print("\n--- CRITICAL ERRORS: FALSE REJECT CLEAR POSITIVE (Total: {}) ---".format(len(data['critical_errors']['false_reject_positives'])))
for idx, err in enumerate(data['critical_errors']['false_reject_positives'], 1):
    print(f"  {idx}. Detail {err['detail_id']} | Cat: {err['category_code']} ({err['subcategory_code']}) | Term: '{err['matched_term']}' | Model Reason Code: {err['reason_code']} | Reason: {err['reason']}")

print("\n--- CRITICAL ERRORS: FALSE CONFIRM CLEAR NEGATIVE (Total: {}) ---".format(len(data['critical_errors']['false_confirm_negatives'])))
for idx, err in enumerate(data['critical_errors']['false_confirm_negatives'], 1):
    print(f"  {idx}. Detail {err['detail_id']} | Cat: {err['category_code']} | Term: '{err['matched_term']}' | Reason: {err['reason']}")

print("\n--- AMBIGUOUS OVERCONFIDENCE (Total: {}) ---".format(len(data['critical_errors']['ambiguous_overconf'])))
for idx, err in enumerate(data['critical_errors']['ambiguous_overconf'], 1):
    print(f"  {idx}. Detail {err['detail_id']} | Cat: {err['category_code']} | Model Dec: {err['model_decision']} | Code: {err['reason_code']} | Reason: {err['reason']}")

print("\n--- POSITIVE UNKNOWNS (Total: {}) ---".format(len(data['critical_errors']['positive_unknowns'])))
for idx, err in enumerate(data['critical_errors']['positive_unknowns'], 1):
    print(f"  {idx}. Detail {err['detail_id']} | Cat: {err['category_code']} ({err['subcategory_code']}) | Term: '{err['matched_term']}' | Reason Code: {err['reason_code']}")
