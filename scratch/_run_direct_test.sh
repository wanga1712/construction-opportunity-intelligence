#!/bin/bash
set -a
. /opt/CRM_Streamlit/.env
set +a
cd /opt/CRM_Streamlit
export PYTHONPATH=/opt/CRM_Streamlit:/opt/pythonProject89
export DIRECT_TEST_PID="${1:-459631}"
.venv313/bin/python /tmp/_direct_test.py 2>&1 | grep -vE "radar_database|tender_database" | tail -60
