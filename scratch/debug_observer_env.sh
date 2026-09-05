#!/bin/bash
# Export variables from /etc/crm_v3.env
export $(sudo cat /etc/crm_v3.env | xargs)

/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys
sys.path.append("/opt/CRM_Streamlit_rescue")
sys.path.append("/opt/pythonProject89")

import logging
logging.basicConfig(level=logging.INFO)

from src.services.commercial_routing_v3.learning_observer import LearningObserver
observer = LearningObserver()

print("Running snapshot builder...")
snap_cnt = observer._build_missing_snapshots()
print(f"Pre-research snapshots created: {snap_cnt}")

print("Running truths builder...")
truth_cnt = observer._build_missing_truths()
print(f"Exhaustive truths created: {truth_cnt}")

PYEOF
