#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASE 6B: CHECK IMPORT AND FIX N+1 ==="

echo "--- Test actual import in rescue ---"
PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python -c "
import sys
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
try:
    from src.services.expert_annotation_service import load_subcategories_for_categories
    print(f'IMPORT_OK=load_subcategories_for_categories')
    import inspect
    src = inspect.getsource(load_subcategories_for_categories)
    print('--- CURRENT IMPL ---')
    print(src)
except Exception as e:
    print(f'IMPORT_FAIL={repr(e)}')
" 2>&1

echo "--- Show load_subcategories (per-category) ---"
sed -n '462,495p' src/services/expert_annotation_service.py

echo "PHASE_6B=DONE"
