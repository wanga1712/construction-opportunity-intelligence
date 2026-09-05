#!/usr/bin/env python3
"""Step 1: Verify reset state is clean."""
import psycopg2
import json

doc_conn = psycopg2.connect(
    "dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432"
)
crm_conn = psycopg2.connect(
    "dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432"
)

def cnt(conn, tbl):
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {tbl}")
            return cur.fetchone()[0]
    except Exception as e:
        conn.rollback()
        return f"ERR:{e}"

doc_tables = [
    "document_processing_queue",
    "document_files",
    "document_processing_results",
    "document_matches",
    "document_match_details",
]
crm_tables = [
    "crm_v3_pre_research_snapshots",
    "crm_v3_shadow_predictions",
    "crm_v3_raw_source_evidence",
    "crm_v3_product_findings",
    "crm_v3_exhaustive_truth",
    "crm_v3_shadow_evaluations",
    "crm_v3_learning_examples",
]

result = {}
for t in doc_tables:
    result[t] = cnt(doc_conn, t)
for t in crm_tables:
    result[t] = cnt(crm_conn, t)

# Preserve authority: source procurements / doc links
for t in ["crm_procurements", "crm_product_categories"]:
    result[t] = cnt(crm_conn, t)

# Check phrase registry tables
for t in ["crm_product_search_phrases", "crm_product_phrase_registry", "search_phrase_registry", "crm_search_phrases"]:
    result[f"phrase_registry.{t}"] = cnt(crm_conn, t)

doc_conn.close()
crm_conn.close()

all_zero = all(v == 0 for k, v in result.items() if k.startswith("document_") or k.startswith("crm_v3_"))
print(json.dumps({"RESET_ALREADY_CLEAN": "YES" if all_zero else "NO", "counts": result}, indent=2))
