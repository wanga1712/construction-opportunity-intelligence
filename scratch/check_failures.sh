#!/bin/bash
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import psycopg2
import psycopg2.extras
import json

doc_dsn = {"host": "127.0.0.1", "port": 5432, "dbname": "document_intelligence", "user": "crm_app", "password": "X17B3n5hbANQSRt6i7WIyy0lJudX"}
doc_conn = psycopg2.connect(**doc_dsn)

print("=== Failed tasks with error messages ===")
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT id, procurement_id, contract_number, status, last_error
        FROM document_processing_queue 
        WHERE status = 'FAILED'
        ORDER BY id
    """)
    for row in cur.fetchall():
        print(f"\nQueue ID {row['id']} (procurement {row['procurement_id']}):")
        print(f"  contract: {row['contract_number']}")
        print(f"  error: {row['last_error'][:500] if row['last_error'] else 'None'}")

print("\n\n=== document_match_details count ===")
with doc_conn.cursor() as cur:
    cur.execute("SELECT COUNT(*) FROM document_match_details")
    print(f"  document_match_details: {cur.fetchone()[0]}")
    
    cur.execute("SELECT COUNT(*) FROM document_matches")
    print(f"  document_matches: {cur.fetchone()[0]}")

print("\n=== Processing items ===")
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT id, procurement_id, contract_number, status, started_at FROM document_processing_queue WHERE status='PROCESSING' ORDER BY id")
    for row in cur.fetchall():
        print(f"  ID={row['id']}, proc={row['procurement_id']}, started={row['started_at']}")
PYEOF
