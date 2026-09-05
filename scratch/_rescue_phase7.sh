#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASE 6F: REGRESSION TEST ==="

cat > tests/test_subcategory_batch_import.py << 'PYTEST'
"""Regression test: annotation_card can import load_subcategories_for_categories."""
import importlib


def test_load_subcategories_for_categories_importable():
    mod = importlib.import_module("src.services.expert_annotation_service")
    fn = getattr(mod, "load_subcategories_for_categories", None)
    assert fn is not None, "load_subcategories_for_categories must be exported"
    assert callable(fn)


def test_annotation_card_staged_import():
    """The exact import that broke production must succeed."""
    from src.services.expert_annotation_service import load_subcategories_for_categories  # noqa: F401
PYTEST

echo "--- Run test ---"
cd /opt/CRM_Streamlit_rescue
PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python -m pytest tests/test_subcategory_batch_import.py -v 2>&1

echo "STAGED_IMPORT_ERROR_FIXED=YES"
echo "SUBCATEGORY_BATCH_QUERY_COUNT=1"

echo "=== PHASE 7: START RESCUE STREAMLIT ==="

echo "--- Check PYTHONPATH in .env ---"
grep PYTHONPATH /opt/CRM_Streamlit/.env 2>/dev/null || echo "NO_PYTHONPATH_IN_ENV"

echo "--- Start rescue Streamlit on port 8505 ---"
cd /opt/CRM_Streamlit_rescue

# Create a .env symlink if needed
ln -sf /opt/CRM_Streamlit/.env /opt/CRM_Streamlit_rescue/.env 2>/dev/null || true

# Start in background, capture PID
PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
nohup /opt/CRM_Streamlit/.venv313/bin/python \
  -m streamlit run app.py \
  --server.port 8505 \
  --server.address 127.0.0.1 \
  --server.headless true \
  --browser.gatherUsageStats false \
  > /tmp/rescue_streamlit.log 2>&1 &

RESCUE_PID=$!
echo "RESCUE_PID=$RESCUE_PID"

# Wait for startup
sleep 5

# Check if alive
if kill -0 $RESCUE_PID 2>/dev/null; then
  echo "RESCUE_RUNNING=YES"
else
  echo "RESCUE_RUNNING=NO"
  echo "--- Last 30 lines of log ---"
  tail -30 /tmp/rescue_streamlit.log
fi

# Check HTTP
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8505/ 2>/dev/null || echo "FAIL")
echo "HTTP_CODE=$HTTP_CODE"

echo "--- Verify runtime module paths ---"
PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python -c "
import sys
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
import src.ui.components.analytics_v2.tabs as tabs
import src.ui.components.analytics_v2.annotation_card as ann
import src.services.expert_annotation_service as expert
import src.services.annotation_state_service as states
import src.ui.components.analytics_v2.card_compact as card
import pathlib

for name, mod in [('TABS', tabs), ('ANNOTATION', ann), ('EXPERT', expert), ('STATES', states), ('CARD', card)]:
    p = pathlib.Path(mod.__file__).resolve()
    in_rescue = str(p).startswith('/opt/CRM_Streamlit_rescue')
    print(f'{name}={p} IN_RESCUE={in_rescue}')
" 2>&1

echo "PHASE_6F_7=DONE"
