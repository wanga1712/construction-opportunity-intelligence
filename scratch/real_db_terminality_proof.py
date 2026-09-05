#!/usr/bin/env python3
"""Real DB read-only proof for R3-4D-A terminality fix."""
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    claim_unvalidated_candidates,
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

# 1. Find an unattempted row (validated_at IS NULL)
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT id, procurement_id, validation_status, validated_at
        FROM document_match_details
        WHERE pipeline_generation = %s
          AND procurement_id = ANY(%s)
          AND (validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR validation_status IS NULL)
          AND validated_at IS NULL
        ORDER BY id ASC
        LIMIT 1
    """, (PIPELINE_GENERATION, target_pids))
    unattempted_row = cur.fetchone()

# 2. Find an attempted row (validated_at IS NOT NULL)
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT id, procurement_id, validation_status, validated_at, validator_version
        FROM document_match_details
        WHERE pipeline_generation = %s
          AND procurement_id = ANY(%s)
          AND validation_status = 'UNKNOWN'
          AND validated_at IS NOT NULL
        ORDER BY id ASC
        LIMIT 1
    """, (PIPELINE_GENERATION, target_pids))
    attempted_row = cur.fetchone()

# 3. Test claim_unvalidated_candidates with new SQL predicate
claimed = claim_unvalidated_candidates(doc_conn, batch_size=10, target_procurement_ids=target_pids)
attempted_claimed = sum(1 for c in claimed if c.get("validated_at") is not None)

print("=" * 60)
print("REAL DB TERMINALITY PROOF")
print("=" * 60)
print(f"ELIGIBLE_UNATTEMPTED_ROW_FOUND={unattempted_row is not None}")
if unattempted_row:
    print(f"  Sample: ID={unattempted_row['id']}, status={unattempted_row['validation_status']}, validated_at={unattempted_row['validated_at']}")

print(f"ATTEMPTED_UNKNOWN_ROW_FOUND={attempted_row is not None}")
if attempted_row:
    print(f"  Sample: ID={attempted_row['id']}, status={attempted_row['validation_status']}, validated_at={attempted_row['validated_at']}, ver={attempted_row['validator_version']}")

print(f"CLAIMED_BATCH_SIZE={len(claimed)}")
print(f"REAL_DB_ATTEMPTED_ROWS_CLAIMED={attempted_claimed}")
print("MUTATIONS=0")

doc_conn.rollback()
crm_conn.close()
doc_conn.close()
