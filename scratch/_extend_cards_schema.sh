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

ddl = """
ALTER TABLE crm_v3_canonical_procurement_cards
    ADD COLUMN IF NOT EXISTS research_state VARCHAR(40) NOT NULL DEFAULT 'WAITING_RESEARCH',
    ADD COLUMN IF NOT EXISTS documents_discovered INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS documents_supported INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS documents_researched INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS documents_failed INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS documents_unsupported INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS documents_no_content INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS raw_evidence_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS accepted_evidence_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS normalized_findings_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS documents_with_evidence INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS preliminary_research_priority VARCHAR(40) NOT NULL DEFAULT 'UNSCORED',
    ADD COLUMN IF NOT EXISTS research_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS research_completed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS research_generation VARCHAR(40) NOT NULL DEFAULT 'S13_V2',
    ADD COLUMN IF NOT EXISTS source_snapshot_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS document_set_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS parsed_content_hash VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_cpc_research_state ON crm_v3_canonical_procurement_cards (research_state);
CREATE INDEX IF NOT EXISTS idx_cpc_preliminary_priority ON crm_v3_canonical_procurement_cards (preliminary_research_priority);
"""

crm_db.execute_update(ddl)
print("SUCCESSFULLY EXTENDED crm_v3_canonical_procurement_cards SCHEMA AND CREATED INDEXES!")

PYEOF
