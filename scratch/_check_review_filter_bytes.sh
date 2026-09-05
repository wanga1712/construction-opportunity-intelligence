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
from streamlit.testing.v1 import AppTest

at = AppTest.from_file("app.py", default_timeout=60)
at.run(timeout=60)

stage_radio = at.radio(key="analytics_v2_active_stage")
stage_radio.set_value(list(stage_radio.options)[2])
at.run(timeout=60)

for i, p in enumerate(at.pills):
    if "annotation_state_filter" in str(p.key):
        print(f"REVIEW_FILTER_PILL key={p.key} label={repr(p.label)}")
        for opt in p.options:
            print(f"   opt repr: {repr(opt)}")
            print(f"   opt bytes: {opt.encode('utf-8')}")

PYEOF
