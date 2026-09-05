#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASE 4B: PORT LEARNING BACKEND ==="

echo "--- Check existing commercial_routing_v3 in rescue ---"
ls -la src/services/commercial_routing_v3/ 2>/dev/null || echo "DIR_MISSING=src/services/commercial_routing_v3/"

echo "--- Discover all donor commercial_routing_v3 backend files ---"
git -C /opt/CRM_Streamlit ls-tree -r --name-only af45f27 -- crm_streamlit/src/services/commercial_routing_v3/

echo "--- Port backend files from donor using path mapping ---"
mkdir -p src/services/commercial_routing_v3

DONOR_FILES=(
  "crm_streamlit/src/services/commercial_routing_v3/autonomous_learning_loop.py"
  "crm_streamlit/src/services/commercial_routing_v3/autonomous_worker.py"
  "crm_streamlit/src/services/commercial_routing_v3/experience_memory.py"
  "crm_streamlit/src/services/commercial_routing_v3/reward_ledger_service.py"
  "crm_streamlit/src/services/commercial_routing_v3/sparse_dataset_compiler.py"
)

PORTED=0
UI_PORTED=0

for donor_path in "${DONOR_FILES[@]}"; do
  rescue_path="${donor_path#crm_streamlit/}"
  echo "PORTING: $donor_path -> $rescue_path"
  git -C /opt/CRM_Streamlit show "af45f27:$donor_path" > "$rescue_path"
  PORTED=$((PORTED + 1))
done

# Also port __init__.py if exists in donor
git -C /opt/CRM_Streamlit show "af45f27:crm_streamlit/src/services/commercial_routing_v3/__init__.py" > src/services/commercial_routing_v3/__init__.py 2>/dev/null && PORTED=$((PORTED + 1)) || echo "NO_INIT_IN_DONOR"

echo "LEARNING_FILES_PORTED=$PORTED"
echo "LEARNING_UI_FILES_PORTED=$UI_PORTED"
echo "LEARNING_DONOR_SHA=af45f27"

echo "--- Verify ported files exist ---"
for f in autonomous_learning_loop.py autonomous_worker.py experience_memory.py reward_ledger_service.py sparse_dataset_compiler.py; do
  if [ -f "src/services/commercial_routing_v3/$f" ]; then
    echo "PRESENT=$f"
  else
    echo "MISSING=$f"
  fi
done

echo "=== PHASE 5: VERIFY LEARNING BACKEND IMPORTS ==="
cd /opt/CRM_Streamlit_rescue
PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python -c "
import sys
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
errors = []
for mod_name in [
    'src.services.commercial_routing_v3.autonomous_worker',
    'src.services.commercial_routing_v3.autonomous_learning_loop',
    'src.services.commercial_routing_v3.reward_ledger_service',
    'src.services.commercial_routing_v3.experience_memory',
    'src.services.commercial_routing_v3.sparse_dataset_compiler',
]:
    try:
        __import__(mod_name)
        print(f'IMPORT_OK={mod_name}')
    except Exception as e:
        print(f'IMPORT_FAIL={mod_name} ERROR={repr(e)}')
        errors.append(mod_name)
if not errors:
    print('LEARNING_BACKEND_IMPORTS=PASS')
else:
    print('LEARNING_BACKEND_IMPORTS=FAIL')
    print(f'FAILED_MODULES={errors}')
" 2>&1

echo "PHASE_4_5=DONE"
