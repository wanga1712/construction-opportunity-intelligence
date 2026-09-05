#!/usr/bin/env python3
import sys
import os
import psycopg2
import psycopg2.extras

sys.path.insert(0, ".")

from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    get_target_procurement_ids,
)
from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db

class _CrmDbWrapper:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, sql):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()

crm_conn = get_crm_db_connection()
priors = load_okpd_priors_from_db(_CrmDbWrapper(crm_conn))
target_ids = get_target_procurement_ids(crm_conn, priors)
print("Target IDs count:", len(target_ids))

doc_conn = get_doc_db_connection()
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    query = """
        SELECT d.id, d.id as detail_id, d.match_id, d.procurement_id, d.category_code, d.subcategory_code,
               d.matched_term, d.term_type, d.score, d.row_data, d.page_or_sheet, d.row_number,
               d.context_before, d.context_after, d.match_method,
               m.document_name, m.archive_member_path
        FROM document_match_details d
        JOIN document_matches m ON d.match_id = m.id
        WHERE (
            d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING')
            OR d.validation_status IS NULL
        )
        AND d.validated_at IS NULL
        AND d.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
        AND d.procurement_id = ANY(%s)
        ORDER BY d.id ASC LIMIT 50
    """
    cur.execute(query, (target_ids,))
    rows = cur.fetchall()

print("Claimable Target Rows Count:", len(rows))
if rows:
    print("First row:", dict(rows[0]))
