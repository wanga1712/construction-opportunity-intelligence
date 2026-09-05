#!/usr/bin/env python3
import json, psycopg2, psycopg2.extras
from dotenv import load_dotenv
load_dotenv("/opt/CRM_Streamlit/.env")
from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection, get_crm_db_connection, get_target_procurement_ids, PIPELINE_GENERATION
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader
from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db

crm_conn = get_crm_db_connection()
doc_conn = get_doc_db_connection()
class W:
    def __init__(self, c): self.conn = c
    def execute_query(self, s):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur: cur.execute(s); return cur.fetchall()
priors = load_okpd_priors_from_db(W(crm_conn))
target_pids = get_target_procurement_ids(crm_conn, priors)
taxonomy = CrmTaxonomyLoader().load_snapshot()
cat_names = {code: getattr(cat, "category_name", code) for code, cat in taxonomy.categories.items()}
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT d.category_code, COUNT(*) as cnt, COUNT(DISTINCT d.procurement_id) as pids
        FROM document_match_details d
        WHERE (d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR d.validation_status IS NULL)
          AND d.validated_at IS NULL
          AND d.pipeline_generation = %s
          AND d.procurement_id = ANY(%s)
          AND d.id NOT BETWEEN 35176 AND 35275
        GROUP BY d.category_code
        ORDER BY cnt DESC
    """, (PIPELINE_GENERATION, target_pids))
    rows = cur.fetchall()

total = sum(r['cnt'] for r in rows)
for r in rows:
    c = r['category_code']
    pct = (r['cnt'] / total) * 100
    print(f"{c} ({cat_names.get(c, c)}): count={r['cnt']} ({pct:.2f}%), pids={r['pids']}")
