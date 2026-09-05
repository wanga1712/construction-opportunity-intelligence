#!/usr/bin/env python3
"""
R3-4F-C-A Final Report & Protocol Audit Script.
Validates exact failure corpus and outputs final report format required by Section 32.
"""
import os
import json
import hashlib

manifest_path = "/tmp/r3_4fca_holdout_manifest.json"
assert os.path.exists(manifest_path), "Manifest must exist"

with open(manifest_path, "r", encoding="utf-8") as f:
    manifest_data = json.load(f)

with open(manifest_path, "rb") as f:
    manifest_sha256 = hashlib.sha256(f.read()).hexdigest()

records = manifest_data["records"]

proc_counts = {}
doc_counts = {}
cat_counts = {}
gold_dist = {}
cohort_dist = {}

for r in records:
    pid = r["procurement_id"]
    doc = r["document_name"]
    cat = r["category_code"]
    gold = r["gold_label"]
    cohort = r["cohort"]

    proc_counts[pid] = proc_counts.get(pid, 0) + 1
    doc_counts[doc] = doc_counts.get(doc, 0) + 1
    cat_counts[cat] = cat_counts.get(cat, 0) + 1
    gold_dist[gold] = gold_dist.get(gold, 0) + 1
    cohort_dist[cohort] = cohort_dist.get(cohort, 0) + 1

max_proc_count = max(proc_counts.values()) if proc_counts else 0
max_doc_count = max(doc_counts.values()) if doc_counts else 0

print("=" * 80)
print("PRE-MODEL PROTOCOL GATE AUDIT RESULT — R3-4F-C-A")
print("=" * 80)
print(f"Total Selected Candidates: {len(records)}")
print(f"Unique Categories: {len(cat_counts)}")
print(f"Unique Procurements: {len(proc_counts)}")
print(f"Unique Documents: {len(doc_counts)}")
print(f"Max Rows per Procurement: {max_proc_count} (Limit: <= 3)")
print(f"Max Rows per Document: {max_doc_count} (Limit: <= 2)")
print(f"Manifest SHA256: {manifest_sha256}")

print("\nCategory breakdown in sample:")
for cat, cnt in cat_counts.items():
    print(f"  {cat:<32}: {cnt} rows")

print("\nGold distribution in sample:")
for gold, cnt in gold_dist.items():
    print(f"  {gold}: {cnt} rows")

print("\nCohort distribution in sample:")
for cohort, cnt in cohort_dist.items():
    print(f"  {cohort}: {cnt} rows")

failed_gates = []
if len(records) < 40 or len(records) > 45:
    failed_gates.append(f"TOTAL={len(records)} not in [40, 45]")
if min(cat_counts.values()) < 2:
    failed_cat = [k for k, v in cat_counts.items() if v < 2]
    failed_gates.append(f"MIN_ROWS_EACH_CATEGORY < 2 for category {failed_cat} (physical DB capacity exhaustion under procurement cap)")
if gold_dist.get("AMBIGUOUS", 0) < 5:
    failed_gates.append(f"AMBIGUOUS={gold_dist.get('AMBIGUOUS', 0)} < 5 (fresh candidate pool contains only {gold_dist.get('AMBIGUOUS', 0)} factual ambiguous rows)")

print(f"\nFAILED PRE-MODEL GATES: {failed_gates}")
