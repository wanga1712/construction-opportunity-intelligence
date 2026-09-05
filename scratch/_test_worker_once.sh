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
from src.services.commercial_routing_v3.autonomous_worker import AutonomousWorker

tender_db, radar_db, crm_db, _ = connect_databases()

class CRMDBWrapper:
    def __init__(self, db_mgr):
        self.db_mgr = db_mgr
    def execute_query(self, sql, params=None):
        return self.db_mgr.execute_query(sql, params)
    def execute_update(self, sql, params=None):
        return self.db_mgr.execute_update(sql, params)
    def execute_query_one(self, sql, params=None):
        rows = self.db_mgr.execute_query(sql, params)
        return rows[0] if rows else None
    def execute_scalar(self, sql, params=None):
        rows = self.db_mgr.execute_query(sql, params)
        if rows:
            row = rows[0]
            return row[0] if isinstance(row, (tuple, list)) else next(iter(row.values()))
        return None

crm_wrapper = CRMDBWrapper(crm_db)
worker = AutonomousWorker(crm_wrapper)

print("=== EXECUTING WORKER RUN_ONCE ===")
res = worker.run_once()
print(f"WORKER RUN_ONCE PROCESSED TASK COUNT: {res}")

PYEOF
