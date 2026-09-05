import sys
import os
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection
from tender_documents_research.document_processor.r4_input_selector import get_r4_input_candidates

doc_conn = get_doc_db_connection()

# 1. Audit real R4 database tables
with doc_conn.cursor() as cur:
    cur.execute("SELECT COUNT(*) FROM structured_extraction_runs")
    runs_cnt = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM structured_entities")
    ent_cnt = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM structured_entity_field_evidence")
    fe_cnt = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM structured_attributes")
    attr_cnt = cur.fetchone()[0]

# 2. Audit current V4 CONFIRMED input population using shared selector
candidates = get_r4_input_candidates(doc_conn)

unique_procurement_ids = set(c["procurement_id"] for c in candidates)
unique_queue_ids = set(c["queue_id"] for c in candidates if c.get("queue_id"))

by_category: dict = {}
by_subcategory: dict = {}

for c in candidates:
    cat = c["category_code"]
    subcat = c.get("subcategory_code") or "NONE"
    by_category[cat] = by_category.get(cat, 0) + 1
    key = f"{cat} -> {subcat}"
    by_subcategory[key] = by_subcategory.get(key, 0) + 1

sample_detail_ids = [c["detail_id"] for c in candidates[:10]]

print("=" * 80)
print("REAL R4 DATABASE TABLES AUDIT")
print("=" * 80)
print("R4_REAL_EXTRACTION_RUNS_CREATED:", runs_cnt)
print("STRUCTURED_ENTITIES_TOTAL:", ent_cnt)
print("STRUCTURED_FIELD_EVIDENCE_TOTAL:", fe_cnt)
print("STRUCTURED_ATTRIBUTES_TOTAL:", attr_cnt)

print("\n" + "=" * 80)
print("CANONICAL R4 INPUT POPULATION (POST-CLOSURE)")
print("=" * 80)
print("V4_CONFIRMED_DETAILS_TOTAL:", len(candidates))
print("UNIQUE_PROCUREMENTS:", len(unique_procurement_ids))
print("UNIQUE_DOCUMENTS:", len(unique_queue_ids))
print("BY_CATEGORY:", by_category)
print("BY_SUBCATEGORY:", by_subcategory)
print("SAMPLE_DETAIL_IDS:", sample_detail_ids)

doc_conn.close()
