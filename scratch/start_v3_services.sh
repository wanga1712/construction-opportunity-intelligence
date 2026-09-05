#!/bin/bash
echo "=== Starting V3 services ==="

echo "--- crm-v3-autonomous-worker.service ---"
sudo systemctl start crm-v3-autonomous-worker.service 2>&1 && echo "STARTED" || echo "FAILED"

echo ""
echo "--- crm-v3-learning-observer.service ---"
sudo systemctl start crm-v3-learning-observer.service 2>&1 && echo "STARTED" || echo "FAILED"

echo ""
echo "=== Service Status ==="
sudo systemctl status tender-docs-daemon.service --no-pager -l 2>&1 | head -10
echo ""
sudo systemctl status crm-v3-autonomous-worker.service --no-pager -l 2>&1 | head -15
echo ""
sudo systemctl status crm-v3-learning-observer.service --no-pager -l 2>&1 | head -15
