#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os, json
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')

from src.services.db_bootstrap import connect_databases

tender_db, radar_db, crm_db, _ = connect_databases()

findings = crm_db.execute_query("""
    SELECT id, procurement_id, procurement_number, category_code, product_type, product_name_normalized, brand, model, quantity, unit, raw_description, evidence_text, document_name, source_locator_json, extractor_role, extraction_confidence, category_validation_status
    FROM crm_v3_product_findings
    WHERE procurement_id = 129606
    ORDER BY id ASC
""") or []

print(f"FINDINGS FOR PROC 129606: count={len(findings)}")
for f in findings:
    print(json.dumps(dict(f), default=str, ensure_ascii=False, indent=2))

PYEOF
