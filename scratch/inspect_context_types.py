#!/usr/bin/env python3
"""Inspect the context_before/context_after DB columns vs row_data nested context."""
import json
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

conn = get_doc_db_connection()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

cur.execute("""
    SELECT id, matched_term, 
           context_before AS db_context_before,
           context_after AS db_context_after,
           pg_typeof(context_before) AS cb_type,
           pg_typeof(context_after) AS ca_type,
           row_data
    FROM document_match_details
    WHERE id IN (35176, 35200, 35250, 35275)
    ORDER BY id
""")

for row in cur.fetchall():
    print(f"=== ID={row['id']}, TERM='{row['matched_term']}' ===")
    print(f"  DB context_before type={row['cb_type']}, value={json.dumps(row['db_context_before'], ensure_ascii=False, default=str)[:200]}")
    print(f"  DB context_after type={row['ca_type']}, value={json.dumps(row['db_context_after'], ensure_ascii=False, default=str)[:200]}")
    
    rd = row['row_data']
    if isinstance(rd, dict):
        rd_cb = rd.get('context_before', 'N/A')
        rd_ca = rd.get('context_after', 'N/A')
        print(f"  ROW_DATA context_before: {json.dumps(rd_cb, ensure_ascii=False, default=str)[:200]}")
        print(f"  ROW_DATA context_after: {json.dumps(rd_ca, ensure_ascii=False, default=str)[:200]}")

        # Check what build_context_block would see
        raw_cells = rd.get('raw_cells', [])
        if raw_cells:
            for cell in raw_cells[:2]:
                print(f"  RAW_CELL: col={cell.get('col')}, text={str(cell.get('text',''))[:80]}, header={str(cell.get('header',''))[:80]}")

# Now check what the actual matched text is for row ID 35176 which has ex-светильники
cur.execute("""
    SELECT id, matched_term, score, row_data->>'values' as rd_values,
           row_data->'raw_cells' as rd_raw_cells
    FROM document_match_details
    WHERE id = 35176
""")
r = cur.fetchone()
print(f"\n=== DETAIL ID=35176 ex-светильники RAW_CELLS ===")
cells = r['rd_raw_cells']
if isinstance(cells, list):
    for cell in cells:
        print(f"  {json.dumps(cell, ensure_ascii=False)}")

# Check the procurement 997
cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
from tender_documents_research.document_processor.context_validator_service import get_crm_db_connection
crm_conn = get_crm_db_connection()
crm_cur = crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
crm_cur.execute("SELECT id, auction_name, okpd_code, okpd_name FROM crm_procurements WHERE id = 997")
proc = crm_cur.fetchone()
print(f"\nPROCUREMENT 997:")
print(f"  TITLE: {proc['auction_name']}")
print(f"  OKPD: {proc['okpd_code']} ({proc['okpd_name']})")

conn.close()
crm_conn.close()
