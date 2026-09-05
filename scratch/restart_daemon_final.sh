#!/bin/bash
sudo systemctl restart tender-docs-daemon.service
sleep 10
echo "=== Service Status ==="
sudo systemctl status tender-docs-daemon.service --no-pager | head -8
echo ""
echo "=== Latest journal (non-error) ==="
sudo journalctl -u tender-docs-daemon.service --since "1 min ago" --no-pager | grep -v "document_processing_queue\|LINE 32" | head -30
