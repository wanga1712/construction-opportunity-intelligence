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

print("=== DISTINCT CANARY SELECTOR ===")
p44_rows = crm_db.execute_query("""
    SELECT DISTINCT p.id, p.source_table, p.source_id, p.contract_number, a.normalized_result->>'research_action' as ai_action
    FROM crm_procurements p
    LEFT JOIN procurement_ai_assessments a ON a.procurement_id = p.id
    WHERE p.source_table = 'reestr_contract_44_fz'
    ORDER BY p.id DESC
    LIMIT 30
""") or []

p223_rows = crm_db.execute_query("""
    SELECT DISTINCT p.id, p.source_table, p.source_id, p.contract_number, a.normalized_result->>'research_action' as ai_action
    FROM crm_procurements p
    LEFT JOIN procurement_ai_assessments a ON a.procurement_id = p.id
    WHERE p.source_table = 'reestr_contract_223_fz'
    ORDER BY p.id DESC
    LIMIT 30
""") or []

unique_44 = []
for r in p44_rows:
    if r["id"] not in unique_44:
        unique_44.append(r["id"])

unique_223 = []
for r in p223_rows:
    if r["id"] not in unique_223:
        unique_223.append(r["id"])

canary_44 = unique_44[:10]
canary_223 = unique_223[:10]

print("CANARY 44-ФЗ (10):", canary_44)
print("CANARY 223-ФЗ (10):", canary_223)
print(f"Total Canary Size: {len(canary_44) + len(canary_223)}")

PYEOF
