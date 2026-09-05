#!/usr/bin/env python3
"""Scale and population audit for R3-4D. READ-ONLY."""
import json
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
import psycopg2.extras

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

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT id, okpd_code FROM crm_procurements")
    rows = cur.fetchall()

crm_total = len(rows)
target_pids = [r["id"] for r in rows if classify_target_okpd(r.get("okpd_code"), priors)[0] == ADMISSION_TARGET]
target_id_count = len(target_pids)
payload_bytes = len(json.dumps(target_pids))

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT
            count(*) AS total,
            count(*) FILTER (WHERE procurement_id = ANY(%s)) AS target_count,
            count(*) FILTER (WHERE procurement_id != ALL(%s)) AS out_of_target_count
        FROM document_match_details
        WHERE (validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR validation_status IS NULL)
          AND pipeline_generation = %s
    """, (target_pids, target_pids, PIPELINE_GENERATION))
    counts = cur.fetchone()

print(f"CRM_PROCUREMENTS_TOTAL={crm_total}")
print(f"CRM_TARGET_PROCUREMENTS={target_id_count}")
print(f"V4_UNKNOWN_DETAILS_TOTAL={counts['total']}")
print(f"V4_UNKNOWN_DETAILS_TARGET={counts['target_count']}")
print(f"V4_UNKNOWN_DETAILS_OUT_OF_TARGET={counts['out_of_target_count']}")
print(f"TARGET_ID_COUNT={target_id_count}")
print(f"TARGET_ID_PAYLOAD_APPROX_BYTES={payload_bytes}")

crm_conn.close()
doc_conn.close()
