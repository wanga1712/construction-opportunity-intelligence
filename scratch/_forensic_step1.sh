#!/bin/bash
set -u
echo "=== HOST ==="
hostname
date

echo "=== SERVICE ==="
systemctl status crm-streamlit.service --no-pager 2>&1 || true

echo "=== SERVICE CAT ==="
systemctl cat crm-streamlit.service 2>&1 || true

PID=$(systemctl show crm-streamlit.service -p MainPID --value)
echo "MAIN_PID=$PID"

if [ "$PID" -gt 0 ] 2>/dev/null; then
  echo "CWD=$(readlink -f /proc/$PID/cwd 2>/dev/null || echo UNAVAILABLE)"
  echo "EXE=$(readlink -f /proc/$PID/exe 2>/dev/null || echo UNAVAILABLE)"
  printf "CMDLINE="
  tr '\0' ' ' < /proc/$PID/cmdline 2>/dev/null || echo UNAVAILABLE
  echo
else
  echo "CWD=SERVICE_NOT_RUNNING"
  echo "EXE=SERVICE_NOT_RUNNING"
  echo "CMDLINE=SERVICE_NOT_RUNNING"
fi
