#!/usr/bin/env python3
import os
import json
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

doc_dsn = {
    "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
    "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
    "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
    "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
}

# S7 DB
s7_dsn = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "tender_monitor"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}

crm_conn = psycopg2.connect(**crm_dsn)
doc_conn = psycopg2.connect(**doc_dsn)
s7_conn = psycopg2.connect(**s7_dsn)

crm_cur = crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
doc_cur = doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
s7_cur = s7_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print("=== 1. CRM PROC 163649 ===")
crm_cur.execute("""
    SELECT id, source_table, source_id, contract_number, auction_name,
           okpd_code, okpd_name, crm_stage, award_status, crm_created_at, crm_updated_at
    FROM crm_procurements
    WHERE id = 163649
""")
crm_row = crm_cur.fetchone()
print(json.dumps(dict(crm_row), ensure_ascii=False, indent=2, default=str))

source_table = crm_row["source_table"]
source_id = crm_row["source_id"]

print(f"\n=== 2. S7 SOURCE ROW ({source_table} id={source_id}) ===")
s7_cur.execute(f"""
    SELECT *
    FROM {source_table}
    WHERE id = %s
""", (source_id,))
s7_row = s7_cur.fetchone()

# Query S7 OKPD table for okpd_id 5605
s7_okpd_id = s7_row.get("okpd_id")
print(f"S7 okpd_id = {s7_okpd_id}")

s7_cur.execute("""
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name LIKE '%okpd%'
""")
okpd_tables = [r["table_name"] for r in s7_cur.fetchall()]
print(f"OKPD TABLES IN S7: {okpd_tables}")

s7_okpd_code = None
s7_okpd_name = None
for ot in okpd_tables:
    try:
        s7_cur.execute(f"SELECT * FROM {ot} WHERE id = %s", (s7_okpd_id,))
        orow = s7_cur.fetchone()
        if orow:
            print(f"Found in S7 {ot}: {dict(orow)}")
            s7_okpd_code = orow.get("code") or orow.get("okpd_code") or orow.get("okpd2_code")
            s7_okpd_name = orow.get("name") or orow.get("okpd_name") or orow.get("okpd2_name")
    except Exception as e:
        print(f"Error querying {ot}: {e}")

s7_clean = {
    "table": source_table,
    "id": s7_row.get("id"),
    "contract_number": s7_row.get("contract_number"),
    "okpd_id": s7_okpd_id,
    "okpd_code": s7_okpd_code,
    "okpd_name": s7_okpd_name,
    "created_at": s7_row.get("created_at"),
    "updated_at": s7_row.get("updated_at"),
}
print("\nS7 STRUCTURED RESULT:")
print(json.dumps(s7_clean, ensure_ascii=False, indent=2, default=str))

print("\n=== 3. ALL S7 OKPD ASSOCIATIONS ===")
all_okpds = [
    {
        "CODE": s7_okpd_code,
        "NAME": s7_okpd_name,
        "SOURCE": f"{source_table} -> okpd (id={s7_okpd_id})",
        "SOURCE_ROW_ID": source_id,
        "ROLE": "MAIN_CONTRACT_ROW_RESOLVED_OKPD"
    }
]
print(json.dumps(all_okpds, ensure_ascii=False, indent=2, default=str))

print("\n=== 4. QUEUE HISTORY IN DOCUMENT DB ===")
doc_cur.execute("""
    SELECT id as queue_id, created_at, status, started_at, completed_at,
           last_error, category_context, assessment_id, pipeline_generation
    FROM document_processing_queue
    WHERE procurement_id = 163649
    ORDER BY id ASC
""")
q_history = doc_cur.fetchall()
print(f"QUEUE ROWS FOUND IN DB: {len(q_history)}")
for r in q_history:
    print(dict(r))

# Check backup entry in data/
backup_path = "/opt/CRM_Streamlit/data/backup_false_failed_out_of_target_20260831.json"
if os.path.exists(backup_path):
    with open(backup_path, "r", encoding="utf-8") as f:
        backups = json.load(f)
    b_163649 = [b for b in backups if b.get("procurement_id") == 163649]
    print(f"\nBACKUP ENTRY COUNT FOR 163649: {len(b_163649)}")
    if b_163649:
        print(json.dumps(b_163649, ensure_ascii=False, indent=2, default=str))

crm_conn.close()
doc_conn.close()
s7_conn.close()
