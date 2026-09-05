import sys
import os
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection
from tender_documents_research.document_processor.r4_input_selector import get_r4_input_candidates

doc_conn = get_doc_db_connection()
candidates = get_r4_input_candidates(doc_conn)

trusted_total = len(candidates)
source_available_total = sum(1 for c in candidates if c["source_available"])
source_unavailable_total = sum(1 for c in candidates if not c["source_available"])
extraction_eligible_total = sum(1 for c in candidates if c["extraction_eligible"])

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

sample_details = [
    {
        "detail_id": c["detail_id"],
        "category": c["category_code"],
        "subcategory": c.get("subcategory_code"),
        "source_sha256": c["source_text_sha256"],
        "source_length": len(c["source_text_snapshot"]),
    }
    for c in candidates[:10]
]

print("=" * 80)
print("CANONICAL R4 INPUT RE-AUDIT (POST-CLOSURE A-B)")
print("=" * 80)
print("TRUSTED_V4_CONFIRMED_TOTAL:", trusted_total)
print("SOURCE_AVAILABLE_TOTAL:", source_available_total)
print("SOURCE_UNAVAILABLE_TOTAL:", source_unavailable_total)
print("EXTRACTION_ELIGIBLE_TOTAL:", extraction_eligible_total)
print("UNIQUE_PROCUREMENTS:", len(unique_procurement_ids))
print("UNIQUE_DOCUMENTS:", len(unique_queue_ids))
print("BY_CATEGORY:", by_category)
print("BY_SUBCATEGORY:", by_subcategory)
print("SAMPLE_DETAILS:")
for s in sample_details:
    print(" ", s)

doc_conn.close()
