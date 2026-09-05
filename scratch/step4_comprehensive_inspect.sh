#!/bin/bash
# Comprehensive inspection
echo "=== MATCH REPOSITORY context/category fields ==="
grep -n "context_before\|context_after\|category_code\|subcategory\|canonical_source" /opt/CRM_Streamlit/tender_documents_research/document_processor/match_repository.py
echo "EXIT=$?"

echo ""
echo "=== MATCH REPOSITORY save_matches function ==="
sed -n '/def save_matches/,/^    def /p' /opt/CRM_Streamlit/tender_documents_research/document_processor/match_repository.py | head -100

echo ""
echo "=== CRM QUEUE BRIDGE admission gates ==="
grep -n "stop_word\|admission\|eligible\|research_action\|SKIP\|WOOD\|medal\|NO_COMMERCIAL\|QUEUE_GATE" /opt/CRM_Streamlit/tender_documents_research/document_processor/crm_queue_bridge.py | head -40

echo ""
echo "=== CRM QUEUE BRIDGE head ==="
head -100 /opt/CRM_Streamlit/tender_documents_research/document_processor/crm_queue_bridge.py

echo ""
echo "=== QUEUE POPULATE COORDINATOR ==="
cat /opt/CRM_Streamlit/tender_documents_research/document_processor/queue_populate_coordinator.py

echo ""
echo "=== QUEUE_MANAGER admission gates ==="
grep -n "stop_word\|admission\|NO_COMMERCIAL\|SKIP\|WOOD\|research_action\|medal\|queue_state\|GATE\|eligible" /opt/CRM_Streamlit/tender_documents_research/document_processor/queue_manager.py | head -40

echo ""
echo "=== DOCUMENT_PROCESSING_QUEUE schema ==="
PGPASSWORD=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT psql -h 127.0.0.1 -U doc_worker -d document_intelligence -c "\d document_processing_queue"

echo ""
echo "=== DOCUMENT_MATCH_DETAILS schema ==="
PGPASSWORD=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT psql -h 127.0.0.1 -U doc_worker -d document_intelligence -c "\d document_match_details"

echo ""
echo "=== DOCUMENT_MATCHES schema ==="
PGPASSWORD=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT psql -h 127.0.0.1 -U doc_worker -d document_intelligence -c "\d document_matches"

echo ""
echo "=== SERVICE UNIT FILES ==="
cat /etc/systemd/system/tender-docs-daemon.service
echo "---"
cat /etc/systemd/system/crm-v3-autonomous-worker.service
echo "---"
cat /etc/systemd/system/crm-v3-learning-observer.service
