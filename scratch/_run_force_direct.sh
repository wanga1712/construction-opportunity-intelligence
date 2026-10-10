#!/bin/bash
# usage: bash /tmp/_run_force_direct.sh [batch_size]
BATCH="${1:-5}"
sudo -n systemd-run --pipe --wait --collect --uid=sergey --gid=sergey \
  --property=WorkingDirectory=/opt/tender_documents_research \
  --property=EnvironmentFile=/opt/tender_documents_research/.env \
  --property=EnvironmentFile=/etc/tender-docs-db.env \
  --property=EnvironmentFile=/etc/tender-docs-worker-open.env \
  --property=EnvironmentFile=-/etc/tender-docs-s13v2-overlay.env \
  --property=EnvironmentFile=-/etc/tender-docs-s13-local-db.env \
  --property=Environment=PROCESSING_BACKEND=S13_V4 \
  --property=Environment=MODEL_QUEUE_PRIORITY_ENABLED=1 \
  --property=Environment=DOCUMENT_STORAGE_ROOT=/data/tender-documents \
  --property=Environment=DOCUMENT_DOWNLOAD_DIR=/data/tender-documents/downloads \
  --property=Environment=S13_DOCUMENT_DB_HOST=127.0.0.1 \
  --property=Environment=S13_DOCUMENT_DB_PORT=5432 \
  --property=Environment=S13_DOCUMENT_DB_NAME=document_intelligence \
  --property=Environment=DOWNLOAD_MAX_CONCURRENT=1 \
  --property=Environment=FORCE_BATCH="$BATCH" \
  /opt/tender_documents_research/.venv/bin/python \
  /opt/CRM_Streamlit/scripts/force_direct_documents.py
