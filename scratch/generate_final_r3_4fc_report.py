#!/usr/bin/env python3
"""
R3-4F-C Holdout Final Report & Protocol Audit.
Validates protocol gate failure details and outputs the complete final report.
"""
import os
import json
import hashlib
from datetime import datetime, timezone

manifest_path = "/tmp/r3_4fc_holdout_manifest.json"
assert os.path.exists(manifest_path), "Manifest must exist for audit"

with open(manifest_path, "r", encoding="utf-8") as f:
    manifest_data = json.load(f)

with open(manifest_path, "rb") as f:
    manifest_sha256 = hashlib.sha256(f.read()).hexdigest()

records = manifest_data["records"]

proc_counts = {}
doc_counts = {}
cat_counts = {}
gold_dist = {}

for r in records:
    pid = r["procurement_id"]
    doc = r["document_name"]
    cat = r["category_code"]
    gold = r["gold_label"]

    proc_counts[pid] = proc_counts.get(pid, 0) + 1
    doc_counts[doc] = doc_counts.get(doc, 0) + 1
    cat_counts[cat] = cat_counts.get(cat, 0) + 1
    gold_dist[gold] = gold_dist.get(gold, 0) + 1

max_proc_count = max(proc_counts.values())
max_doc_count = max(doc_counts.values())

print("=" * 80)
print("PRE-MODEL PROTOCOL GATE AUDIT RESULT")
print("=" * 80)
print(f"Total Selected Candidates: {len(records)}")
print(f"Unique Categories: {len(cat_counts)}")
print(f"Unique Procurements: {len(proc_counts)}")
print(f"Max Rows per Procurement: {max_proc_count} (Limit: <= 3)")
print(f"Max Rows per Document: {max_doc_count} (Limit: <= 2)")
print(f"Manifest SHA256: {manifest_sha256}")

print("\nProcurement breakdown for top procurement IDs in sample:")
for pid, cnt in sorted(proc_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
    cats_in_pid = [r['category_code'] for r in records if r['procurement_id'] == pid]
    print(f"  procurement_id={pid}: {cnt} rows across categories {set(cats_in_pid)}")

print("\nCategory breakdown in sample:")
for cat, cnt in cat_counts.items():
    print(f"  {cat}: {cnt} rows")

failed_gates = []
if max_proc_count > 3:
    failed_gates.append(f"MAX_ROWS_PER_PROCUREMENT={max_proc_count} > 3 (Category 'structural_reinforcement' has only 1 procurement_id=165114 in candidate population)")

print(f"\nFAILED GATES: {failed_gates}")
