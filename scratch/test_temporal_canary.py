#!/usr/bin/env python3
import os
import time
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from src.services.commercial_routing_v3.okpd_priors import (
    load_okpd_priors_from_db,
    classify_target_okpd,
    ADMISSION_TARGET,
)
from src.services.commercial_routing_v3.factual_feeder import FactualFeeder
from src.services.commercial_routing_v3.document_links import resolve_document_links

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
doc_conn = psycopg2.connect(**doc_dsn)

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
feeder = FactualFeeder(crm_db)

# 1. Find a candidate in CRM that is not in document_processing_queue
crm_cur.execute("""
    SELECT p.id, p.source_table, p.source_id, p.contract_number, p.okpd_code, p.okpd_name
    FROM crm_procurements p
    WHERE p.source_table IN ('reestr_contract_44_fz', 'reestr_contract_223_fz')
      AND p.crm_stage NOT IN ('cancelled', 'failed', 'closed', 'rejected', 'archived', 'no_winner', 'suspended', 'razygranye')
      AND p.okpd_code IS NOT NULL
    ORDER BY p.id DESC
    LIMIT 200
""")
candidates = crm_cur.fetchall()

target_cand = None
for c in candidates:
    cls, matched = classify_target_okpd(c["okpd_code"], priors)
    if cls == ADMISSION_TARGET:
        doc_cur.execute("SELECT id FROM document_processing_queue WHERE procurement_id = %s", (c["id"],))
        if not doc_cur.fetchone():
            links_res = resolve_document_links(source_table=c["source_table"], source_id=c["source_id"], contract_number=c["contract_number"])
            if links_res.get("links"):
                target_cand = c
                break

if not target_cand:
    print("NO_FRESH_TARGET_CANDIDATE_FOUND")
    exit(1)

pid = target_cand["id"]
print(f"Selected fresh target candidate: pid={pid}, okpd={target_cand['okpd_code']}")

# Admit via factual_feeder
res = feeder.admit_procurement(target_cand, priors=priors)
print(f"Admission result: {res}")
queue_id = res.get("queue_task_id")

doc_cur.execute("SELECT id, procurement_id, status, created_at FROM document_processing_queue WHERE id = %s", (queue_id,))
initial_row = doc_cur.fetchone()
print(f"Initial Queue Row: status={initial_row['status']}, created_at={initial_row['created_at']}")

crm_conn.close()
doc_conn.close()
