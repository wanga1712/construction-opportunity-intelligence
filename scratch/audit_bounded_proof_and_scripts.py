import sys
import os
import glob
import re
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

doc_conn = get_doc_db_connection()

# 1. Search for original 6 bounded-proof detail IDs around 2026-09-01 18:30..19:00 UTC (or 21:30..22:00 MSK)
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT
            d.id AS detail_id,
            d.procurement_id,
            d.category_code,
            d.subcategory_code,
            d.validation_status AS current_status,
            d.validated_at AS current_validated_at,
            d.validator_version AS current_validator_version,
            d.validation_method AS current_validation_method,
            d.pipeline_generation
        FROM document_match_details d
        WHERE d.id BETWEEN 38180 AND 38220
           OR (d.validated_at >= '2026-09-01 18:30:00+00' AND d.validated_at <= '2026-09-01 19:10:00+00')
        ORDER BY d.id ASC
    """)
    rows = [dict(r) for r in cur.fetchall()]

print("=" * 80)
print("BOUNDED PROOF CANDIDATE ROWS (IDs around 38180-38220):")
print("=" * 80)
for r in rows:
    print(" ", r)

# 2. Check scratch scripts for any UPDATE/DELETE on document_match_details
scratch_files = glob.glob("/opt/CRM_Streamlit/scratch/*.py") + glob.glob("/tmp/*.py")
mutating_scripts = []

for filepath in scratch_files:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            if "UPDATE document_match_details" in content or "DELETE FROM document_match_details" in content:
                mutating_scripts.append((filepath, content))
    except Exception:
        pass

print("\n" + "=" * 80)
print("MUTATING TEST / SCRATCH SCRIPTS FOUND:")
print("=" * 80)
for filepath, content in mutating_scripts:
    print(f"\n--- {filepath} ---")
    lines = [line for line in content.splitlines() if "UPDATE" in line or "DELETE" in line or "WHERE" in line]
    for l in lines[:10]:
        print("  ", l)

doc_conn.close()
