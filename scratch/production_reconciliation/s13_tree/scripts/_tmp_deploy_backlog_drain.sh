#!/bin/bash
set -euo pipefail
ROOT=/opt/CRM_Streamlit
OUT=/var/lib/crm-v3-canary/continuous_backlog_drain
mkdir -p "$OUT"

sudo cp "$ROOT/deploy/crm-ai-assessment-runner.service" /etc/systemd/system/crm-ai-assessment-runner.service
sudo cp "$ROOT/deploy/crm-ai-assessment-runner.timer" /etc/systemd/system/crm-ai-assessment-runner.timer
sudo systemctl daemon-reload
sudo systemctl enable crm-ai-assessment-runner.timer
# Restart timer to pick up new OnUnitActiveSec cadence
sudo systemctl restart crm-ai-assessment-runner.timer

{
  echo "DEPLOYED_AT=$(date -Is)"
  systemctl cat crm-ai-assessment-runner.service | sed -n '1,30p'
  echo '---'
  systemctl cat crm-ai-assessment-runner.timer
  echo "TIMER_ACTIVE=$(systemctl is-active crm-ai-assessment-runner.timer)"
  echo "TIMER_ENABLED=$(systemctl is-enabled crm-ai-assessment-runner.timer)"
  systemctl show crm-ai-assessment-runner.timer -p NextElapseUSecRealtime -p ActiveState -p SubState
  echo "SYNC=$(systemctl is-active crm-procurement-sync.timer)"
  echo "MEDAL=$(systemctl is-active crm-v3-daily-medal-reevaluation.timer)/$(systemctl is-enabled crm-v3-daily-medal-reevaluation.timer)"
} | tee "$OUT/deploy.txt"
echo OK
