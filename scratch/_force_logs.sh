#!/bin/bash
echo "--- systemd-run units (last 60 min) ---"
journalctl --since "60 min ago" --no-pager 2>/dev/null | grep -iE "force_direct|force_run|run-r" | tail -30
echo "--- stale PROCESSING rows of worker 77 ---"
sudo -n -u postgres psql -d document_intelligence -Atc "select id, procurement_id, contract_number, status, started_at from document_processing_queue where worker_id=77"
echo "--- errors around that time ---"
journalctl --since "60 min ago" --no-pager 2>/dev/null | grep -iE "Traceback|Error|timeout" | tail -15
