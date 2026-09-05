#!/usr/bin/env python3
"""READ-ONLY inspection of row_data and context for the 100-row bounded run."""
import json
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

conn = get_doc_db_connection()

with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    # Get the last 100 validated rows (the 14:05 batch)
    cur.execute("""
        SELECT d.id, d.matched_term, d.category_code, d.subcategory_code,
               d.match_method, d.score, d.row_data, d.context_before, d.context_after,
               d.validation_status, d.validation_reason, d.validated_at,
               d.page_or_sheet, d.row_number, d.procurement_id,
               m.document_name
        FROM document_match_details d
        JOIN document_matches m ON d.match_id = m.id
        WHERE d.validation_method = 'QWEN_CONTEXT_V1'
          AND d.validator_version = 'v1'
          AND d.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
          AND d.validated_at >= '2026-09-01 14:00:00+03:00'
          AND d.validated_at <= '2026-09-01 14:10:00+03:00'
        ORDER BY d.id ASC
    """)
    last_run_rows = cur.fetchall()

print(f"LAST_RUN_EXACT_COUNT={len(last_run_rows)}")

# Show ALL with row_data inspection
for i, row in enumerate(last_run_rows):
    rd = row["row_data"]
    cb = row["context_before"]
    ca = row["context_after"]

    # Parse row_data
    matched_line = ""
    rd_type = type(rd).__name__ if rd is not None else "NULL"
    if isinstance(rd, dict):
        matched_line = rd.get("matched_line", "") or rd.get("matched_display_text", "") or rd.get("text", "") or ""
    elif isinstance(rd, str):
        try:
            parsed = json.loads(rd)
            if isinstance(parsed, dict):
                matched_line = parsed.get("matched_line", "") or parsed.get("matched_display_text", "") or parsed.get("text", "") or ""
        except:
            matched_line = rd[:100]

    cb_present = bool(cb)
    ca_present = bool(ca)

    print(f"ROW[{i+1}]: ID={row['id']}, PID={row['procurement_id']}, "
          f"TERM='{row['matched_term']}', "
          f"CAT={row['category_code']}/{row['subcategory_code']}, "
          f"METHOD={row['match_method']}, SCORE={row['score']}, "
          f"DOC={row['document_name']}, "
          f"PAGE={row.get('page_or_sheet')}, ROW={row.get('row_number')}, "
          f"STATUS={row['validation_status']}, "
          f"REASON={str(row['validation_reason'])[:80]}, "
          f"MATCHED_LINE='{matched_line[:80]}', "
          f"CTX_BEFORE={cb_present}, CTX_AFTER={ca_present}, "
          f"RD_TYPE={rd_type}")

# Summary
statuses = {}
for r in last_run_rows:
    s = r["validation_status"]
    statuses[s] = statuses.get(s, 0) + 1

print(f"\nSTATUS_SUMMARY: {statuses}")

# Context presence
ml_present = sum(1 for r in last_run_rows if r["row_data"] is not None)
cb_present = sum(1 for r in last_run_rows if r["context_before"] is not None and r["context_before"] not in [None, [], "[]", "null"])
ca_present = sum(1 for r in last_run_rows if r["context_after"] is not None and r["context_after"] not in [None, [], "[]", "null"])

print(f"ROW_DATA_NOT_NULL={ml_present}/{len(last_run_rows)}")
print(f"CONTEXT_BEFORE_NOT_NULL={cb_present}/{len(last_run_rows)}")
print(f"CONTEXT_AFTER_NOT_NULL={ca_present}/{len(last_run_rows)}")

# Check 3 confirmed rows
confirmed = [r for r in last_run_rows if r["validation_status"] == "CONFIRMED"]
print(f"\nCONFIRMED_COUNT={len(confirmed)}")
for r in confirmed:
    rd = r["row_data"]
    if isinstance(rd, dict):
        ml = rd.get("matched_line", "")
    elif isinstance(rd, str):
        try: ml = json.loads(rd).get("matched_line", "")
        except: ml = ""
    else:
        ml = ""
    print(f"  CONFIRMED: ID={r['id']}, TERM='{r['matched_term']}', CAT={r['category_code']}/{r['subcategory_code']}, LINE='{ml[:100]}', REASON={r['validation_reason'][:100]}")

conn.close()
