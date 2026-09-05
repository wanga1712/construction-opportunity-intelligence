import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from src.services.commercial_routing_v3.okpd_priors import (
    classify_target_okpd,
    load_okpd_priors_from_db,
    ADMISSION_TARGET,
)
from src.services.crm_db_runtime import require_crm_db_connect_kwargs

# Connect to doc DB
doc_conn = psycopg2.connect(
    dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
    user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
    password=os.getenv("S13_DOCUMENT_DB_PASSWORD"),
    host=os.getenv("S13_DOCUMENT_DB_HOST", "localhost"),
    port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
)

# Connect to CRM DB
crm_conn = psycopg2.connect(**require_crm_db_connect_kwargs())

# Load priors
class CrmDbWrapper:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, sql):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()

crm_wrapper = CrmDbWrapper(crm_conn)
priors = load_okpd_priors_from_db(crm_wrapper)
print(f"LOADED_PRIORS_COUNT: {len(priors)}")

# Query all unvalidated details grouped by pipeline_generation and procurement_id
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT pipeline_generation, validation_status, count(*) as cnt, array_agg(DISTINCT procurement_id) as pids
        FROM document_match_details
        WHERE (validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR validation_status IS NULL)
        GROUP BY pipeline_generation, validation_status
    """)
    rows = cur.fetchall()
    print("\nUNVALIDATED DETAILS BREAKDOWN:")
    all_v4_pids = set()
    other_gen_cnt = 0
    all_v4_cnt = 0
    for r in rows:
        print(f"Gen={r['pipeline_generation']}, Status={r['validation_status']}, Count={r['cnt']}, UniquePIDs={len(r['pids'])}")
        if r['pipeline_generation'] == 'S13_V4_EXHAUSTIVE_CONTEXT':
            all_v4_cnt += r['cnt']
            all_v4_pids.update(r['pids'])
        else:
            other_gen_cnt += r['cnt']

# Check OKPD for all V4 procurements in CRM DB
with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT id, auction_name, okpd_code, okpd_name
        FROM crm_procurements
        WHERE id = ANY(%s)
    """, (list(all_v4_pids),))
    proc_rows = {r['id']: r for r in cur.fetchall()}

target_pids = set()
out_of_target_pids = set()
for pid in all_v4_pids:
    p = proc_rows.get(pid)
    okpd = p.get('okpd_code') if p else None
    status, _ = classify_target_okpd(okpd, priors)
    if status == ADMISSION_TARGET:
        target_pids.add(pid)
    else:
        out_of_target_pids.add(pid)

print(f"\nV4 UNIQUE PROCURMENTS: Total={len(all_v4_pids)}, TARGET={len(target_pids)}, OUT_OF_TARGET={len(out_of_target_pids)}")

# Count details for target vs out-of-target V4
with doc_conn.cursor() as cur:
    cur.execute("""
        SELECT count(*)
        FROM document_match_details
        WHERE (validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR validation_status IS NULL)
          AND pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
          AND procurement_id = ANY(%s)
    """, (list(target_pids),))
    target_v4_cnt = cur.fetchone()[0]

    cur.execute("""
        SELECT count(*)
        FROM document_match_details
        WHERE (validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR validation_status IS NULL)
          AND pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
          AND procurement_id = ANY(%s)
    """, (list(out_of_target_pids),))
    out_of_target_v4_cnt = cur.fetchone()[0]

print(f"\nBACKLOG NUMBERS:")
print(f"UNKNOWN_DETAILS_ALL_V4 = {all_v4_cnt}")
print(f"UNKNOWN_DETAILS_TARGET_V4 = {target_v4_cnt}")
print(f"UNKNOWN_DETAILS_OUT_OF_TARGET_V4 = {out_of_target_v4_cnt}")
print(f"UNKNOWN_DETAILS_OTHER_GENERATIONS = {other_gen_cnt}")

doc_conn.close()
crm_conn.close()
