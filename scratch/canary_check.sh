#!/bin/bash
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import psycopg2
import psycopg2.extras
import json

doc_dsn = {"host": "127.0.0.1", "port": 5432, "dbname": "document_intelligence", "user": "crm_app", "password": "X17B3n5hbANQSRt6i7WIyy0lJudX"}
doc_conn = psycopg2.connect(**doc_dsn)

print("=== Queue Status ===")
with doc_conn.cursor() as cur:
    cur.execute("SELECT status, COUNT(*) FROM document_processing_queue GROUP BY status ORDER BY status")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")

print("\n=== 3 Sample Queue Items ===")
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT id, procurement_id, source_table, contract_number, 
               research_action, queue_lane, pipeline_generation, status, created_at
        FROM document_processing_queue 
        ORDER BY id 
        LIMIT 3
    """)
    for row in cur.fetchall():
        print(json.dumps(dict(row), default=str, indent=2))

print("\n=== Active daemon processing? ===")
with doc_conn.cursor() as cur:
    cur.execute("SELECT COUNT(*) FROM document_processing_queue WHERE status='PROCESSING'")
    processing = cur.fetchone()[0]
    print(f"  Processing: {processing}")
    
    cur.execute("SELECT COUNT(*) FROM document_processing_queue WHERE status='COMPLETED'")
    completed = cur.fetchone()[0]
    print(f"  Completed: {completed}")

# Also check document_files
print("\n=== document_files count ===")
with doc_conn.cursor() as cur:
    cur.execute("SELECT COUNT(*) FROM document_files")
    print(f"  document_files: {cur.fetchone()[0]}")
    
    cur.execute("SELECT COUNT(*) FROM document_processing_results")
    print(f"  document_processing_results: {cur.fetchone()[0]}")

PYEOF
