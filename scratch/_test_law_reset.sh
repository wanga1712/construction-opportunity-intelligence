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

law_pills = None
for p in at.pills:
    if str(p.key).startswith("torgi_law_filter"):
        law_pills = p
        break

ui_counts = {}
for opt in law_pills.options:
    s = str(opt)
    delim = "·" if "·" in s else ("\u00b7" if "\u00b7" in s else " ")
    parts = s.split(delim)
    k = parts[0].strip()
    v = int(parts[-1].strip())
    ui_counts[k] = v

print("PARSED LAW UI COUNTS:")
print(json.dumps(ui_counts, indent=2, ensure_ascii=False))

ui_all = ui_counts.get("\u0412\u0441\u0435") or ui_counts.get("Все")
ui_44 = ui_counts.get("44-\u0424\u0417") or ui_counts.get("44-ФЗ")
ui_223 = ui_counts.get("223-\u0424\u0417") or ui_counts.get("223-ФЗ")

print(f"UI_ALL={ui_all}, UI_44={ui_44}, UI_223={ui_223}")

# Page reset test
page_input = None
for ni in at.number_input:
    if str(ni.key) == "torgi_workset_page":
        page_input = ni
        break

print(f"Initial page value={page_input.value}")
page_input.set_value(2)
at.run(timeout=60)
print(f"After page set to 2, page_input.value={page_input.value}")

law_pills.set_value(law_pills.options[1]) # 44-ФЗ
at.run(timeout=60)
print(f"After law change to 44-ФЗ, page_input.value={page_input.value}")

PYEOF
