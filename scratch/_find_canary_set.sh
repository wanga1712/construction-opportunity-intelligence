#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.document_links import resolve_document_links

tender_db, radar_db, crm_db, _ = connect_databases()

print("=== SEARCHING 44-ФЗ CANARY CANDIDATES ===")
p44 = crm_db.execute_query("""
    SELECT p.id, p.source_table, p.source_id, p.contract_number, a.normalized_result->>'research_action' as ai_action
    FROM crm_procurements p
    LEFT JOIN procurement_ai_assessments a ON a.procurement_id = p.id
    WHERE p.source_table = 'reestr_contract_44_fz'
    ORDER BY p.id DESC
    LIMIT 200
""") or []

valid_44 = []
old_ai_skip_44 = None
for r in p44:
    docs = resolve_document_links(r["source_table"], r["source_id"], r["contract_number"])
    if docs:
        valid_44.append((r["id"], r["source_table"], r["ai_action"], len(docs)))
        if r["ai_action"] in ("SKIP", "METADATA_ONLY", None) and not old_ai_skip_44:
            old_ai_skip_44 = r["id"]

print(f"Found {len(valid_44)} 44-ФЗ procurements with documents. Sample: {valid_44[:5]}")
print(f"Old AI skip candidate 44: {old_ai_skip_44}")

print("\n=== SEARCHING 223-ФЗ CANARY CANDIDATES ===")
p223 = crm_db.execute_query("""
    SELECT p.id, p.source_table, p.source_id, p.contract_number, a.normalized_result->>'research_action' as ai_action
    FROM crm_procurements p
    LEFT JOIN procurement_ai_assessments a ON a.procurement_id = p.id
    WHERE p.source_table = 'reestr_contract_223_fz'
    ORDER BY p.id DESC
    LIMIT 200
""") or []

valid_223 = []
old_ai_skip_223 = None
for r in p223:
    docs = resolve_document_links(r["source_table"], r["source_id"], r["contract_number"])
    if docs:
        valid_223.append((r["id"], r["source_table"], r["ai_action"], len(docs)))
        if r["ai_action"] in ("SKIP", "METADATA_ONLY", None) and not old_ai_skip_223:
            old_ai_skip_223 = r["id"]

print(f"Found {len(valid_223)} 223-ФЗ procurements with documents. Sample: {valid_223[:5]}")
print(f"Old AI skip candidate 223: {old_ai_skip_223}")

PYEOF
