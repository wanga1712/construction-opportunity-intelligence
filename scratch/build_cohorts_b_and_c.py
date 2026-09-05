#!/usr/bin/env python3
"""Build Cohorts B & C, assign GOLD labels, and generate frozen manifest."""
import os
import json
import hashlib
from decimal import Decimal
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
from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    hydrate_candidate_context,
)
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader
from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db

def default_json(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

crm_conn = get_crm_db_connection()
doc_conn = get_doc_db_connection()

class _CrmDbWrapper:
    def __init__(self, conn): self.conn = conn
    def execute_query(self, s):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur: cur.execute(s); return cur.fetchall()

priors = load_okpd_priors_from_db(_CrmDbWrapper(crm_conn))
target_pids = get_target_procurement_ids(crm_conn, priors)

taxonomy = CrmTaxonomyLoader().load_snapshot()
cat_names = {}
sub_names = {}
for code, cat in taxonomy.categories.items():
    c_name = getattr(cat, "category_name", None) or getattr(cat, "name", None) or (cat.get("category_name") if isinstance(cat, dict) else str(code))
    cat_names[code] = c_name
    subs = getattr(cat, "subcategories", {}) if not isinstance(cat, dict) else cat.get("subcategories", {})
    if isinstance(subs, dict):
        for sub_code, sub in subs.items():
            s_name = getattr(sub, "subcategory_name", None) or getattr(sub, "name", None) or (sub.get("subcategory_name") if isinstance(sub, dict) else str(sub_code))
            sub_names[sub_code] = s_name

with open("/tmp/cohort_A_draft.json", "r", encoding="utf-8") as f:
    cohort_A = json.load(f)

selected_ids = {r["id"] for r in cohort_A}
procurement_counts = {}
for r in cohort_A:
    pid = r["procurement_id"]
    procurement_counts[pid] = procurement_counts.get(pid, 0) + 1

# Load remaining eligible candidates
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT d.id, d.id as detail_id, d.match_id, d.procurement_id, d.category_code, d.subcategory_code,
               d.matched_term, d.term_type, d.score, d.row_data, d.page_or_sheet, d.row_number,
               d.context_before, d.context_after, d.match_method,
               m.document_name, m.archive_member_path
        FROM document_match_details d
        JOIN document_matches m ON d.match_id = m.id
        WHERE (d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR d.validation_status IS NULL)
          AND d.validated_at IS NULL
          AND d.pipeline_generation = %s
          AND d.procurement_id = ANY(%s)
          AND d.id NOT BETWEEN 35176 AND 35275
        ORDER BY d.id ASC
    """, (PIPELINE_GENERATION, target_pids))
    eligible_rows = cur.fetchall()

validator = ContextValidator(ai_caller=lambda p: "")

remaining = []
for r in eligible_rows:
    if r["id"] not in selected_ids:
        r["category_name"] = cat_names.get(r["category_code"], r["category_code"])
        r["subcategory_name"] = sub_names.get(r["subcategory_code"], r["subcategory_code"])
        r["context_block"] = validator.build_context_block(r)
        remaining.append(r)

print(f"Remaining pool for Cohorts B & C: {len(remaining)} candidates")

# Save remaining candidates grouped by category for inspect/selection
by_cat = {}
for r in remaining:
    c = r["category_code"]
    by_cat.setdefault(c, []).append(r)

summary = {c: len(rows) for c, rows in by_cat.items()}
print("Remaining candidates per category:", summary)

crm_conn.close()
doc_conn.close()
