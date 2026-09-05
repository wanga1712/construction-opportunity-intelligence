#!/bin/bash
echo "=== Checking daemon.py patch ==="
grep -n "S13_V2.*populate\|populate.*S13_V2\|skip legacy populate" /opt/CRM_Streamlit/tender_documents_research/document_processor/daemon.py

echo ""
echo "=== populate_on_startup line in daemon.py ==="
grep -n "populate_on_startup\|populate_if_needed" /opt/CRM_Streamlit/tender_documents_research/document_processor/daemon.py

echo ""
echo "=== Is daemon running from CRM_Streamlit or tender_documents_research? ==="
readlink -f /opt/tender_documents_research/document_processor/daemon.py
ls -la /opt/tender_documents_research/document_processor/daemon.py
