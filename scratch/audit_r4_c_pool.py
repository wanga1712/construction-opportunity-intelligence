import sys
import os
import json
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection
from tender_documents_research.document_processor.r4_input_selector import get_r4_input_candidates

doc_conn = get_doc_db_connection()
all_candidates = get_r4_input_candidates(doc_conn)

# 1. Blacklist
blacklist_ids = {38319, 38324, 38325, 38373, 38417}
try:
    if os.path.exists("/tmp/r4_b_extractor_smoke_manifest.json"):
        with open("/tmp/r4_b_extractor_smoke_manifest.json", "r", encoding="utf-8") as f:
            manifest = json.load(f)
            for item in manifest:
                blacklist_ids.add(item["detail_id"])
except Exception:
    pass

with doc_conn.cursor() as cur:
    cur.execute("SELECT DISTINCT detail_id FROM structured_extraction_runs WHERE extractor_version = 'v1'")
    for r in cur.fetchall():
        blacklist_ids.add(r[0])

doc_conn.close()

fresh_candidates = [c for c in all_candidates if c["detail_id"] not in blacklist_ids and c["extraction_eligible"]]

print("=" * 80)
print("FRESH POOL AUDIT FOR R4-C EVALUATION")
print("=" * 80)
print("TOTAL_CANONICAL_CANDIDATES:", len(all_candidates))
print("BLACKLISTED_IDS_COUNT:", len(blacklist_ids))
print("BLACKLISTED_IDS:", sorted(list(blacklist_ids)))
print("TOTAL_FRESH_ELIGIBLE:", len(fresh_candidates))

by_cat = {}
by_subcat = {}
procs = set()
docs = set()

for c in fresh_candidates:
    cat = c["category_code"]
    subcat = f"{cat} -> {c.get('subcategory_code')}"
    by_cat[cat] = by_cat.get(cat, 0) + 1
    by_subcat[subcat] = by_subcat.get(subcat, 0) + 1
    procs.add(c["procurement_id"])
    if c.get("queue_id"):
        docs.add(c["queue_id"])

print("UNIQUE_CATEGORIES:", len(by_cat))
print("UNIQUE_PROCUREMENTS:", len(procs))
print("UNIQUE_DOCUMENTS:", len(docs))
print("BY_CATEGORY:", by_cat)
print("BY_SUBCATEGORY:", by_subcat)

# Calculate capacity under caps: MAX_ROWS_PER_PROCUREMENT=3, MAX_ROWS_PER_DOCUMENT=2, MAX_ROWS_PER_CATEGORY=8
cat_counts = {}
proc_counts = {}
doc_counts = {}
selectable = []

for c in fresh_candidates:
    cat = c["category_code"]
    proc = c["procurement_id"]
    doc = c.get("queue_id")
    
    if cat_counts.get(cat, 0) >= 8:
        continue
    if proc_counts.get(proc, 0) >= 3:
        continue
    if doc and doc_counts.get(doc, 0) >= 2:
        continue
        
    cat_counts[cat] = cat_counts.get(cat, 0) + 1
    proc_counts[proc] = proc_counts.get(proc, 0) + 1
    if doc:
        doc_counts[doc] = doc_counts.get(doc, 0) + 1
    selectable.append(c)

print("\nCAPACITY UNDER GLOBAL CAPS:")
print("MAX_SELECTABLE_ROWS:", len(selectable))
print("SELECTABLE_CATEGORIES:", len(set(c["category_code"] for c in selectable)))
print("SELECTABLE_PROCUREMENTS:", len(set(c["procurement_id"] for c in selectable)))
print("SELECTABLE_DOCUMENTS:", len(set(c.get("queue_id") for c in selectable if c.get("queue_id"))))
