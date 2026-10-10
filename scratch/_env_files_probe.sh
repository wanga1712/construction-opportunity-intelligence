#!/bin/bash
ls -l /etc/tender-docs-db.env /etc/tender-docs-worker-open.env /opt/tender_documents_research/.env
echo "--- /etc/tender-docs-db.env keys (values masked) ---"
sed -E 's/=(.*)$/=***/' /etc/tender-docs-db.env 2>/dev/null | head -25 || echo "(не читается под текущим пользователем)"
echo "--- /etc/tender-docs-worker-open.env ---"
cat /etc/tender-docs-worker-open.env 2>/dev/null || echo "(не читается)"
echo "--- keys in research .env ---"
sed -E 's/=(.*)$/=***/' /opt/tender_documents_research/.env | head -30
