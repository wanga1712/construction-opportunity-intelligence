#!/usr/bin/env python3
"""Build and select R3-4F Holdout Cohorts A, B, C from S13 DB."""
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

# Fetch all eligible candidates
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

print(f"Total eligible rows loaded: {len(eligible_rows)}")

for r in eligible_rows:
    r["category_name"] = cat_names.get(r["category_code"], r["category_code"])
    r["subcategory_name"] = sub_names.get(r["subcategory_code"], r["subcategory_code"])

validator = ContextValidator(ai_caller=lambda p: "")

cat_targets_A = {
    "lighting": 12,
    "waterproofing": 6,
    "flooring": 5,
    "drainage_water_management": 4,
    "waterproofing_concrete_repair": 2,
    "composite_structures": 1,
}

cohort_A = []
selected_ids = set()
procurement_counts = {}

hashed_candidates = []
for r in eligible_rows:
    h_str = f"R3-4F-NATURAL-V1:{r['id']}:{r['procurement_id']}"
    h_val = hashlib.sha256(h_str.encode("utf-8")).hexdigest()
    hashed_candidates.append((h_val, r))
hashed_candidates.sort(key=lambda x: x[0])

cat_selected_A = {c: 0 for c in cat_targets_A}
for h_val, r in hashed_candidates:
    c_code = r["category_code"]
    pid = r["procurement_id"]
    if c_code not in cat_targets_A:
        continue
    if cat_selected_A[c_code] >= cat_targets_A[c_code]:
        continue
    if procurement_counts.get(pid, 0) >= 3:
        continue
    
    r_copy = dict(r)
    r_copy["cohort"] = "NATURAL_STRATIFIED"
    cohort_A.append(r_copy)
    selected_ids.add(r["id"])
    cat_selected_A[c_code] += 1
    procurement_counts[pid] = procurement_counts.get(pid, 0) + 1
    if len(cohort_A) >= 30:
        break

print(f"Cohort A selected: {len(cohort_A)} rows")

cohort_A_formatted = []
for r in cohort_A:
    r_copy = dict(r)
    r_copy["context_block"] = validator.build_context_block(r)
    cohort_A_formatted.append(r_copy)

with open("/tmp/cohort_A_draft.json", "w", encoding="utf-8") as f:
    json.dump(cohort_A_formatted, f, ensure_ascii=False, indent=2, default=default_json)

print("Saved /tmp/cohort_A_draft.json")

crm_conn.close()
doc_conn.close()
