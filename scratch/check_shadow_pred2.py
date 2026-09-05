#!/usr/bin/env python3
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

crm_dsn = {
    "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("CRM_DB_PORT", "5432")),
    "dbname": os.getenv("CRM_DB_NAME", "crm"),
    "user": os.getenv("CRM_DB_USER", "crm_app"),
    "password": os.getenv("CRM_DB_PASSWORD", ""),
}

crm_conn = psycopg2.connect(**crm_dsn)
crm_cur = crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

crm_cur.execute("""
    SELECT id, procurement_id, run_kind, run_status, created_at
    FROM crm_v3_model_inference_runs
    WHERE procurement_id = 165094
""")
print("INFERENCE_RUNS:", [dict(r) for r in crm_cur.fetchall()])

crm_cur.execute("""
    SELECT id, snapshot_id, procurement_id, has_target_decision, has_target_probability, created_at
    FROM crm_v3_shadow_predictions
    WHERE procurement_id = 165094
""")
print("SHADOW_PREDICTIONS:", [dict(r) for r in crm_cur.fetchall()])

crm_conn.close()
