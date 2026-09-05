#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os, json
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from src.services.db_bootstrap import connect_databases

tender_db, radar_db, crm_db, _ = connect_databases()

traces_cnt = crm_db.execute_query("SELECT COUNT(*) as cnt FROM crm_v3_autonomous_analysis_traces")[0]["cnt"]
findings_cnt = crm_db.execute_query("SELECT COUNT(*) as cnt FROM crm_v3_product_findings")[0]["cnt"]
researched_cnt = crm_db.execute_query("SELECT COUNT(DISTINCT procurement_id) as cnt FROM crm_v3_autonomous_analysis_traces")[0]["cnt"]

print(f"POST_TRACES={traces_cnt}")
print(f"POST_FINDINGS={findings_cnt}")
print(f"POST_RESEARCHED_PROCUREMENTS={researched_cnt}")

traces = crm_db.execute_query("""
    SELECT procurement_id, consensus_state, research_completeness, created_at
    FROM crm_v3_autonomous_analysis_traces
    ORDER BY id DESC
    LIMIT 20
""") or []

print("\n=== RECENT AUTONOMOUS TRACES ===")
for t in traces:
    print(f"  Procurement {t['procurement_id']}: consensus={t['consensus_state']}, completeness={t['research_completeness']}, created_at={t['created_at']}")

findings = crm_db.execute_query("""
    SELECT id, procurement_id, procurement_number, category_code, product_name_normalized, raw_description, document_name, source_locator_json
    FROM crm_v3_product_findings
    ORDER BY id DESC
    LIMIT 5
""") or []

print("\n=== SAMPLE NORMALIZED FINDING ===")
if findings:
    print(json.dumps(findings[0], indent=2, ensure_ascii=False, default=str))

PYEOF
