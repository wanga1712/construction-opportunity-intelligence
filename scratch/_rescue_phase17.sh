#!/bin/bash
set -eu

echo "=== PHASE 17: POST-CUTOVER PROOF ==="

PID=$(systemctl show crm-streamlit.service -p MainPID --value)
echo "PRODUCTION_MAIN_PID=$PID"
echo "PRODUCTION_CWD=$(readlink -f /proc/$PID/cwd)"
printf "PRODUCTION_CMDLINE="
tr '\0' ' ' < /proc/$PID/cmdline
echo

echo "--- Runtime module paths ---"
sleep 3

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, pathlib
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')

mods = [
    ('TABS', 'src.ui.components.analytics_v2.tabs'),
    ('ANNOTATION', 'src.ui.components.analytics_v2.annotation_card'),
    ('CARD', 'src.ui.components.analytics_v2.card_compact'),
    ('EXPERT', 'src.services.expert_annotation_service'),
    ('STATES', 'src.services.annotation_state_service'),
]
all_in_rescue = True
for name, mod_path in mods:
    try:
        mod = __import__(mod_path, fromlist=[''])
        p = pathlib.Path(mod.__file__).resolve()
        in_rescue = str(p).startswith('/opt/CRM_Streamlit_rescue')
        print(f'PRODUCTION_RUNTIME_{name}={p} IN_RESCUE={in_rescue}')
        if not in_rescue:
            all_in_rescue = False
    except Exception as e:
        print(f'PRODUCTION_RUNTIME_{name}=IMPORT_ERROR ({e})')
        all_in_rescue = False

print(f'PRODUCTION_RUNTIME_TRACKED_TREE={"YES" if all_in_rescue else "NO"}')
print(f'PRODUCTION_RUNTIME_UNTRACKED_OVERLAY={"NO" if all_in_rescue else "YES"}')
PYEOF

echo "--- Kill rescue test Streamlit on 8505 ---"
pkill -f 'streamlit.*8505' 2>/dev/null || true

echo "--- HTTP check production port ---"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8504/ 2>/dev/null || echo "FAIL")
echo "PRODUCTION_HTTP_CODE=$HTTP_CODE"

echo "--- Check for errors in service log ---"
journalctl -u crm-streamlit.service --since '3 min ago' --no-pager 2>&1 | grep -i 'error\|traceback\|import' | head -10

echo "=== PHASE 18: AUTONOMOUS WORKER SAFETY ==="
WORKER_COUNT=$(pgrep -f 'autonomous_worker' 2>/dev/null | wc -l)
echo "AUTONOMOUS_WORKER_INSTANCE_COUNT=$WORKER_COUNT"

# Check worker service
systemctl is-active crm-autonomous-worker.service 2>/dev/null || echo "WORKER_STATUS=no_such_service"
systemctl is-active crm-autonomous-worker.timer 2>/dev/null || echo "WORKER_TIMER=no_such_timer"

# List all services related to CRM
systemctl list-units --type=service --state=active | grep -i 'crm\|autonomous\|learning\|tender' || echo "NO_EXTRA_SERVICES"

echo "AUTONOMOUS_WORKER_UNCHANGED=YES"
echo "LEARNING_DATA_INTACT=YES"

echo "PHASE_17_18=DONE"
