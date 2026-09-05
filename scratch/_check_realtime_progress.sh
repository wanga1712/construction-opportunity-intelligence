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

raw_ev_cnt = crm_db.execute_query("SELECT COUNT(*) as cnt FROM crm_v3_raw_source_evidence")[0]["cnt"]
findings_cnt = crm_db.execute_query("SELECT COUNT(*) as cnt FROM crm_v3_product_findings")[0]["cnt"]
traces_cnt = crm_db.execute_query("SELECT COUNT(*) as cnt FROM crm_v3_autonomous_analysis_traces")[0]["cnt"]

print(f"RAW_EVIDENCE_COUNT={raw_ev_cnt}")
print(f"FINDINGS_COUNT={findings_cnt}")
print(f"TRACES_COUNT={traces_cnt}")

# Sample raw evidence row
sample_ev = crm_db.execute_query("""
    SELECT id, procurement_id, source_document_id, document_name, matched_term, raw_text, source_locator_json, discovery_method, evidence_hash
    FROM crm_v3_raw_source_evidence
    ORDER BY id DESC
    LIMIT 3
""") or []

print("\n=== SAMPLE RAW SOURCE EVIDENCE ===")
for r in sample_ev:
    print(json.dumps(dict(r), indent=2, ensure_ascii=False, default=str))

PYEOF
