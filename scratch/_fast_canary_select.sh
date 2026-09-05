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

print("=== FAST CANARY SELECTOR ===")
p44_rows = crm_db.execute_query("""
    SELECT p.id, p.source_table, p.source_id, p.contract_number, a.normalized_result->>'research_action' as ai_action
    FROM crm_procurements p
    LEFT JOIN procurement_ai_assessments a ON a.procurement_id = p.id
    WHERE p.source_table = 'reestr_contract_44_fz'
    ORDER BY p.id DESC
    LIMIT 30
""") or []

p223_rows = crm_db.execute_query("""
    SELECT p.id, p.source_table, p.source_id, p.contract_number, a.normalized_result->>'research_action' as ai_action
    FROM crm_procurements p
    LEFT JOIN procurement_ai_assessments a ON a.procurement_id = p.id
    WHERE p.source_table = 'reestr_contract_223_fz'
    ORDER BY p.id DESC
    LIMIT 30
""") or []

canary_44 = [r["id"] for r in p44_rows[:10]]
canary_223 = [r["id"] for r in p223_rows[:10]]

print("CANARY 44-ФЗ IDs:", canary_44)
print("CANARY 223-ФЗ IDs:", canary_223)

old_ai_skip_44 = [r["id"] for r in p44_rows if r["ai_action"] in ("SKIP", "METADATA_ONLY", None)]
old_ai_skip_223 = [r["id"] for r in p223_rows if r["ai_action"] in ("SKIP", "METADATA_ONLY", None)]

print("OLD_AI_SKIP 44-ФЗ IDs:", old_ai_skip_44)
print("OLD_AI_SKIP 223-ФЗ IDs:", old_ai_skip_223)

PYEOF
