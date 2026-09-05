#!/bin/bash
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import psycopg2
import psycopg2.extras
import json

doc_dsn = {"host": "127.0.0.1", "port": 5432, "dbname": "document_intelligence", "user": "crm_app", "password": "X17B3n5hbANQSRt6i7WIyy0lJudX"}
doc_conn = psycopg2.connect(**doc_dsn)

print("=== First 5 FAILED tasks error messages ===")
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT id, procurement_id, contract_number, last_error
        FROM document_processing_queue 
        WHERE status = 'FAILED'
        ORDER BY id
        LIMIT 5
    """)
    for row in cur.fetchall():
        print(f"\nQueue ID {row['id']} (procurement {row['procurement_id']}) [{row['contract_number']}]:")
        print(f"  error: {(row['last_error'] or '')[:300]}")

print("\n=== 3 COMPLETED tasks ===")
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT id, procurement_id, contract_number, completed_at
        FROM document_processing_queue 
        WHERE status = 'COMPLETED'
        ORDER BY id
    """)
    for row in cur.fetchall():
        print(f"\nQueue ID {row['id']} (procurement {row['procurement_id']}) [{row['contract_number']}], completed={row['completed_at']}")

print("\n=== document_files check ===")
with doc_conn.cursor() as cur:
    cur.execute("SELECT COUNT(*) FROM document_files")
    print(f"  document_files: {cur.fetchone()[0]}")
    
    cur.execute("SELECT COUNT(*) FROM document_match_details")
    print(f"  document_match_details: {cur.fetchone()[0]}")
    
    cur.execute("SELECT COUNT(*) FROM document_matches")
    print(f"  document_matches: {cur.fetchone()[0]}")
    
    # Check if document_files table even has the columns we'd expect
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='document_files' ORDER BY ordinal_position LIMIT 10")
    cols = [r[0] for r in cur.fetchall()]
    print(f"  document_files columns: {cols}")
PYEOF
