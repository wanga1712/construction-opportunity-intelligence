#!/bin/bash
pkill -f populate_actual 2>/dev/null || true
sleep 1
nohup /opt/CRM_Streamlit/.venv313/bin/python /tmp/run_populate_actual.py > /tmp/populate_actual2.log 2>&1 &
echo "PID=$! LAUNCHED"
sleep 5
echo "=== FIRST LOG LINES ==="
head -20 /tmp/populate_actual2.log
