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

pills_widget = None
for p in at.pills:
    if p.options:
        pills_widget = p
        break

ui_counts = {}
for opt in pills_widget.options:
    s = str(opt)
    if "·" in s or "\u00b7" in s:
        delim = "·" if "·" in s else "\u00b7"
        parts = s.split(delim)
        k = parts[0].strip()
        v = int(parts[1].strip())
        ui_counts[k] = v

print("PARSED UI COUNTS:")
print(json.dumps(ui_counts, indent=2, ensure_ascii=False))

total = ui_counts.get("Все", 0)
rev = ui_counts.get("Проверено", 0)
unrev = ui_counts.get("Не проверено", 0)
print(f"WORKSET TOTAL={total}")
print(f"REVIEWED={rev}")
print(f"UNREVIEWED={unrev}")
print(f"REVIEWED + UNREVIEWED = {rev + unrev} (equals total: {rev + unrev == total})")
PYEOF
