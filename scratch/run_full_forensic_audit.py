#!/usr/bin/env python3
"""
R3-4F-D Comprehensive Forensic Audit Engine.

Executes all forensic analysis steps (Sections 3 to 22) deterministically on S13.
"""

import os
import json
import re
import hashlib
from collections import Counter

manifest_path = "/tmp/r3_4fca_holdout_manifest.json"
results_path = "/tmp/r3_4fcc_eval_results.json"

with open(manifest_path, "r", encoding="utf-8") as f:
    manifest_data = json.load(f)

with open(results_path, "r", encoding="utf-8") as f:
    results_data = json.load(f)

m_records = manifest_data["records"]
r_records = results_data["records"]

m_by_id = {r["detail_id"]: r for r in m_records}
r_by_id = {r["detail_id"]: r for r in r_records}

print("=" * 80)
print("1. RAW MODEL RESPONSES & PATTERN COLLAPSE (Section 6)")
print("=" * 80)

raw_responses = [r.get("raw_model_response", "") for r in r_records]
unique_raw_responses = set(raw_responses)
print(f"Total rows: {len(r_records)}")
print(f"Unique raw responses: {len(unique_raw_responses)}")

normalized_patterns = Counter()
for resp in raw_responses:
    # Normalize detail_id, whitespace, punctuation
    norm = re.sub(r'"detail_id"\s*:\s*\d+', '"detail_id": X', resp)
    norm = re.sub(r'\s+', ' ', norm).strip()
    normalized_patterns[norm] += 1

print(f"Unique normalized response patterns: {len(normalized_patterns)}")
for pat, cnt in normalized_patterns.most_common(5):
    print(f"  Count={cnt}: {pat[:120]}...")

print("\n" + "=" * 80)
print("2. TRUNCATION MARKER CORRELATION (Section 11)")
print("=" * 80)

marker_before = "...[контекст до совпадения сокращён]..."
marker_after = "...[контекст после совпадения сокращён]..."
marker_mline = "...[строка совпадения сокращена]..."

rows_with_any_marker = 0
rows_with_before_marker = 0
rows_with_after_marker = 0
rows_with_mline_marker = 0

pos_with_marker = 0
neg_with_marker = 0
amb_with_marker = 0

for r in r_records:
    block = r_by_id[r["detail_id"]].get("context_block", "")
    gold = r["gold_label"]
    has_b = marker_before in block
    has_a = marker_after in block
    has_m = marker_mline in block
    has_any = has_b or has_a or has_m

    if has_any:
        rows_with_any_marker += 1
        if gold == "CLEAR_POSITIVE": pos_with_marker += 1
        elif gold == "CLEAR_NEGATIVE": neg_with_marker += 1
        elif gold == "AMBIGUOUS": amb_with_marker += 1

    if has_b: rows_with_before_marker += 1
    if has_a: rows_with_after_marker += 1
    if has_m: rows_with_mline_marker += 1

print(f"ROWS_WITH_ANY_TRUNCATION_MARKER: {rows_with_any_marker} / 40")
print(f"  ROWS_WITH_BEFORE_MARKER: {rows_with_before_marker}")
print(f"  ROWS_WITH_AFTER_MARKER: {rows_with_after_marker}")
print(f"  ROWS_WITH_MATCH_LINE_MARKER: {rows_with_mline_marker}")
print(f"  CLEAR_POSITIVE_WITH_MARKER: {pos_with_marker} / 27")
print(f"  CLEAR_NEGATIVE_WITH_MARKER: {neg_with_marker} / 11")
print(f"  AMBIGUOUS_WITH_MARKER: {amb_with_marker} / 2")

print("\n" + "=" * 80)
print("3. GOLD POSITIVE EVIDENCE STRENGTH (Section 12 & 13)")
print("=" * 80)

pos_records = [r for r in r_records if r["gold_label"] == "CLEAR_POSITIVE"]
evidence_classes = Counter()

strong_positives = []
suspect_positives = []

for r in pos_records:
    vis = r["visible_source_text"]
    quote = r["gold_supporting_quote"]
    sub = r["subcategory_code"]

    has_qty = bool(re.search(r"\d+\s*(шт|м|м2|м3|кг|т|п\.м|компл|набор)", vis, re.IGNORECASE))
    has_tech = any(w in vis.lower() for w in ["вт", "мм", "см", "кг", "квт", "дку", "гост", "паспорт", "марк", "серия"])
    has_spec = any(w in vis.lower() for w in ["спецификац", "ведомост", "вор ", "смета", "чертеж", "лист", "таблица"])

    classes = []
    if has_qty: classes.append("QUANTITY_UNIT")
    if has_tech: classes.append("TECHNICAL_CHARACTERISTICS")
    if has_spec: classes.append("SPECIFICATION_ROW")
    if not classes: classes.append("GENERIC_CONTEXT_ONLY")

    for c in classes:
        evidence_classes[c] += 1

    if "GENERIC_CONTEXT_ONLY" in classes:
        suspect_positives.append(r)
    else:
        strong_positives.append(r)

print(f"STRONG_POSITIVE_ROWS: {len(strong_positives)}")
print(f"SUSPECT_POSITIVE_ROWS: {len(suspect_positives)}")
print(f"Evidence Classes: {dict(evidence_classes)}")

print("\nTop 10 Strongest Positives Audit:")
for idx, r in enumerate(strong_positives[:10], 1):
    print(f"  [{idx}] detail_id={r['detail_id']} ({r['category_code']}/{r['subcategory_code']}): term='{r['matched_term']}'")
    print(f"      visible_source sample: {repr(r['visible_source_text'][:100])}")
    print(f"      gold_quote: '{r['gold_supporting_quote']}'")
    print(f"      raw_reason: '{r['final_reason']}'")

print("\n" + "=" * 80)
print("4. LITERAL SUBCATEGORY NAME HYPOTHESIS (Section 15)")
print("=" * 80)

literal_match_cnt = 0
no_literal_match_cnt = 0

for r in pos_records:
    sub_name = r.get("subcategory_name", "").lower()
    vis = r["visible_source_text"].lower()

    if sub_name and sub_name in vis:
        literal_match_cnt += 1
    else:
        no_literal_match_cnt += 1

print(f"VISIBLE_SOURCE_CONTAINS_LITERAL_SUBCATEGORY_NAME: {literal_match_cnt} / 27")
print(f"VISIBLE_SOURCE_DOES_NOT_CONTAIN_LITERAL_SUBCATEGORY_NAME: {no_literal_match_cnt} / 27")

print("\n" + "=" * 80)
print("5. MATCHED TERM RELATIONSHIP (Section 16)")
print("=" * 80)

exact_term_cnt = 0
variant_term_cnt = 0
no_term_cnt = 0

for r in pos_records:
    term = r.get("matched_term", "").lower().strip()
    vis = r["visible_source_text"].lower()

    if not term:
        no_term_cnt += 1
    elif term in vis:
        exact_term_cnt += 1
    else:
        # Check stem
        stem = term[:len(term)-2] if len(term) > 4 else term
        if stem in vis:
            variant_term_cnt += 1
        else:
            no_term_cnt += 1

print(f"POSITIVE_EXACT_TERM: {exact_term_cnt} / 27")
print(f"POSITIVE_VARIANT_TERM: {variant_term_cnt} / 27")
print(f"POSITIVE_NO_TERM: {no_term_cnt} / 27")

print("\n" + "=" * 80)
print("6. CLEAR NEGATIVE FORENSIC (Section 17)")
print("=" * 80)

neg_records = [r for r in r_records if r["gold_label"] == "CLEAR_NEGATIVE"]
neg_classes = Counter()

for r in neg_records:
    vis = r["visible_source_text"].lower()
    phrase = r.get("matched_term", "").lower()

    if any(w in vis for w in ["ооо ", "зао ", "пао ", "администрация", "институт", "департамент"]):
        neg_classes["ORGANIZATION"] += 1
    elif any(w in vis for w in ["ул.", "проспект", "район", "г. ", "область"]):
        neg_classes["ADDRESS_LOCATION"] += 1
    elif any(w in vis for w in ["договор", "подрядчик", "согласован", "акт", "приложение"]):
        neg_classes["LEGAL_ADMIN"] += 1
    else:
        neg_classes["LEXICAL_COLLISION"] += 1

print(f"CLEAR_NEGATIVE count: {len(neg_records)}")
print(f"Negative Classes: {dict(neg_classes)}")

print("\nAll 11 CLEAR_NEGATIVE rows:")
for idx, r in enumerate(neg_records, 1):
    print(f"  [{idx}] detail_id={r['detail_id']} ({r['category_code']}/{r['subcategory_code']}): term='{r['matched_term']}'")
    print(f"      visible_source sample: {repr(r['visible_source_text'][:100])}")
    print(f"      gold_quote: '{r['gold_supporting_quote']}'")
    print(f"      raw_reason: '{r['final_reason']}'")

print("\n" + "=" * 80)
print("7. AMBIGUOUS ROWS (Section 18)")
print("=" * 80)

amb_records = [r for r in r_records if r["gold_label"] == "AMBIGUOUS"]
for idx, r in enumerate(amb_records, 1):
    print(f"  [{idx}] detail_id={r['detail_id']} ({r['category_code']}/{r['subcategory_code']}): term='{r['matched_term']}'")
    print(f"      visible_source: {repr(r['visible_source_text'])}")
    print(f"      gold_reason: {r['gold_reason']}")
    print(f"      raw_decision: {r['raw_decision']}, final_decision: {r['final_decision']}, reason: {r['final_reason']}")

print("\n" + "=" * 80)
print("8. SUB-CATEGORY DISPLAY LABELS AUDIT (Section 14)")
print("=" * 80)

human_readable_cnt = 0
code_only_cnt = 0
truncated_cnt = 0

for r in r_records:
    cat_n = r.get("category_name", "")
    sub_n = r.get("subcategory_name", "")
    cat_c = r.get("category_code", "")
    sub_c = r.get("subcategory_code", "")

    if sub_n and sub_n != sub_c:
        human_readable_cnt += 1
    else:
        code_only_cnt += 1

print(f"HUMAN_READABLE_SUBCATEGORY_ROWS: {human_readable_cnt} / 40")
print(f"CODE_ONLY_SUBCATEGORY_ROWS: {code_only_cnt} / 40")
print(f"TRUNCATED_SUBCATEGORY_LABEL_ROWS: {truncated_cnt} / 40")
