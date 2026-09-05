#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASE 9D: FIX REMAINING REFERENCES ==="

/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
filepath = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(filepath, 'r') as f:
    content = f.read()

# Fix selected_ids reference -> filtered_total
content = content.replace(
    'len(selected_ids)',
    'filtered_total',
    1  # only first occurrence in torgi
)

with open(filepath, 'w') as f:
    f.write(content)
print("SELECTED_IDS_FIXED=YES")

# Verify no remaining selected_ids in torgi section
import re
torgi = re.search(r'def _render_torgi_tab.*?(?=\ndef _render_komissia_tab)', content, re.DOTALL)
if torgi:
    if 'selected_ids' in torgi.group():
        print("WARNING: selected_ids still referenced in torgi")
    else:
        print("NO_SELECTED_IDS_IN_TORGI=CLEAN")
PYEOF

echo "--- Kill old rescue Streamlit and restart ---"
kill $(cat /tmp/rescue_pid.txt 2>/dev/null) 2>/dev/null || true
pkill -f 'streamlit.*8505' 2>/dev/null || true
sleep 2

cd /opt/CRM_Streamlit_rescue
PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
nohup /opt/CRM_Streamlit/.venv313/bin/python \
  -m streamlit run app.py \
  --server.port 8505 \
  --server.address 127.0.0.1 \
  --server.headless true \
  --browser.gatherUsageStats false \
  > /tmp/rescue_streamlit.log 2>&1 &

RESCUE_PID=$!
echo "$RESCUE_PID" > /tmp/rescue_pid.txt
echo "RESCUE_PID=$RESCUE_PID"
sleep 5

if kill -0 $RESCUE_PID 2>/dev/null; then
  echo "RESCUE_RUNNING=YES"
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8505/ 2>/dev/null || echo "FAIL")
  echo "HTTP_CODE=$HTTP_CODE"
else
  echo "RESCUE_RUNNING=NO"
  echo "--- Last 40 lines ---"
  tail -40 /tmp/rescue_streamlit.log
fi

echo "PHASE_9D=DONE"
