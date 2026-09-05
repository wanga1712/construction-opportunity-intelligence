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
page_input = [ni for ni in at.number_input if str(ni.key) == "torgi_workset_page"][0]

print(f"Page value before set_value: {page_input.value}")
page_input.set_value(2)
at.run(timeout=60)

page_input_after_run1 = [ni for ni in at.number_input if str(ni.key) == "torgi_workset_page"][0]
print(f"Page value after set_value(2) and run: {page_input_after_run1.value}")

law_pills.set_value(law_pills.options[1]) # 44-ФЗ
at.run(timeout=60)

page_input_after_law_change = [ni for ni in at.number_input if str(ni.key) == "torgi_workset_page"][0]
print(f"Page value after law change to 44-ФЗ and run: {page_input_after_law_change.value}")
assert page_input_after_law_change.value == 1, "Page did not reset to 1!"
print("PAGE RESET TEST PASSED 100%!")

PYEOF
