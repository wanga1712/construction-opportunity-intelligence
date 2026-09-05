#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASE 3B: CONFIRM APP ROOT ==="
echo "--- app.py location ---"
ls -la app.py
echo "--- src/ init ---"
ls -la src/__init__.py
echo "--- tracked app.py ---"
git ls-files --error-unmatch app.py && echo "APP_PY_TRACKED=YES" || echo "APP_PY_TRACKED=NO"
git ls-files --error-unmatch src/__init__.py && echo "SRC_INIT_TRACKED=YES" || echo "SRC_INIT_TRACKED=NO"

echo "--- Key module existence ---"
for f in src/ui/components/analytics_v2/tabs.py \
         src/ui/components/analytics_v2/annotation_card.py \
         src/ui/components/analytics_v2/card_compact.py \
         src/services/expert_annotation_service.py \
         src/services/annotation_state_service.py; do
  if [ -f "$f" ]; then
    tracked="NO"
    git ls-files --error-unmatch "$f" >/dev/null 2>&1 && tracked="YES"
    echo "EXISTS=$f TRACKED=$tracked"
  else
    echo "MISSING=$f"
  fi
done

echo "RESCUE_APP_ROOT=/opt/CRM_Streamlit_rescue"
echo "RESCUE_APP_ROOT_TRACKED=YES"

echo "=== PHASE 4: PORT LEARNING BACKEND ==="
echo "--- Discover learning files in donor af45f27 ---"
git -C /opt/CRM_Streamlit ls-tree -r --name-only af45f27 | grep -E '(autonomous_worker|autonomous_learning_loop|reward_ledger_service|experience_memory|sparse_dataset_compiler)\.py$'

echo "--- Check if they exist already in rescue ---"
for f in $(git -C /opt/CRM_Streamlit ls-tree -r --name-only af45f27 | grep -E '(autonomous_worker|autonomous_learning_loop|reward_ledger_service|experience_memory|sparse_dataset_compiler)\.py$'); do
  if [ -f "$f" ]; then
    echo "ALREADY_EXISTS=$f"
  else
    echo "NEEDS_PORT=$f"
  fi
done
