#!/bin/bash
# Operational deploy of continuous-production startup units/code. Docs stay OFF.
set -euo pipefail
ROOT=/opt/CRM_Streamlit
OUT=/var/lib/crm-v3-canary/continuous_production_startup
mkdir -p "$OUT"

# Persist production flags in .env (idempotent)
ENVF="$ROOT/.env"
grep -q '^COMMERCIAL_ROUTING_V3_PERSIST_OPPORTUNITIES_DRY_RUN=' "$ENVF" 2>/dev/null \
  && sed -i 's/^COMMERCIAL_ROUTING_V3_PERSIST_OPPORTUNITIES_DRY_RUN=.*/COMMERCIAL_ROUTING_V3_PERSIST_OPPORTUNITIES_DRY_RUN=0/' "$ENVF" \
  || echo 'COMMERCIAL_ROUTING_V3_PERSIST_OPPORTUNITIES_DRY_RUN=0' >> "$ENVF"
grep -q '^CRM_V3_WAITING_ROUTABLE=' "$ENVF" 2>/dev/null \
  && sed -i 's/^CRM_V3_WAITING_ROUTABLE=.*/CRM_V3_WAITING_ROUTABLE=0/' "$ENVF" \
  || echo 'CRM_V3_WAITING_ROUTABLE=0' >> "$ENVF"
grep -q '^COMMERCIAL_ROUTING_V3_RUNTIME_ENABLED=' "$ENVF" 2>/dev/null \
  && sed -i 's/^COMMERCIAL_ROUTING_V3_RUNTIME_ENABLED=.*/COMMERCIAL_ROUTING_V3_RUNTIME_ENABLED=1/' "$ENVF" \
  || echo 'COMMERCIAL_ROUTING_V3_RUNTIME_ENABLED=1' >> "$ENVF"

sudo cp "$ROOT/deploy/crm-ai-assessment-runner.service" /etc/systemd/system/crm-ai-assessment-runner.service
sudo cp "$ROOT/deploy/crm-ai-assessment-runner.timer" /etc/systemd/system/crm-ai-assessment-runner.timer
sudo cp "$ROOT/deploy/crm-v3-daily-medal-reevaluation.service" /etc/systemd/system/crm-v3-daily-medal-reevaluation.service
sudo cp "$ROOT/deploy/crm-v3-daily-medal-reevaluation.timer" /etc/systemd/system/crm-v3-daily-medal-reevaluation.timer
sudo systemctl daemon-reload

{
  echo "DEPLOYED_AT=$(date -Is)"
  echo "WAITING_ROUTABLE_CODE=$(grep WAITING_ROUTABLE $ROOT/src/services/commercial_routing_v3/routing_runtime_config.py)"
  grep -E '^(COMMERCIAL_ROUTING_V3_|CRM_V3_WAITING)' "$ENVF"
} | tee "$OUT/deploy_units.txt"
echo OK
