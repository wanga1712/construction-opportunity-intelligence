#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/factual_feeder.py"
with open(path, "r", encoding="utf-8") as f:
    code = f.read()

target = """    def load_factual_candidates(self, limit: int = 100) -> List[Dict[str, Any]]:
        \"\"\"Fetch candidate procurements directly from crm_procurements (44-???? and 223-????) based on factual state.\"\"\"
        sql = \"\"\"
            SELECT DISTINCT ON (p.id) p.id, p.source_table, p.source_id, p.contract_number, p.updated_at
            FROM crm_procurements p
            WHERE p.source_table IN ('reestr_contract_44_fz', 'reestr_contract_223_fz')
            ORDER BY p.id DESC, p.updated_at DESC NULLS LAST
            LIMIT %s
        \"\"\""""

replacement = """    def load_factual_candidates(self, limit: int = 100) -> List[Dict[str, Any]]:
        \"\"\"Fetch candidate procurements directly from crm_procurements (44-???? and 223-????) based on factual state.\"\"\"
        sql = \"\"\"
            SELECT DISTINCT ON (p.id) p.id, p.source_table, p.source_id, p.contract_number
            FROM crm_procurements p
            WHERE p.source_table IN ('reestr_contract_44_fz', 'reestr_contract_223_fz')
            ORDER BY p.id DESC
            LIMIT %s
        \"\"\""""

assert target in code, "target not found in factual_feeder.py"
code = code.replace(target, replacement)
with open(path, "w", encoding="utf-8") as f:
    f.write(code)

print("UPDATED load_factual_candidates IN factual_feeder.py!")
PYEOF
