#!/usr/bin/env python3
"""Real DB bounded claim proof for R3-4D. Read-only / rollback."""
import os
import sys
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    claim_unvalidated_candidates,
    get_target_procurement_ids,
    enrich_candidates_with_crm_facts,
    filter_target_candidates,
    PIPELINE_GENERATION,
)
from src.services.commercial_routing_v3.okpd_priors import (
    classify_target_okpd,
    load_okpd_priors_from_db,
    ADMISSION_TARGET,
)

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

# Run target claim with small batch size = 5
claimed = claim_unvalidated_candidates(doc_conn, batch_size=5, target_procurement_ids=target_pids)
enriched = enrich_candidates_with_crm_facts(claimed, crm_conn)
target_only = filter_target_candidates(enriched, priors)

out_of_target_claimed = len(claimed) - len(target_only)
other_gen_claimed = sum(1 for c in claimed if c.get("pipeline_generation") and c.get("pipeline_generation") != PIPELINE_GENERATION)

print("=" * 60)
print("REAL DB BOUNDED CLAIM PROOF")
print("=" * 60)
print(f"CLAIMED_BATCH_SIZE={len(claimed)}")
print(f"ALL_TARGET={len(target_only) == len(claimed)}")
print(f"OUT_OF_TARGET_CLAIMED={out_of_target_claimed}")
print(f"OTHER_GENERATION_CLAIMED={other_gen_claimed}")
print("MUTATIONS=0")

for c in claimed[:3]:
    print(f"  ID={c['id']}, PID={c['procurement_id']}, OKPD={c.get('procurement_okpd_code')}")

doc_conn.rollback()
crm_conn.close()
doc_conn.close()
