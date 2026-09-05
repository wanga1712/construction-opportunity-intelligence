#!/bin/bash
set -e

echo "=== Create /opt/tender_documents_research/.env ==="
cat > /opt/tender_documents_research/.env << 'ENVEOF'
# CRM production DB connection (for queue reading and evidence writing)
CRM_DB_HOST=127.0.0.1
CRM_DB_PORT=5432
CRM_DB_DATABASE=crm
CRM_DB_USER=crm_app
CRM_DB_PASSWORD=X17B3n5hbANQSRt6i7WIyy0lJudX

# Document intelligence DB  
DOCUMENT_DB_HOST=127.0.0.1
DOCUMENT_DB_PORT=5432
DOCUMENT_DB_NAME=document_intelligence
DOCUMENT_DB_USER=doc_worker
DOCUMENT_DB_PASSWORD=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT
ENVEOF
echo "Created .env"

echo ""
echo "=== Check daemon can start dry-run ==="
PYTHONPATH=/opt/tender_documents_research /opt/tender_documents_research/.venv/bin/python -c "
from document_processor.daemon import main
print('DAEMON_IMPORT_FINAL_OK')
"

echo ""
echo "=== Reload systemd and enable ==="
sudo systemctl daemon-reload
sudo systemctl enable tender-docs-daemon.service
echo "ENABLED=OK"

echo ""
echo "=== Start daemon ==="
sudo systemctl start tender-docs-daemon.service
sleep 3
sudo systemctl status tender-docs-daemon.service --no-pager
echo ""
sudo journalctl -u tender-docs-daemon.service -n 20 --no-pager
