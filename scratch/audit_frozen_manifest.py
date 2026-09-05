#!/usr/bin/env python3
"""Inspect frozen manifest distributions before model run."""
import json
from collections import Counter

with open("/tmp/r3_4f_holdout_manifest.json", "r", encoding="utf-8") as f:
    data = json.load(f)

records = data["records"]
total = len(records)
sha = data["manifest_sha256"]

by_cohort = Counter(r["cohort"] for r in records)
by_gold = Counter(r["gold_label"] for r in records)
by_cat = Counter(r["category_code"] for r in records)
by_sub = Counter(r["subcategory_code"] for r in records)
by_method = Counter(r["match_method"] for r in records)
by_pid = Counter(r["procurement_id"] for r in records)
by_doc = Counter(r["document_name"] for r in records)
top_terms = Counter(r["matched_term"] for r in records).most_common(5)

waterproofing_count = by_cat.get("waterproofing", 0) + by_cat.get("waterproofing_concrete_repair", 0)
wp_share = (by_cat.get("waterproofing", 0) / total) * 100

print("=" * 60)
print("FROZEN HOLDOUT MANIFEST AUDIT BEFORE MODEL RUN")
print("=" * 60)
print(f"MANIFEST_SHA256={sha}")
print(f"GOLD_FROZEN_BEFORE_MODEL={data['gold_frozen_before_model']}")
print(f"TOTAL_HOLDOUT_COUNT={total}")
print(f"UNIQUE_PROCUREMENTS={len(by_pid)}")
print(f"UNIQUE_DOCUMENTS={len(by_doc)}")
print(f"CATEGORY_COUNT={len(by_cat)}")
print(f"SUBCATEGORY_COUNT={len(by_sub)}")
print(f"MAX_ROWS_PER_PROCUREMENT={max(by_pid.values())}")
print(f"WATERPROOFING_SHARE={wp_share:.2f}% (<= 30%)")
print("\nBY_COHORT:", dict(by_cohort))
print("BY_GOLD_LABEL:", dict(by_gold))
print("BY_CATEGORY:", dict(by_cat))
print("BY_SUBCATEGORY:", dict(by_sub))
print("BY_MATCH_METHOD:", dict(by_method))
print("TOP_TERMS:", top_terms)
print("=" * 60)
