#!/usr/bin/env python3
"""Inspect row_data shapes for 10 diverse detail rows. READ-ONLY."""
import json
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")
from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

conn = get_doc_db_connection()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# Pick 10 diverse IDs from 35176..35275
ids = [35176, 35180, 35190, 35200, 35210, 35220, 35230, 35240, 35260, 35275]

cur.execute("""
    SELECT d.id, d.matched_term, d.match_method, d.category_code, d.subcategory_code,
           d.context_before AS db_cb, d.context_after AS db_ca,
           d.row_data, d.page_or_sheet, d.row_number,
           pg_typeof(d.context_before) AS cb_pgtype,
           pg_typeof(d.context_after) AS ca_pgtype,
           pg_typeof(d.row_data) AS rd_pgtype
    FROM document_match_details d
    WHERE d.id = ANY(%s)
    ORDER BY d.id
""", (ids,))

rows = cur.fetchall()

for r in rows:
    print(f"{'='*60}")
    print(f"DETAIL_ID={r['id']}")
    print(f"TERM='{r['matched_term']}' CAT={r['category_code']}/{r['subcategory_code']}")
    print(f"DB context_before pgtype={r['cb_pgtype']}, value_type={type(r['db_cb']).__name__}, "
          f"is_empty={r['db_cb'] in (None, {}, [], '', '{}', '[]')}")
    print(f"DB context_after  pgtype={r['ca_pgtype']}, value_type={type(r['db_ca']).__name__}, "
          f"is_empty={r['db_ca'] in (None, {}, [], '', '{}', '[]')}")
    print(f"DB row_data pgtype={r['rd_pgtype']}, value_type={type(r['row_data']).__name__}")

    rd = r['row_data']
    if isinstance(rd, dict):
        print(f"  ROW_DATA top-level keys: {sorted(rd.keys())}")
        # matched_line or equivalent
        for k in ['matched_line', 'matched_display_text', 'text']:
            if k in rd:
                val = rd[k]
                print(f"  rd['{k}'] type={type(val).__name__}, val='{str(val)[:80]}'")
        # context_before
        cb = rd.get('context_before')
        if cb is not None:
            print(f"  rd['context_before'] type={type(cb).__name__}, len={len(cb) if isinstance(cb, list) else 'N/A'}")
            if isinstance(cb, list) and cb:
                print(f"    first: '{str(cb[0])[:80]}'")
        # context_after
        ca = rd.get('context_after')
        if ca is not None:
            print(f"  rd['context_after'] type={type(ca).__name__}, len={len(ca) if isinstance(ca, list) else 'N/A'}")
            if isinstance(ca, list) and ca:
                print(f"    first: '{str(ca[0])[:80]}'")
        # values/headers/raw_cells
        for k in ['values', 'headers', 'raw_cells', 'column_map', 'context_lines', 'header_line_number']:
            if k in rd:
                val = rd[k]
                if isinstance(val, (dict, list)):
                    print(f"  rd['{k}'] type={type(val).__name__}, len={len(val)}")
                    if isinstance(val, list) and val:
                        print(f"    first: {json.dumps(val[0], ensure_ascii=False, default=str)[:100]}")
                    elif isinstance(val, dict) and val:
                        print(f"    keys: {list(val.keys())[:5]}")
                else:
                    print(f"  rd['{k}'] = {val}")
    elif isinstance(rd, str):
        print(f"  ROW_DATA is str, len={len(rd)}")
    else:
        print(f"  ROW_DATA is {type(rd).__name__}")

# Also check a wider set for unique row_data key patterns
cur.execute("""
    SELECT DISTINCT jsonb_object_keys(row_data) AS k
    FROM document_match_details
    WHERE id BETWEEN 35176 AND 35275
      AND row_data IS NOT NULL
    ORDER BY k
""")
all_keys = [r['k'] for r in cur.fetchall()]
print(f"\n{'='*60}")
print(f"ALL DISTINCT row_data KEYS across 35176..35275:")
print(f"  {all_keys}")

# Check if any rows have non-empty DB context_before/after
cur.execute("""
    SELECT count(*) AS total,
           count(*) FILTER (WHERE context_before IS NOT NULL AND context_before != '{}' AND context_before != '[]' AND context_before != 'null') AS cb_nonempty,
           count(*) FILTER (WHERE context_after IS NOT NULL AND context_after != '{}' AND context_after != '[]' AND context_after != 'null') AS ca_nonempty
    FROM document_match_details
    WHERE id BETWEEN 35176 AND 35275
""")
stats = cur.fetchone()
print(f"\nDB COLUMN STATS (35176..35275):")
print(f"  TOTAL={stats['total']}")
print(f"  context_before NOT EMPTY={stats['cb_nonempty']}")
print(f"  context_after NOT EMPTY={stats['ca_nonempty']}")

# Also check globally how many rows have empty vs non-empty DB context
cur.execute("""
    SELECT count(*) AS total,
           count(*) FILTER (WHERE context_before IS NOT NULL AND context_before != '{}' AND context_before != '[]') AS cb_nonempty,
           count(*) FILTER (WHERE context_after IS NOT NULL AND context_after != '{}' AND context_after != '[]') AS ca_nonempty,
           count(*) FILTER (WHERE row_data IS NOT NULL) AS rd_notnull
    FROM document_match_details
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
    LIMIT 1
""")
gstats = cur.fetchone()
print(f"\nDB COLUMN STATS (ALL S13_V4):")
print(f"  TOTAL={gstats['total']}")
print(f"  context_before NOT EMPTY={gstats['cb_nonempty']}")
print(f"  context_after NOT EMPTY={gstats['ca_nonempty']}")
print(f"  row_data NOT NULL={gstats['rd_notnull']}")

conn.close()
