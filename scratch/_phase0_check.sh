#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)"
echo "CURRENT_HEAD=$(git rev-parse HEAD)"

PID=$(systemctl show crm-streamlit.service -p MainPID --value)
echo "SERVICE_PID=$PID"
echo "PRODUCTION_CWD=$(readlink -f /proc/$PID/cwd)"

PYEOF
