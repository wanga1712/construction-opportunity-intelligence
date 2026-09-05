#!/usr/bin/env python3
"""Audit DB state for terminality fix (R3-4D-A). Read-only."""
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    get_target_procurement_ids,
    PIPELINE_GENERATION,
)
from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db

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
target_pids = get_target_procurement_ids(crm_conn, priors)

# 1. Audit TARGET V4 details status by validated_at
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT
            (validated_at IS NOT NULL) AS has_validated_at,
            validation_status,
            validator_version,
            validation_method,
            COUNT(*) as cnt
        FROM document_match_details
        WHERE pipeline_generation = %s
          AND procurement_id = ANY(%s)
        GROUP BY 1, 2, 3, 4
        ORDER BY 1, 2, 3, 4
    """, (PIPELINE_GENERATION, target_pids))
    counts = cur.fetchall()

unvalidated_eligible = sum(
    r["cnt"] for r in counts
    if not r["has_validated_at"] and (r["validation_status"] in ("UNKNOWN", "RAW", "PENDING") or r["validation_status"] is None)
)

already_attempted_unknown = sum(
    r["cnt"] for r in counts
    if r["has_validated_at"] and r["validation_status"] == "UNKNOWN"
)

# 2. Inspect Forensic 100 rows (35176..35275)
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT id, validation_status, validated_at, validator_version, validation_method
        FROM document_match_details
        WHERE id BETWEEN 35176 AND 35275
        ORDER BY id ASC
    """)
    forensic_rows = cur.fetchall()

f_status_cnt = {}
f_has_val_cnt = 0
for f in forensic_rows:
    st = f["validation_status"]
    f_status_cnt[st] = f_status_cnt.get(st, 0) + 1
    if f["validated_at"] is not None:
        f_has_val_cnt += 1

print("--- TERMINALITY DB AUDIT RESULTS ---", flush=True)
print(f"UNVALIDATED_ELIGIBLE_COUNT={unvalidated_eligible}", flush=True)
print(f"ALREADY_ATTEMPTED_UNKNOWN_COUNT={already_attempted_unknown}", flush=True)
print("GROUPED_COUNTS=", counts, flush=True)
print(f"FORENSIC_100_TOTAL={len(forensic_rows)}", flush=True)
print(f"FORENSIC_100_STATUS_DISTRIBUTION={f_status_cnt}", flush=True)
print(f"FORENSIC_100_HAS_VALIDATED_AT_COUNT={f_has_val_cnt}", flush=True)
if forensic_rows:
    print(f"FORENSIC_SAMPLE_35176={forensic_rows[0]}", flush=True)

crm_conn.close()
doc_conn.close()
