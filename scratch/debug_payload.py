#!/usr/bin/env python3
import os
import json
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    hydrate_candidate_context,
)
from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    enrich_candidates_with_crm_facts,
)
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader

doc_conn = get_doc_db_connection()
crm_conn = get_crm_db_connection()
taxonomy = CrmTaxonomyLoader().load_snapshot()

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT d.id as detail_id, d.procurement_id, d.category_code, d.subcategory_code,
               d.matched_term, d.term_type, d.score, d.row_data, d.page_or_sheet, d.row_number,
               d.context_before, d.context_after, d.match_method,
               m.document_name, m.archive_member_path
        FROM document_match_details d
        JOIN document_matches m ON d.match_id = m.id
        WHERE d.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
          AND d.validated_at IS NULL
          AND (d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR d.validation_status IS NULL)
    """)
    all_raw = cur.fetchall()

doc_conn.close()
enriched = enrich_candidates_with_crm_facts(all_raw, crm_conn, taxonomy)
crm_conn.close()

validator = ContextValidator()
fail_count = 0
for c in enriched:
    try:
        payload = validator.build_context_payload(c)
    except Exception as ex:
        fail_count += 1
        print(f"FAIL #{fail_count} on detail_id={c['detail_id']}: {ex}")
        c_hyd = hydrate_candidate_context(c)
        m_line = str(c_hyd.get("matched_line"))
        b_ctx = str(c_hyd.get("context_before"))
        a_ctx = str(c_hyd.get("context_after"))
        print(f"  matched_line len={len(m_line)}")
        print(f"  context_before len={len(b_ctx)} sample={b_ctx[:100]}")
        print(f"  context_after len={len(a_ctx)} sample={a_ctx[:100]}")
        if fail_count >= 5:
            break
