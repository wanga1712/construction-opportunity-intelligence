import sys
import json
import os
import time
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

t0 = time.time()
crm_conn = get_crm_db_connection()
doc_conn = get_doc_db_connection()

class _CrmDbWrapper:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, sql):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()

priors = load_okpd_priors_from_db(_CrmDbWrapper(crm_conn))

with crm_conn.cursor() as cur:
    cur.execute("SELECT count(*) FROM crm_procurements")
    crm_total = cur.fetchone()[0]

# Distinct OKPD classification optimization
with crm_conn.cursor() as cur:
    cur.execute("SELECT DISTINCT okpd_code FROM crm_procurements WHERE okpd_code IS NOT NULL AND okpd_code != ''")
    distinct_okpds = [r[0] for r in cur.fetchall()]

target_okpds = [okpd for okpd in distinct_okpds if classify_target_okpd(okpd, priors)[0] == ADMISSION_TARGET]

with crm_conn.cursor() as cur:
    cur.execute("SELECT id FROM crm_procurements WHERE okpd_code = ANY(%s)", (target_okpds,))
    all_target_pids = [r[0] for r in cur.fetchall()]

target_id_count = len(all_target_pids)
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
t1 = time.time()

print("--- AUDIT RESULTS ---", flush=True)
print(f"ELAPSED_SECONDS={t1 - t0:.3f}", flush=True)
print(f"CRM_PROCUREMENTS_TOTAL={crm_total}", flush=True)
print(f"CRM_TARGET_PROCUREMENTS={target_id_count}", flush=True)
print(f"V4_UNKNOWN_DETAILS_TOTAL={v4_total}", flush=True)
print(f"V4_UNKNOWN_DETAILS_TARGET={v4_target}", flush=True)
print(f"V4_UNKNOWN_DETAILS_OUT_OF_TARGET={v4_out}", flush=True)
print(f"TARGET_ID_COUNT={target_id_count}", flush=True)
print(f"TARGET_ID_PAYLOAD_APPROX_BYTES={payload_bytes}", flush=True)

crm_conn.close()
doc_conn.close()
