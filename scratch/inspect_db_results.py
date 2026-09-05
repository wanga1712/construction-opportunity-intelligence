import os
import json
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

conn = psycopg2.connect(
    dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
    user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
    password=os.getenv("S13_DOCUMENT_DB_PASSWORD"),
    host=os.getenv("S13_DOCUMENT_DB_HOST", "localhost"),
    port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
)

with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
    cur.execute("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'document_match_details'
        ORDER BY ordinal_position
    """)
    print("COLUMNS:")
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]}")

    cur.execute("""
        SELECT validation_status, count(*) 
        FROM document_match_details 
        GROUP BY validation_status
    """)
    print("\nMATCH DETAILS STATUS BREAKDOWN:")
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]}")

    cur.execute("""
        SELECT *
        FROM document_match_details
        WHERE validation_status = 'CONFIRMED'
        ORDER BY id DESC
        LIMIT 10
    """)
    rows = cur.fetchall()
    print(f"\nCONFIRMED ROWS SAMPLE (total {len(rows)}):")
    for r in rows:
        print(dict(r))

    cur.execute("""
        SELECT *
        FROM document_evidence
        WHERE validation_status = 'CONFIRMED'
        ORDER BY created_at DESC
        LIMIT 10
    """)
    ev_rows = cur.fetchall()
    print(f"\nDOCUMENT EVIDENCE CONFIRMED ROWS (total {len(ev_rows)}):")
    for r in ev_rows:
        print(dict(r))

    cur.execute("""
        SELECT validation_status, count(*)
        FROM document_evidence
        GROUP BY validation_status
    """)
    print("\nDOCUMENT EVIDENCE STATUS BREAKDOWN:")
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]}")

conn.close()
