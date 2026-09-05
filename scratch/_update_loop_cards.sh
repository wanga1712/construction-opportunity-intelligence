#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/autonomous_learning_loop.py"
with open(path, "r", encoding="utf-8") as f:
    code = f.read()

target = "self.save_consensus_results(procurement_id, trace_id, hunter_data, auditor_data, consensus_state)"
replacement = """self.save_consensus_results(procurement_id, trace_id, hunter_data, auditor_data, consensus_state)
            try:
                from src.services.commercial_routing_v3.canonical_card_service import sync_procurement_card_projection
                sync_procurement_card_projection(procurement_id, self.crm_db)
            except Exception as _ce:
                logger.warning(f"Card projection sync error for {procurement_id}: {_ce}")"""

if target in code and "sync_procurement_card_projection" not in code:
    code = code.replace(target, replacement)
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    print("UPDATED autonomous_learning_loop.py WITH sync_procurement_card_projection!")
else:
    print("ALREADY UPDATED OR TARGET NOT FOUND.")

PYEOF
