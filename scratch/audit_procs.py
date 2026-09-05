#!/usr/bin/env python3
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
from src.services.commercial_routing_v3.okpd_priors import classify_target_okpd, ADMISSION_TARGET
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader

old_manifest_path = "/tmp/r3_4f_holdout_manifest.json"
blacklisted_ids = set(range(35176, 35276))
if os.path.exists(old_manifest_path):
    with open(old_manifest_path, "r", encoding="utf-8") as f:
        old_data = json.load(f)
        for r in old_data.get("records", []):
            blacklisted_ids.add(r["detail_id"])

doc_conn = get_doc_db_connection()
crm_conn = get_crm_db_connection()

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT commercial_category_code, okpd_pattern, match_type, prior_weight, active FROM crm_category_okpd_priors WHERE active = TRUE")
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

print("Procurement distribution per category:")
for cat in target_9_categories:
    cands = [c for c in target_candidates if c["category_code"] == cat]
    proc_map = {}
    for c in cands:
        pid = c["procurement_id"]
        proc_map[pid] = proc_map.get(pid, 0) + 1
    print(f"\nCategory '{cat}' (Total candidate rows={len(cands)}, Unique procs={len(proc_map)}):")
    for pid, cnt in sorted(proc_map.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  procurement_id={pid}: {cnt} rows")
