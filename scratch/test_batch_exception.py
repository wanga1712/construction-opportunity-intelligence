#!/usr/bin/env python3
import sys
import os
import traceback
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")
sys.path.insert(0, ".")

from tender_documents_research.document_processor.context_validator import ContextValidator
from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    process_batch,
    get_cached_target_procurement_ids,
)
from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader

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
taxonomy = CrmTaxonomyLoader().load_snapshot()
target_ids = get_cached_target_procurement_ids(crm_conn, priors, force_refresh=True)

validator = ContextValidator()

try:
    print("Calling process_batch...")
    count = process_batch(
        doc_conn,
        crm_conn,
        validator,
        priors,
        taxonomy,
        batch_size=20,
        target_procurement_ids=target_ids,
        use_target_cache=True,
    )
    print("Batch processed count:", count)
except Exception as e:
    print("EXCEPTION IN PROCESS_BATCH:")
    traceback.print_exc()

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT COUNT(*) as cnt FROM document_match_details WHERE validator_version = 'v4'")
    print("V4 count inside same conn:", cur.fetchone()["cnt"])

doc_conn.close()
crm_conn.close()

# Now open NEW connection to verify DB persistence
doc_conn2 = get_doc_db_connection()
with doc_conn2.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT COUNT(*) as cnt FROM document_match_details WHERE validator_version = 'v4'")
    print("V4 count in NEW conn:", cur.fetchone()["cnt"])
doc_conn2.close()
