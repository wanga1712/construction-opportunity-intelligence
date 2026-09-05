#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
from src.services.db_bootstrap import connect_databases
_, _, crm_db, _ = connect_databases()

sql_raw = """
ALTER TABLE crm_v3_raw_source_evidence
ADD COLUMN IF NOT EXISTS research_generation_hash text,
ADD COLUMN IF NOT EXISTS pipeline_generation text DEFAULT 'S13_V2';

CREATE INDEX IF NOT EXISTS idx_rw_ev_gen_hash ON crm_v3_raw_source_evidence (procurement_id, research_generation_hash);
"""

sql_find = """
ALTER TABLE crm_v3_product_findings
ADD COLUMN IF NOT EXISTS raw_evidence_id bigint,
ADD COLUMN IF NOT EXISTS relevance text DEFAULT 'RELEVANT',
ADD COLUMN IF NOT EXISTS research_generation_hash text;

CREATE INDEX IF NOT EXISTS idx_pf_raw_ev ON crm_v3_product_findings (raw_evidence_id);
CREATE INDEX IF NOT EXISTS idx_pf_gen_hash ON crm_v3_product_findings (procurement_id, research_generation_hash);
"""

crm_db.execute_query(sql_raw)
crm_db.execute_query(sql_find)
print("SUCCESSFULLY APPLIED PROVENANCE MIGRATION ON CRM DB!")

PYEOF
