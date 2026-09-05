#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, inspect
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
import src.ui.components.analytics_v2.stage_workspace as sw
import src.ui.components.analytics_v2.tabs as tabs
import src.services.annotation_state_service as ass

print("=== STAGE WORKSPACE ===")
for name in dir(sw):
    if "FILTER" in name or "LABEL" in name or "TITLE" in name or "HEADER" in name:
        val = getattr(sw, name)
        print(f"sw.{name} = {repr(val)}")

print("\n=== TABS ===")
for name in dir(tabs):
    if "FILTER" in name or "LABEL" in name or "TITLE" in name:
        val = getattr(tabs, name)
        print(f"tabs.{name} = {repr(val)}")

print("\n=== ASS ===")
for name in dir(ass):
    if "FILTER" in name or "LABEL" in name or "STATE" in name:
        val = getattr(ass, name)
        print(f"ass.{name} = {repr(val)}")

PYEOF
