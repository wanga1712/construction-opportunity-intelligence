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

law_pills = [p for p in at.pills if str(p.key).startswith("torgi_law_filter")][0]

# Page under ALL
page_all = [ni for ni in at.number_input if str(ni.key) == "torgi_workset_page_ALL"][0]
print(f"Page value under ALL before change: {page_all.value}")

page_all.set_value(2)
at.run(timeout=60)

page_all = [ni for ni in at.number_input if str(ni.key) == "torgi_workset_page_ALL"][0]
print(f"Page value under ALL after set_value(2): {page_all.value}")

# Switch to 44-ФЗ
law_pills.set_value(law_pills.options[1]) # 44-ФЗ
at.run(timeout=60)

page_44 = [ni for ni in at.number_input if str(ni.key) == "torgi_workset_page_44-ФЗ"][0]
print(f"Active page value under 44-ФЗ (key={page_44.key}): {page_44.value}")
assert page_44.value == 1, "Page under 44-ФЗ is not 1!"

print("PAGE RESET TEST WITH DYNAMIC KEY PASSED 100%!")

PYEOF
