import sys
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')

import psycopg2
import psycopg2.extras

# Count procurements with document links using bulk query
tender_monitor_dsn = {
    "host": "10.8.0.7",
    "port": 5432,
    "dbname": "tender_monitor",
    "user": "postgres",
    "password": "oTIg3EqK85pux8SfZTuCbS-bEcObXiGfV3P2hU2m5uJ_pYMbRtRmP8jnMA-hvyhR",
}

crm_dsn = {
    "host": "127.0.0.1",
    "port": 5432,
    "dbname": "crm",
    "user": "crm_app",
    "password": "X17B3n5hbANQSRt6i7WIyy0lJudX",
}

doc_dsn = {
    "host": "127.0.0.1",
    "port": 5432,
    "dbname": "document_intelligence",
    "user": "crm_app",
    "password": "X17B3n5hbANQSRt6i7WIyy0lJudX",
}

print("Connecting to CRM DB...")
crm_conn = psycopg2.connect(**crm_dsn)
crm_conn.autocommit = True

with crm_conn.cursor() as cur:
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename ILIKE '%procurement%' LIMIT 10")
    tables = [r[0] for r in cur.fetchall()]
    print(f"Procurement tables: {tables}")
    
    # Use the correct table name
    proc_table = next((t for t in tables if 'v3' in t or 'procurement' in t), None)
    if proc_table:
        cur.execute(f"SELECT COUNT(*) FROM {proc_table}")
        total_procs = cur.fetchone()[0]
        print(f"Total CRM procurements ({proc_table}): {total_procs}")
    
    # Check crm_stage values
    for tname in tables[:3]:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {tname}")
            cnt = cur.fetchone()[0]
            print(f"  {tname}: {cnt} rows")
        except:
            pass

print("\nConnecting to document_intelligence DB...")
doc_conn = psycopg2.connect(**doc_dsn)
with doc_conn.cursor() as cur:
    cur.execute("SELECT COUNT(*) FROM document_processing_queue")
    queue_count = cur.fetchone()[0]
    print(f"Current document_processing_queue rows: {queue_count}")

print("\nConnecting to tender_monitor...")
tm_conn = psycopg2.connect(**tender_monitor_dsn)
with tm_conn.cursor() as cur:
    # Check what tables exist that would have document links
    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name ILIKE '%document%'
        ORDER BY table_name
        LIMIT 20
    """)
    tables = [row[0] for row in cur.fetchall()]
    print(f"Tables with 'document' in name: {tables}")

print("AUDIT_COMPLETE=YES")
