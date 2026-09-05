#!/usr/bin/env python3
"""
R3-4F-C-B Exact Feasibility Solver & Candidate Pool Audit.

Computes exact hard capacity for each category under ONLY:
- MAX_ROWS_PER_PROCUREMENT = 3
- MAX_ROWS_PER_DOCUMENT = 2
"""

import os
import json
import hashlib
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

# 1. Build complete blacklist
blacklisted_ids = set(range(35176, 35276))  # Forensic 100

for old_path in ["/tmp/r3_4f_holdout_manifest.json", "/tmp/r3_4fc_holdout_manifest.json"]:
    if os.path.exists(old_path):
        with open(old_path, "r", encoding="utf-8") as f:
            old_data = json.load(f)
            for r in old_data.get("records", []):
                blacklisted_ids.add(r["detail_id"])

print(f"Total Blacklisted IDs count: {len(blacklisted_ids)}")

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

raw_eligible = [c for c in all_raw if c["detail_id"] not in blacklisted_ids]
enriched = enrich_candidates_with_crm_facts(raw_eligible, crm_conn, taxonomy)
crm_conn.close()

target_candidates = []
for c in enriched:
    okpd = c.get("procurement_okpd_code")
    target_class, _ = classify_target_okpd(okpd, priors)
    if target_class == ADMISSION_TARGET:
        target_candidates.append(c)

print(f"Total fresh TARGET candidates: {len(target_candidates)}")

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

by_cat = {cat: [] for cat in target_9_categories}
for c in target_candidates:
    cat = c["category_code"]
    if cat in by_cat:
        by_cat[cat].append(c)

print("\n" + "=" * 80)
print("EXACT HARD CAPACITY SOLVER")
print("=" * 80)

def compute_hard_capacity(pool: list) -> int:
    """Computes exact maximum selectable rows for a category under ONLY:
    MAX_ROWS_PER_PROCUREMENT <= 3
    MAX_ROWS_PER_DOCUMENT <= 2
    """
    proc_cnt = {}
    doc_cnt = {}
    selected = []
    for c in pool:
        pid = c["procurement_id"]
        doc = c["document_name"]
        if proc_cnt.get(pid, 0) < 3 and doc_cnt.get(doc, 0) < 2:
            proc_cnt[pid] = proc_cnt.get(pid, 0) + 1
            doc_cnt[doc] = doc_cnt.get(doc, 0) + 1
            selected.append(c)
    return len(selected)

for cat in target_9_categories:
    pool = by_cat[cat]
    procs = {c["procurement_id"] for c in pool}
    docs = {c["document_name"] for c in pool}
    hard_cap = compute_hard_capacity(pool)
    print(f"Category '{cat}':")
    print(f"  eligible_rows = {len(pool)}")
    print(f"  unique_procurements = {len(procs)}")
    print(f"  unique_documents = {len(docs)}")
    print(f"  HARD_CAPACITY = {hard_cap}")

# Detailed Audit for Bridge, Structural Reinforcement, Cable Support
for cat in ["bridge_road_infrastructure", "structural_reinforcement", "cable_support_systems"]:
    pool = by_cat[cat]
    print(f"\nDETAILED CANDIDATE AUDIT: '{cat}' ({len(pool)} candidates)")
    for idx, c in enumerate(pool, 1):
        print(f"  [{idx}] detail_id={c['detail_id']}, proc_id={c['procurement_id']}, doc={c['document_name']}, sub={c['subcategory_code']}, term={c['matched_term']}")
