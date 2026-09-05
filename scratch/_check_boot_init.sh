#!/bin/bash
units=(
  tender-docs-daemon.service
  crm-v3-autonomous-worker.service
  crm-v3-learning-observer.service
  crm-v3-shadow-predictor.service
  crm-v3-learning-dataset.timer
  crm-v3-factual-feeder.service
)

for u in "${units[@]}"; do
  echo "=== $u ==="
  echo -n "ACTIVE: "
  systemctl is-active "$u"
  echo -n "ENABLED: "
  systemctl is-enabled "$u"
  systemctl show "$u" -p UnitFileState -p FragmentPath
done

echo "=== OLLAMA SEARCH ==="
systemctl list-units --type=service | grep -i ollama || true
systemctl list-unit-files | grep -i ollama || true

echo "=== POSTGRES SEARCH ==="
systemctl list-units --type=service | grep -i postgres || true
systemctl list-unit-files | grep -i postgres || true
