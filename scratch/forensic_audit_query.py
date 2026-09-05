#!/usr/bin/env python3
"""READ-ONLY forensic audit of the completed 100-row bounded natural run.
NO model calls. NO code changes. NO validation runs."""
import json
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    PIPELINE_GENERATION,
)

doc_conn = get_doc_db_connection()

# 1. Find exactly the 100 rows validated by the completed run
# They were validated today (2026-09-01) by validator_name='context_validator', validator_version='v1'
# and have validation_method='QWEN_CONTEXT_V1'
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT d.id as detail_id, d.match_id, d.procurement_id,
               d.category_code, d.subcategory_code,
               d.matched_term, d.term_type, d.score,
               d.row_data, d.page_or_sheet, d.row_number,
               d.context_before, d.context_after, d.match_method,
               d.validation_status, d.validation_reason, d.validation_method,
               d.validator_version, d.validated_at,
               d.pipeline_generation,
               m.document_name, m.archive_member_path
        FROM document_match_details d
        JOIN document_matches m ON d.match_id = m.id
        WHERE d.validation_method = 'QWEN_CONTEXT_V1'
          AND d.validator_version = 'v1'
          AND d.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
          AND d.validated_at IS NOT NULL
        ORDER BY d.validated_at DESC
        LIMIT 300
    """)
    all_validated = cur.fetchall()

print(f"TOTAL_VALIDATED_ROWS_IN_DB={len(all_validated)}")

# Group by validated_at to find the run batches
from collections import Counter
import datetime

# Find the time range of the most recent natural run (approx 14:22-14:34 +03:00, i.e. 11:22-11:34 UTC)
# But we need to find the actual batch
validated_times = sorted(set(r["validated_at"] for r in all_validated if r["validated_at"]), reverse=True)
print(f"DISTINCT_VALIDATED_AT_TIMESTAMPS={len(validated_times)}")
if validated_times:
    print(f"NEWEST_VALIDATED_AT={validated_times[0]}")
    print(f"OLDEST_VALIDATED_AT={validated_times[-1]}")

# Identify runs: group by minute
by_minute = Counter()
for r in all_validated:
    if r["validated_at"]:
        minute = r["validated_at"].strftime("%Y-%m-%d %H:%M") if hasattr(r["validated_at"], 'strftime') else str(r["validated_at"])[:16]
        by_minute[minute] += 1

print(f"\nVALIDATED_ROWS_BY_MINUTE:")
for minute, cnt in sorted(by_minute.items(), reverse=True):
    print(f"  {minute}: {cnt}")

# The last run should be the ones validated after the previous runs
# Let's look at all validation_status distribution
status_counts = Counter(r["validation_status"] for r in all_validated)
print(f"\nVALIDATION_STATUS_DISTRIBUTION (all validated rows):")
for s, c in status_counts.most_common():
    print(f"  {s}: {c}")

# Now output the full details for forensic audit
output = []
for r in all_validated:
    row_data = r.get("row_data")
    if isinstance(row_data, str):
        try: row_data = json.loads(row_data)
        except: row_data = {}
    elif row_data is None:
        row_data = {}

    matched_line = ""
    if isinstance(row_data, dict):
        matched_line = row_data.get("matched_line", "") or row_data.get("matched_display_text", "") or row_data.get("text", "")

    context_before = r.get("context_before")
    if isinstance(context_before, str):
        try: context_before = json.loads(context_before)
        except: context_before = [context_before]
    elif context_before is None:
        context_before = []

    context_after = r.get("context_after")
    if isinstance(context_after, str):
        try: context_after = json.loads(context_after)
        except: context_after = [context_after]
    elif context_after is None:
        context_after = []

    output.append({
        "detail_id": r["detail_id"],
        "procurement_id": r["procurement_id"],
        "category_code": r["category_code"],
        "subcategory_code": r["subcategory_code"],
        "matched_term": r["matched_term"],
        "term_type": r.get("term_type"),
        "match_method": r["match_method"],
        "score": float(r["score"]) if r.get("score") else None,
        "document_name": r["document_name"],
        "archive_member_path": r.get("archive_member_path"),
        "page_or_sheet": r.get("page_or_sheet"),
        "row_number": r.get("row_number"),
        "matched_line": matched_line[:200] if matched_line else "",
        "context_before": context_before[:3] if isinstance(context_before, list) else [],
        "context_after": context_after[:3] if isinstance(context_after, list) else [],
        "context_before_present": bool(context_before),
        "context_after_present": bool(context_after),
        "validation_status": r["validation_status"],
        "validation_reason": r.get("validation_reason", "")[:200],
        "validation_method": r["validation_method"],
        "validator_version": r.get("validator_version"),
        "validated_at": str(r["validated_at"]),
        "pipeline_generation": r["pipeline_generation"],
    })

# Distribution analysis
terms = Counter(r["matched_term"] for r in output)
categories = Counter(r["category_code"] for r in output)
subcategories = Counter(f"{r['category_code']}/{r['subcategory_code']}" for r in output)
methods = Counter(r["match_method"] for r in output)
procurements = Counter(r["procurement_id"] for r in output)
documents = Counter(r["document_name"] for r in output)

print(f"\n--- DISTRIBUTION FOR ALL {len(output)} VALIDATED ROWS ---")
print(f"\nBY_MATCH_METHOD:")
for m, c in methods.most_common():
    print(f"  {m}: {c}")

print(f"\nBY_CATEGORY:")
for cat, c in categories.most_common():
    print(f"  {cat}: {c}")

print(f"\nBY_SUBCATEGORY:")
for sub, c in subcategories.most_common():
    print(f"  {sub}: {c}")

print(f"\nTOP_TERMS_30:")
for t, c in terms.most_common(30):
    print(f"  '{t}': {c}")

print(f"\nBY_PROCUREMENT:")
for p, c in procurements.most_common():
    print(f"  PID={p}: {c}")

print(f"\nUNIQUE_PROCUREMENTS={len(procurements)}")
print(f"UNIQUE_DOCUMENTS={len(documents)}")
print(f"UNIQUE_TERMS={len(terms)}")

# Context quality
matched_text_present = sum(1 for r in output if r["matched_line"])
before_present = sum(1 for r in output if r["context_before_present"])
after_present = sum(1 for r in output if r["context_after_present"])

print(f"\nCONTEXT_QUALITY:")
print(f"MATCHED_TEXT_PRESENT={matched_text_present}/{len(output)}")
print(f"CONTEXT_BEFORE_PRESENT={before_present}/{len(output)}")
print(f"CONTEXT_AFTER_PRESENT={after_present}/{len(output)}")

with open("/opt/CRM_Streamlit/forensic_audit_data.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2, default=str)

print(f"\nSAVED forensic_audit_data.json ({len(output)} rows)")

doc_conn.close()
