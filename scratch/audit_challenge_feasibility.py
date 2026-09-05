#!/usr/bin/env python3
"""
R3-4F-C-B Challenge Feasibility & Non-Positive Availability Audit.

Searches deterministic candidate windows across all 9 categories under global caps:
MAX_ROWS_PER_PROCUREMENT <= 3
MAX_ROWS_PER_DOCUMENT <= 2
to verify feasibility of:
- >= 12 CLEAR_POSITIVE challenge candidates
- >= 10 non-positive (CLEAR_NEGATIVE / AMBIGUOUS) challenge candidates (with >= 5 CLEAR_NEGATIVE)
"""

import os
import json
import re
import hashlib
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
from src.services.commercial_routing_v3.okpd_priors import (
    classify_target_okpd,
    ADMISSION_TARGET,
)
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader

blacklisted_ids = set(range(35176, 35276))
for old_path in ["/tmp/r3_4f_holdout_manifest.json", "/tmp/r3_4fc_holdout_manifest.json", "/tmp/r3_4fca_holdout_manifest.json"]:
    if os.path.exists(old_path):
        with open(old_path, "r", encoding="utf-8") as f:
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

target_candidates = [c for c in enriched if classify_target_okpd(c.get("procurement_okpd_code"), priors)[0] == ADMISSION_TARGET]

validator = ContextValidator(ai_caller=lambda p: "")

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

pos_found = []
neg_found = []
amb_found = []

proc_counts = {}
doc_counts = {}

def can_add(c):
    pid = c["procurement_id"]
    doc = c["document_name"]
    return proc_counts.get(pid, 0) < 3 and doc_counts.get(doc, 0) < 2

def mark_added(c):
    pid = c["procurement_id"]
    doc = c["document_name"]
    proc_counts[pid] = proc_counts.get(pid, 0) + 1
    doc_counts[doc] = doc_counts.get(doc, 0) + 1

for cat in target_9_categories:
    pool = by_cat[cat]
    for c in pool[:50]:  # Inspect first 50 per category
        if not can_add(c): continue
        payload = validator.build_context_payload(c)
        vis_source = payload["visible_source_text"]
        term = c.get("matched_term", "")
        neg_phrases = c.get("negative_phrases") or []

        has_neg_phrase = any(str(np).lower() in vis_source.lower() for np in neg_phrases if str(np).strip())
        has_location_org = any(w in vis_source.lower() for w in ["ул.", "проспект", "ооо ", "зао ", "администрация", "договор", "подрядчик", "согласован"])
        has_qty = bool(re.search(r"\d+\s*(шт|м|м2|м3|кг|т|п\.м|компл|набор)", vis_source, re.IGNORECASE))
        has_spec = any(w in vis_source.lower() for w in ["спецификац", "ведомост", "вор ", "смета", "марк", "гост", "паспорт", "чертеж", "лист", "арматур", "прокат", "труба", "кабель"])

        if has_neg_phrase or has_location_org:
            neg_found.append(c)
            mark_added(c)
        elif has_qty or has_spec:
            pos_found.append(c)
            mark_added(c)
        else:
            amb_found.append(c)
            mark_added(c)

print("CHALLENGE AUDIT RESULTS:")
print(f"  CLEAR_POSITIVE_FOUND = {len(pos_found)} across {len({c['category_code'] for c in pos_found})} categories")
print(f"  CLEAR_NEGATIVE_FOUND = {len(neg_found)} across {len({c['category_code'] for c in neg_found})} categories")
print(f"  AMBIGUOUS_FOUND = {len(amb_found)} across {len({c['category_code'] for c in amb_found})} categories")
print(f"  TOTAL_NON_POSITIVE_FOUND = {len(neg_found) + len(amb_found)}")
