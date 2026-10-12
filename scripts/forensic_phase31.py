import os
import sys
sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv("/opt/CRM_Streamlit/.env")

import psycopg2
from psycopg2.extras import RealDictCursor
from src.services.crm_db_runtime import require_crm_db_connect_kwargs

crm_conn = psycopg2.connect(**require_crm_db_connect_kwargs())
doc_kw = dict(require_crm_db_connect_kwargs())
doc_kw["dbname"] = "document_intelligence"
doc_conn = psycopg2.connect(**doc_kw)

print("=== 1. DOCUMENT_PROCESSING_QUEUE COLUMNS ===")
with doc_conn.cursor(cursor_factory=RealDictCursor) as cur:
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='document_processing_queue'")
    cols = cur.fetchall()
    print("Columns in document_processing_queue:", [c["column_name"] for c in cols])

print("\n=== 2. QUEUE NONEXPIRED vs CRM_PROCUREMENTS DECOMPOSITION ===")
with doc_conn.cursor(cursor_factory=RealDictCursor) as cur:
    cur.execute("""
        SELECT COUNT(*) AS count
        FROM document_processing_queue
        WHERE status IN ('pending', 'PRE_RESEARCH_WAITING')
    """)
    print("Total pending/waiting queue:", cur.fetchone()["count"])

    cur.execute("""
        SELECT COUNT(*) AS count
        FROM document_processing_queue
        WHERE status IN ('pending', 'PRE_RESEARCH_WAITING')
          AND priority_score > 0
    """)
    print("Total pending/waiting with priority_score > 0 (non-expired):", cur.fetchone()["count"])

    cur.execute("""
        SELECT candidate_level, procurement_scope_type, COUNT(*)
        FROM document_processing_queue
        WHERE status IN ('pending', 'PRE_RESEARCH_WAITING')
          AND priority_score > 0
        GROUP BY candidate_level, procurement_scope_type
        ORDER BY count DESC
    """)
    print("Queue Non-expired breakdown (priority_score > 0):", cur.fetchall())

with crm_conn.cursor(cursor_factory=RealDictCursor) as cur:
    cur.execute("SELECT COUNT(*) FROM crm_procurements WHERE crm_stage = 'torgi'")
    print(f"crm_stage = 'torgi': {cur.fetchone()['count']}")

    cur.execute("SELECT COUNT(*) FROM crm_procurements WHERE crm_stage = 'torgi' AND award_status = 'submission_open'")
    print(f"crm_stage = 'torgi' AND award_status = 'submission_open': {cur.fetchone()['count']}")

    from src.services.commercial_routing_v3.submission_window import actionable_submission_sql
    cur.execute(f"SELECT COUNT(*) FROM crm_procurements cp WHERE cp.crm_stage = 'torgi' AND cp.award_status = 'submission_open' AND {actionable_submission_sql('cp')}")
    print(f"actionable_submission_sql: {cur.fetchone()['count']}")

    cur.execute("SELECT COUNT(*) FROM crm_procurements WHERE crm_stage = 'torgi' AND award_status = 'submission_open' AND end_date >= CURRENT_DATE")
    print(f"end_date >= CURRENT_DATE: {cur.fetchone()['count']}")

    cur.execute("SELECT COUNT(*) FROM crm_procurements WHERE crm_stage = 'torgi' AND award_status = 'submission_open' AND end_date IS NULL")
    print(f"end_date IS NULL: {cur.fetchone()['count']}")

crm_conn.close()
doc_conn.close()
