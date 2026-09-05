#!/usr/bin/env python3
"""R3-4F Step 2: Full Category Population Audit on S13 DB."""
import os
import json
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
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader
from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db

crm_conn = get_crm_db_connection()
doc_conn = get_doc_db_connection()

class _CrmDbWrapper:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, sql):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()

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

# Inventory eligible pool
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT d.id, d.procurement_id, d.category_code, d.subcategory_code,
               d.matched_term, d.match_method, m.document_name
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

eligible_total = len(eligible_rows)
unique_pids = len(set(r["procurement_id"] for r in eligible_rows))
unique_docs = len(set(r["document_name"] for r in eligible_rows))

# Group by category and subcategory
by_cat = {}
by_sub = {}
by_method = {}

for r in eligible_rows:
    c = r["category_code"]
    s = r["subcategory_code"]
    m = r["match_method"] or "UNKNOWN"
    
    if c not in by_cat:
        by_cat[c] = {"code": c, "name": cat_names.get(c, c), "count": 0, "pids": set(), "docs": set(), "terms": set()}
    by_cat[c]["count"] += 1
    by_cat[c]["pids"].add(r["procurement_id"])
    by_cat[c]["docs"].add(r["document_name"])
    by_cat[c]["terms"].add(r["matched_term"])

    if s not in by_sub:
        by_sub[s] = {"code": s, "name": sub_names.get(s, s), "category": c, "count": 0, "pids": set()}
    by_sub[s]["count"] += 1
    by_sub[s]["pids"].add(r["procurement_id"])

    by_method[m] = by_method.get(m, 0) + 1

cat_summary = {}
for c, info in by_cat.items():
    cat_summary[c] = {
        "code": c,
        "name": info["name"],
        "count": info["count"],
        "percentage": round((info["count"] / eligible_total) * 100, 2),
        "unique_pids": len(info["pids"]),
        "unique_docs": len(info["docs"]),
        "unique_terms": len(info["terms"]),
    }

sub_summary = {}
for s, info in by_sub.items():
    sub_summary[s] = {
        "code": s,
        "name": info["name"],
        "category": info["category"],
        "count": info["count"],
        "unique_pids": len(info["pids"]),
    }

print("--- R3-4F POPULATION AUDIT ---", flush=True)
print(f"ELIGIBLE_TOTAL={eligible_total}", flush=True)
print(f"CATEGORY_COUNT={len(by_cat)}", flush=True)
print(f"SUBCATEGORY_COUNT={len(by_sub)}", flush=True)
print(f"UNIQUE_PROCUREMENTS={unique_pids}", flush=True)
print(f"UNIQUE_DOCUMENTS={unique_docs}", flush=True)
print("\nBY_MATCH_METHOD=", json.dumps(by_method), flush=True)
print("\nBY_CATEGORY=", json.dumps(cat_summary, ensure_ascii=False, indent=2), flush=True)
print("\nBY_SUBCATEGORY=", json.dumps(sub_summary, ensure_ascii=False, indent=2), flush=True)

crm_conn.close()
doc_conn.close()
