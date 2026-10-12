import os
import dotenv
import psycopg2

vals = dotenv.dotenv_values("/opt/CRM_Streamlit/.env")
crm_pw = vals.get("CRM_DB_PASSWORD", "")

print("1. Testing crm_app user on document_intelligence...")
try:
    c = psycopg2.connect(host="127.0.0.1", port=5432, dbname="document_intelligence", user="crm_app", password=crm_pw)
    print("SUCCESS: crm_app connected to document_intelligence!")
    with c.cursor() as cur:
        cur.execute("SELECT count(*) FROM document_processing_queue WHERE status = 'pending'")
        print("Pending queue count via crm_app:", cur.fetchone()[0])
    c.close()
except Exception as e:
    print("crm_app failed:", e)

print("2. Testing doc_worker with crm password...")
try:
    c = psycopg2.connect(host="127.0.0.1", port=5432, dbname="document_intelligence", user="doc_worker", password=crm_pw)
    print("SUCCESS: doc_worker with crm_pw connected!")
    c.close()
except Exception as e:
    print("doc_worker with crm_pw failed:", e)
