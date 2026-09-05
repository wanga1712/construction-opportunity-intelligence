#!/usr/bin/env python3
import os
import json
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db, classify_target_okpd

crm_dsn = {
    "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("CRM_DB_PORT", "5432")),
    "dbname": os.getenv("CRM_DB_NAME", "crm"),
    "user": os.getenv("CRM_DB_USER", "crm_app"),
    "password": os.getenv("CRM_DB_PASSWORD", ""),
}

crm_conn = psycopg2.connect(**crm_dsn)
crm_cur = crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

class CrmDbWrapper:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, sql, params=None):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()

crm_db = CrmDbWrapper(crm_conn)
priors = load_okpd_priors_from_db(crm_db)

crm_cur.execute("SELECT id, contract_number, okpd_code, okpd_name FROM crm_procurements WHERE id = 997")
p997 = crm_cur.fetchone()
cls_997, matched_997 = classify_target_okpd(p997["okpd_code"], priors)
print(f"PROCUREMENT_997: id={p997['id']}, okpd={p997['okpd_code']}, okpd_name={p997['okpd_name']}")
print(f"PROCUREMENT_997_TARGET_CLASSIFICATION={cls_997}")

crm_conn.close()
