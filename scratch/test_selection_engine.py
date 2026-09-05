#!/usr/bin/env python3
import os
import sys
import json
import glob
import hashlib
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

sys.path.insert(0, ".")

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    hydrate_candidate_context,
)
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

# 1. Blacklist Union
blacklisted_ids = set(range(35176, 35276))  # Forensic 100
sources = {"forensic100": 100}

prior_files = [
    "/tmp/r3_4f_holdout_manifest.json",
    "/tmp/r3_4fc_holdout_manifest.json",
    "/tmp/r3_4fca_holdout_manifest.json",
    "/tmp/r3_4fcc_eval_results.json"
] + glob.glob("/tmp/r3_*_manifest*.json") + glob.glob("/tmp/r3_*_eval*.json")

for p in set(prior_files):
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            items = d if isinstance(d, list) else d.get("records", d.get("rows", d.get("results", [])))
            cnt = 0
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and "detail_id" in item:
                        blacklisted_ids.add(int(item["detail_id"]))
                        cnt += 1
            sources[os.path.basename(p)] = cnt
        except Exception:
            pass

print(f"[STEP 1] Union Blacklist Total: {len(blacklisted_ids)} IDs")
for k, v in sources.items():
    print(f"  - {k}: {v}")

# 2. Fetch fresh candidates
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

print(f"[STEP 2] Fresh TARGET Candidates: {len(target_candidates)}")

by_cat = {}
for c in target_candidates:
    by_cat.setdefault(c["category_code"], []).append(c)

all_9 = [
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

print("\n[STEP 2] Population by 9 Active Categories:")
for cat in all_9:
    items = by_cat.get(cat, [])
    procs = len(set(x["procurement_id"] for x in items))
    docs = len(set(x["document_name"] for x in items))
    print(f"  {cat:32s}: {len(items):4d} rows | {procs:3d} procs | {docs:3d} docs")
