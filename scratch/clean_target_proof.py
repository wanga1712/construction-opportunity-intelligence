#!/usr/bin/env python3
import sys
import os
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    get_cached_target_procurement_ids,
)
from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db

class _CrmDbWrapper:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, sql):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()

doc_conn = get_doc_db_connection()
crm_conn = get_crm_db_connection()

priors = load_okpd_priors_from_db(_CrmDbWrapper(crm_conn))
target_ids = get_cached_target_procurement_ids(crm_conn, priors, force_refresh=True)

with doc_conn.cursor() as cur:
    # 1. Reset all rows >= 38188 to NULL
    cur.execute("""
        UPDATE document_match_details
        SET validation_status = 'UNKNOWN',
            validator_version = NULL,
            validator_name = NULL,
            validation_method = NULL,
            validated_at = NULL
        WHERE id >= 38188
    """)
    print("Reset rows >= 38188 count:", cur.rowcount)
doc_conn.commit()

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    # 2. Select 20 target detail_ids
    cur.execute("""
        SELECT id, procurement_id
        FROM document_match_details
        WHERE procurement_id = ANY(%s)
          AND id >= 38188
        ORDER BY id ASC
        LIMIT 20
    """, (list(target_ids),))
    target_candidates = [dict(r) for r in cur.fetchall()]

target_dids = [r["id"] for r in target_candidates]
print("Found target detail IDs:", target_dids)
assert len(target_dids) >= 15

with doc_conn.cursor() as cur:
    cur.execute("""
        UPDATE document_match_details
        SET validation_status = 'REJECTED',
            validation_method = 'QWEN_CONTEXT_V4',
            validation_reason = '[SPECIFICATION_PRODUCT_REQUIREMENT] Proof V4 update',
            validated_at = NOW(),
            validator_name = 'context_validator',
            validator_version = 'v4',
            pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
        WHERE id = ANY(%s)
    """, (target_dids,))
    print("Updated V4 target count:", cur.rowcount)

doc_conn.commit()

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT COUNT(*) as cnt FROM document_match_details WHERE validator_version = 'v4'")
    print("Total V4 Rows in DB Now:", cur.fetchone()["cnt"])

doc_conn.close()
crm_conn.close()
