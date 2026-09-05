#!/usr/bin/env python3
"""
R3-4F-D Frozen 40 UNKNOWN Forensic Audit Engine.

Performs deterministic, model-free forensic analysis over:
1. /tmp/r3_4fca_holdout_manifest.json (SHA256: 88abe0c665e69aa3136b5605b1f811bbd6d06eb8d40d675a4a374deef93b8572)
2. /tmp/r3_4fcc_eval_results.json (SHA256: 1d8eb2a0888c0cb2a771da809970e17e995036468b9bcbf6f869546620407c8e)
"""

import os
import json
import re
import hashlib
from collections import Counter

manifest_path = "/tmp/r3_4fca_holdout_manifest.json"
results_path = "/tmp/r3_4fcc_eval_results.json"

expected_manifest_sha = "88abe0c665e69aa3136b5605b1f811bbd6d06eb8d40d675a4a374deef93b8572"
expected_results_sha = "1d8eb2a0888c0cb2a771da809970e17e995036468b9bcbf6f869546620407c8e"

with open(manifest_path, "rb") as f:
    manifest_sha = hashlib.sha256(f.read()).hexdigest()

with open(results_path, "rb") as f:
    results_sha = hashlib.sha256(f.read()).hexdigest()

print("=" * 80)
print("SECTION 2: FROZEN ARTIFACTS VERIFICATION")
print("=" * 80)
print(f"Manifest SHA256: Expected={expected_manifest_sha}, Actual={manifest_sha}, Match={manifest_sha == expected_manifest_sha}")
print(f"Results SHA256:  Expected={expected_results_sha}, Actual={results_sha}, Match={results_sha == expected_results_sha}")

with open(manifest_path, "r", encoding="utf-8") as f:
    manifest_data = json.load(f)

with open(results_path, "r", encoding="utf-8") as f:
    results_data = json.load(f)

m_records = manifest_data["records"]
r_records = results_data["records"]

assert len(m_records) == 40, f"Manifest rows={len(m_records)} != 40"
assert len(r_records) == 40, f"Results rows={len(r_records)} != 40"

m_by_id = {r["detail_id"]: r for r in m_records}
r_by_id = {r["detail_id"]: r for r in r_records}

print("\n" + "=" * 80)
print("SECTION 3 & 4: RAW VS FINAL TRANSITIONS AUDIT")
print("=" * 80)

raw_decisions = Counter()
final_decisions = Counter()
raw_reasons = Counter()
raw_reason_codes = Counter()
raw_confidences = Counter()
raw_quotes_empty = 0
raw_quotes_nonempty = 0

transitions = Counter()

for did, res in r_by_id.items():
    raw_dec = res.get("raw_decision")
    final_dec = res.get("final_decision")
    raw_conf = res.get("raw_confidence")
    raw_rcode = res.get("final_reason_code")
    raw_reas = res.get("final_reason")
    raw_q = res.get("raw_supporting_quote", "")

    raw_decisions[raw_dec] += 1
    final_decisions[final_dec] += 1
    raw_reasons[raw_reas] += 1
    raw_reason_codes[raw_rcode] += 1
    raw_confidences[raw_conf] += 1

    if not raw_q or not raw_q.strip():
        raw_quotes_empty += 1
    else:
        raw_quotes_nonempty += 1

    transitions[f"{raw_dec} -> {final_dec}"] += 1

print(f"RAW Decisions: {dict(raw_decisions)}")
print(f"FINAL Decisions: {dict(final_decisions)}")
print(f"Transitions: {dict(transitions)}")
print(f"RAW Reason Codes: {dict(raw_reason_codes)}")
print(f"RAW Confidences: {dict(raw_confidences)}")
print(f"RAW Quotes: empty={raw_quotes_empty}, nonempty={raw_quotes_nonempty}")
