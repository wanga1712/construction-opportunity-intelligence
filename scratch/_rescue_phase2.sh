#!/bin/bash
set -eu
cd /opt/CRM_Streamlit

echo "=== PHASE 2: CREATE CLEAN RESCUE WORKTREE ==="

git worktree add \
  -b CRM-V3-S13-LOCAL-GOOD-BASE-PRODUCTION-RESCUE-1 \
  /opt/CRM_Streamlit_rescue \
  c5db3ad 2>&1

echo "--- Verify ---"
echo "RESCUE_HEAD=$(git -C /opt/CRM_Streamlit_rescue rev-parse HEAD)"
echo "RESCUE_STATUS=$(git -C /opt/CRM_Streamlit_rescue status --porcelain | wc -l)"

echo "=== PHASE 3: DISCOVER ACTUAL PROJECT ROOT ==="
cd /opt/CRM_Streamlit_rescue

echo "--- Top-level tracked app.py locations ---"
git ls-files | grep -E '^(app\.py|crm_streamlit/app\.py)$'

echo "--- Top-level tracked src/ ---"
git ls-files | grep -E '^(src/|crm_streamlit/src/)' | head -5

echo "--- Check if crm_streamlit/app.py exists ---"
if [ -f /opt/CRM_Streamlit_rescue/crm_streamlit/app.py ]; then
  echo "RESCUE_APP_ROOT=/opt/CRM_Streamlit_rescue/crm_streamlit"
  echo "RESCUE_APP_ROOT_TYPE=crm_streamlit_subtree"
else
  echo "RESCUE_APP_ROOT=/opt/CRM_Streamlit_rescue"
  echo "RESCUE_APP_ROOT_TYPE=top_level"
fi

echo "--- Verify tracked status of app root ---"
git ls-files --error-unmatch crm_streamlit/app.py 2>/dev/null && echo "RESCUE_APP_ROOT_TRACKED=YES" || echo "RESCUE_APP_ROOT_TRACKED_TOPLEVEL=checking"
git ls-files --error-unmatch crm_streamlit/src/__init__.py 2>/dev/null && echo "RESCUE_SRC_TRACKED=YES" || echo "RESCUE_SRC_TRACKED=NO"

echo "PHASE_2_3=DONE"
