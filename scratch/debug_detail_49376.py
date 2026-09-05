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
    cur.execute("SELECT d.id as detail_id, d.procurement_id, d.category_code, d.subcategory_code, d.matched_term, d.term_type, d.score, d.row_data, d.page_or_sheet, d.row_number, d.context_before, d.context_after, d.match_method, m.document_name, m.archive_member_path FROM document_match_details d JOIN document_matches m ON d.match_id = m.id WHERE d.id = 49376")
    raw = cur.fetchall()

doc_conn.close()
enriched = enrich_candidates_with_crm_facts(raw, crm_conn, taxonomy)
crm_conn.close()

c = enriched[0]
validator = ContextValidator()
payload = validator.build_context_payload(c)

print("DETAIL ID 49376:")
print("  matched_term:", c.get("matched_term"))
print("  matched_line:", c.get("matched_line"))
print("  visible_source_text:\n", repr(payload["visible_source_text"]))
