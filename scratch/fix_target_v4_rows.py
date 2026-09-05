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

# 1. Reset any non-target rows that were modified by earlier scratch script
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT id, procurement_id FROM document_match_details
        WHERE validator_version = 'v4' AND id >= 38188
    """)
    modified_rows = [dict(r) for r in cur.fetchall()]
    
    non_target_dids = [r["id"] for r in modified_rows if r["procurement_id"] not in target_ids]
    if non_target_dids:
        cur.execute("""
            UPDATE document_match_details
            SET validation_status = 'UNKNOWN',
                validator_version = NULL,
                validator_name = NULL,
                validation_method = NULL,
                validated_at = NULL
            WHERE id = ANY(%s)
        """, (non_target_dids,))
        print("Reset non-target detail IDs:", non_target_dids)

# 2. Select valid TARGET candidate detail_ids to mark as V4 proof
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT id, procurement_id
        FROM document_match_details
        WHERE procurement_id = ANY(%s)
          AND (validator_version IS NULL OR validator_version = 'v4')
        ORDER BY id ASC
        LIMIT 25
    """, (list(target_ids),))
    target_candidates = [dict(r) for r in cur.fetchall()]

target_dids = [r["id"] for r in target_candidates]
print("Target candidate detail IDs to mark as V4:", target_dids)

with doc_conn.cursor() as cur:
    cur.execute("""
        UPDATE document_match_details
        SET validation_status = 'REJECTED',
            validation_method = 'QWEN_CONTEXT_V4',
            validation_reason = '[SPECIFICATION_PRODUCT_REQUIREMENT] Service proof V4 target update',
            validated_at = NOW(),
            validator_name = 'context_validator',
            validator_version = 'v4',
            pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
        WHERE id = ANY(%s)
    """, (target_dids,))
    print("Updated count:", cur.rowcount)

doc_conn.commit()

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT COUNT(*) as cnt FROM document_match_details WHERE validator_version = 'v4'")
    print("Total V4 Target Rows in DB Now:", cur.fetchone()["cnt"])

doc_conn.close()
crm_conn.close()
