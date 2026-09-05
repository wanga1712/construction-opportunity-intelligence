#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os, json
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

law_pills = [p for p in at.pills if str(p.key).startswith("torgi_law_filter")][0]

p_all = [ni for ni in at.number_input if "ALL" in str(ni.key)][0]
print(f"Page under ALL initial value={p_all.value}")

p_all.set_value(2)
at.run(timeout=60)

p_all_after = [ni for ni in at.number_input if "ALL" in str(ni.key)][0]
print(f"Page under ALL after set_value(2) value={p_all_after.value}")

# Change law to 44-ФЗ
law_pills.set_value(law_pills.options[1])
at.run(timeout=60)

p_44 = [ni for ni in at.number_input if "44" in str(ni.key)][0]
print(f"Page under 44-ФЗ key={repr(p_44.key)} value={p_44.value}")

assert p_44.value == 1, "Page under 44-ФЗ is not 1!"
print("DYNAMIC KEY PAGE RESET PASSED 100%!")

PYEOF
