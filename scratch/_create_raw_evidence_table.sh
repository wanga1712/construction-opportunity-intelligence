#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')

from src.services.db_bootstrap import connect_databases

tender_db, radar_db, crm_db, _ = connect_databases()

sql = """
CREATE TABLE IF NOT EXISTS crm_v3_raw_source_evidence (
    id BIGSERIAL PRIMARY KEY,
    procurement_id BIGINT NOT NULL,
    source_document_id BIGINT,
    document_name TEXT,
    matched_term TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    context_before JSONB,
    context_after JSONB,
    source_locator_json JSONB NOT NULL,
    discovery_method VARCHAR(80) NOT NULL,
    suggested_category_code VARCHAR(80),
    evidence_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_raw_evidence_proc_doc_hash UNIQUE (procurement_id, source_document_id, evidence_hash)
);
CREATE INDEX IF NOT EXISTS idx_rw_ev_procurement ON crm_v3_raw_source_evidence (procurement_id);
"""

crm_db.execute_update(sql)
print("SUCCESSFULLY CREATED/VERIFIED crm_v3_raw_source_evidence TABLE IN CRM DB!")

PYEOF
