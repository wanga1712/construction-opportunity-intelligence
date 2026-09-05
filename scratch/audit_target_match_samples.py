#!/usr/bin/env python3
import os
import json
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from src.services.commercial_routing_v3.okpd_priors import (
    load_okpd_priors_from_db,
    classify_target_okpd,
    ADMISSION_TARGET,
    ADMISSION_OUT_OF_TARGET,
    ADMISSION_UNKNOWN_OKPD,
)

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

crm_conn = psycopg2.connect(**crm_dsn)
crm_conn.autocommit = True
doc_conn = psycopg2.connect(**doc_dsn)
doc_conn.autocommit = True

crm_cur = crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
doc_cur = doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

class CrmDbWrapper:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, sql, params=None):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()

crm_db = CrmDbWrapper(crm_conn)
priors = load_okpd_priors_from_db(crm_db)

print("=== 1. AUDIT PROCUREMENT 997 ===")
crm_cur.execute("SELECT id, contract_number, okpd_code, okpd_name FROM crm_procurements WHERE id = 997")
p997 = crm_cur.fetchone()
if p997:
    cls_997, matched_997 = classify_target_okpd(p997["okpd_code"], priors)
    print(f"PROCUREMENT_997: id={p997['id']}, okpd={p997['okpd_code']}, okpd_name={p997['okpd_name']}")
    print(f"PROCUREMENT_997_TARGET_CLASSIFICATION={cls_997}")
    if cls_997 == ADMISSION_TARGET:
        doc_cur.execute("""
            SELECT matched_term, category_code, subcategory_code, COUNT(*) as cnt,
                   (ARRAY_AGG(row_data))[1] as sample_data
            FROM document_match_details
            WHERE procurement_id = 997
            GROUP BY matched_term, category_code, subcategory_code
            ORDER BY cnt DESC
            LIMIT 30
        """)
        print("TOP 30 MATCHES FOR 997:")
        for r in doc_cur.fetchall():
            print(dict(r))
else:
    print("PROCUREMENT 997 NOT FOUND IN CRM")

print("\n=== 2. SELECT 10 NATURALLY COMPLETED TARGET PROCUREMENTS ===")
doc_cur.execute("""
    SELECT DISTINCT procurement_id
    FROM document_processing_queue
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
      AND status = 'COMPLETED'
""")
completed_pids = [r["procurement_id"] for r in doc_cur.fetchall()]

target_completed_pids = []
if completed_pids:
    placeholders = ",".join(["%s"] * len(completed_pids))
    crm_cur.execute(f"SELECT id, okpd_code, okpd_name, auction_name FROM crm_procurements WHERE id IN ({placeholders})", tuple(completed_pids))
    p_map = {r["id"]: r for r in crm_cur.fetchall()}
    for pid in completed_pids:
        proc = p_map.get(pid)
        if proc:
            cls, _ = classify_target_okpd(proc["okpd_code"], priors)
            if cls == ADMISSION_TARGET:
                target_completed_pids.append(proc)

print(f"FOUND {len(target_completed_pids)} COMPLETED TARGET PROCUREMENTS.")

# Take up to 10
sample_targets = target_completed_pids[:10]

target_match_sample = []
for p in sample_targets:
    pid = p["id"]
    doc_cur.execute("""
        SELECT matched_term, category_code, subcategory_code, COUNT(*) as cnt,
               (ARRAY_AGG(row_data))[1] as sample_data
        FROM document_match_details
        WHERE procurement_id = %s
        GROUP BY matched_term, category_code, subcategory_code
        ORDER BY cnt DESC
        LIMIT 10
    """, (pid,))
    matches = doc_cur.fetchall()
    for m in matches:
        raw_text = ""
        sdata = m.get("sample_data")
        if isinstance(sdata, dict):
            raw_text = sdata.get("raw_text") or str(sdata)
        elif isinstance(sdata, str):
            raw_text = sdata
        target_match_sample.append({
            "PROCUREMENT_ID": pid,
            "OKPD_CODE": p["okpd_code"],
            "MATCHED_TERM": m["matched_term"],
            "CATEGORY": m["category_code"],
            "SUBCATEGORY": m["subcategory_code"],
            "COUNT": m["cnt"],
            "CONTEXT_SAMPLE": raw_text[:120] if raw_text else "table row hit"
        })

print(f"\nTARGET_MATCH_SAMPLE ({len(target_match_sample)} entries):")
for item in target_match_sample[:25]:
    print(json.dumps(item, ensure_ascii=False, indent=2))

crm_conn.close()
doc_conn.close()
