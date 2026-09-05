#!/bin/bash
# Inspect document processor matcher - all key sections
MATCHER="/opt/CRM_Streamlit/tender_documents_research/document_processor/matcher.py"
echo "=== MATCHER LINES ==="
wc -l $MATCHER

echo "=== MATCHER FUNCTIONS AND KEY PATTERNS ==="
grep -n "def \|    break\|context_before\|context_after\|negative_phrase\|stop_phrase\|first_match" $MATCHER | head -80

echo "=== MATCHER SECTION 120-400 ==="
sed -n '120,400p' $MATCHER

echo "=== CRM QUEUE BRIDGE ==="
head -100 /opt/CRM_Streamlit/tender_documents_research/document_processor/crm_queue_bridge.py

echo "=== POPULATE_WITH_FILTERS 285-430 ==="
sed -n '285,430p' /opt/CRM_Streamlit/tender_documents_research/document_processor/queue_manager.py
