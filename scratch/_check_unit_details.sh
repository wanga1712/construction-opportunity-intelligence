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
  systemctl show "$u" -p ExecStart -p WorkingDirectory -p Wants -p WantedBy -p After -p Restart -p RestartSec
done
