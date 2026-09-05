#!/bin/bash
echo "=== MATCH REPOSITORY save_matches ==="
grep -n "context_before\|context_after\|category_code\|subcategory" /opt/CRM_Streamlit/tender_documents_research/document_processor/match_repository.py
echo "---DONE---"
echo "=== CRM QUEUE BRIDGE admission ==="
grep -n "stop_word\|admission\|research_action\|SKIP\|WOOD\|medal\|NO_COMMERCIAL\|GATE" /opt/CRM_Streamlit/tender_documents_research/document_processor/crm_queue_bridge.py
echo "---DONE---"

echo "=== QUEUE POPULATE COORDINATOR ==="
cat /opt/CRM_Streamlit/tender_documents_research/document_processor/queue_populate_coordinator.py
echo "---DONE---"

echo "=== DOCUMENT PROCESSING QUEUE schema ==="
PGPASSWORD=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT psql -h 127.0.0.1 -U doc_worker -d document_intelligence -c "\d document_processing_queue"
echo "---DONE---"
