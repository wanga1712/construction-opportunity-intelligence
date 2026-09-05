#!/usr/bin/env python3
"""
Audits candidate pool on S13 for R3-4F-C 9-Category Holdout.
"""
import os
import json
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    enrich_candidates_with_crm_facts,
)
from src.services.commercial_routing_v3.okpd_priors import (
    classify_target_okpd,
    ADMISSION_TARGET,
)
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader

# 1. Blacklist IDs
old_manifest_path = "/tmp/r3_4f_holdout_manifest.json"
blacklisted_ids = set(range(35176, 35276))  # Forensic 100

if os.path.exists(old_manifest_path):
    with open(old_manifest_path, "r", encoding="utf-8") as f:
        old_data = json.load(f)
        for r in old_data.get("records", []):
            blacklisted_ids.add(r["detail_id"])

print(f"Total Blacklisted IDs: {len(blacklisted_ids)}")

doc_conn = get_doc_db_connection()
crm_conn = get_crm_db_connection()

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT commercial_category_code, okpd_pattern, match_type, prior_weight, active
        FROM crm_category_okpd_priors
        WHERE active = TRUE
    """)
    priors = [dict(r) for r in cur.fetchall()]

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

print(f"Total raw candidates fetched from Doc DB: {len(all_raw)}")

# Exclude blacklisted candidates first
raw_eligible = [c for c in all_raw if c["detail_id"] not in blacklisted_ids]
print(f"Candidates after blacklisting: {len(raw_eligible)}")

# Enrich candidates with CRM facts (procurement title, OKPD, category names, etc.)
enriched = enrich_candidates_with_crm_facts(raw_eligible, crm_conn, taxonomy)
crm_conn.close()

# Filter canonical TARGET procurements
target_candidates = []
for c in enriched:
    okpd = c.get("procurement_okpd_code")
    target_class, _ = classify_target_okpd(okpd, priors)
    if target_class == ADMISSION_TARGET:
        target_candidates.append(c)

print(f"Total fresh TARGET candidates: {len(target_candidates)}")

cat_counts = {}
cat_procs = {}
cat_docs = {}
cat_subs = {}
cat_terms = {}

for c in target_candidates:
    cat = c["category_code"]
    pid = c["procurement_id"]
    doc = c["document_name"]
    sub = c["subcategory_code"]
    term = c.get("matched_term", "")

    cat_counts[cat] = cat_counts.get(cat, 0) + 1
    cat_procs.setdefault(cat, set()).add(pid)
    cat_docs.setdefault(cat, set()).add(doc)
    cat_subs.setdefault(cat, set()).add(sub)
    cat_terms.setdefault(cat, set()).add(term)

target_9_categories = [
    "lighting",
    "waterproofing",
    "flooring",
    "drainage_water_management",
    "waterproofing_concrete_repair",
    "composite_structures",
    "structural_reinforcement",
    "cable_support_systems",
    "bridge_road_infrastructure",
]

print("\nEligible Candidate Population by Category:")
print(f"{'Category Code':<32} {'Rows':<8} {'Unique Procs':<14} {'Unique Docs':<14} {'Subcats':<8} {'Terms':<8}")
print("-" * 90)

all_9_valid = True
for cat in target_9_categories:
    rows = cat_counts.get(cat, 0)
    procs = len(cat_procs.get(cat, set()))
    docs = len(cat_docs.get(cat, set()))
    subs = len(cat_subs.get(cat, set()))
    terms = len(cat_terms.get(cat, set()))
    status = "OK" if rows >= 3 else "FAIL (<3 rows)"
    if rows < 3:
        all_9_valid = False
    print(f"{cat:<32} {rows:<8} {procs:<14} {docs:<14} {subs:<8} {terms:<8} [{status}]")

print("-" * 90)
print(f"CURRENT_ELIGIBLE_CATEGORY_COUNT = {sum(1 for c in target_9_categories if cat_counts.get(c, 0) >= 3)}")
print(f"ALL_9_CATEGORIES_TESTED = {'YES' if all_9_valid else 'NO'}")
