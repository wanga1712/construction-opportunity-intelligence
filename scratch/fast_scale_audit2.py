import sys
import json
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    PIPELINE_GENERATION,
)
from src.services.commercial_routing_v3.okpd_priors import (
    classify_target_okpd,
    load_okpd_priors_from_db,
    ADMISSION_TARGET,
)

doc_conn = get_doc_db_connection()
crm_conn = get_crm_db_connection()

class _CrmDbWrapper:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, sql):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()

priors = load_okpd_priors_from_db(_CrmDbWrapper(crm_conn))

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT id, okpd_code FROM crm_procurements")
    rows = cur.fetchall()

crm_total = len(rows)
all_target_pids = [r["id"] for r in rows if classify_target_okpd(r.get("okpd_code"), priors)[0] == ADMISSION_TARGET]
all_target_count = len(all_target_pids)
payload_bytes = len(json.dumps(all_target_pids))

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT procurement_id
        FROM document_match_details
        WHERE (validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR validation_status IS NULL)
          AND pipeline_generation = %s
    """, (PIPELINE_GENERATION,))
    v4_rows = cur.fetchall()

v4_total = len(v4_rows)
all_target_set = set(all_target_pids)
v4_target = sum(1 for r in v4_rows if r["procurement_id"] in all_target_set)
v4_out = v4_total - v4_target

print("--- SCALE AUDIT COMPLETE ---", flush=True)
print(f"CRM_PROCUREMENTS_TOTAL={crm_total}", flush=True)
print(f"CRM_TARGET_PROCUREMENTS={all_target_count}", flush=True)
print(f"V4_UNKNOWN_DETAILS_TOTAL={v4_total}", flush=True)
print(f"V4_UNKNOWN_DETAILS_TARGET={v4_target}", flush=True)
print(f"V4_UNKNOWN_DETAILS_OUT_OF_TARGET={v4_out}", flush=True)
print(f"TARGET_ID_COUNT={all_target_count}", flush=True)
print(f"TARGET_ID_PAYLOAD_APPROX_BYTES={payload_bytes}", flush=True)

crm_conn.close()
doc_conn.close()
