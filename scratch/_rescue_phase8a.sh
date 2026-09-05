#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASE 8: MEASURE TORGI ROUTE ==="

echo "--- Check for full-workset enrichment patterns in tabs.py ---"
echo "--- Searching for load_current_annotation_states call ---"
grep -n 'load_current_annotation_states' src/ui/components/analytics_v2/tabs.py 2>/dev/null || echo "NOT_FOUND"

echo "--- Searching for get_effective_business_assessments call ---"
grep -n 'get_effective_business_assessments\|effective_business\|EffectiveAssessment' src/ui/components/analytics_v2/tabs.py 2>/dev/null || echo "NOT_FOUND"

echo "--- Searching for workset_ids / all IDs enrichment ---"
grep -n 'workset_ids\|all_ids\|enrichment\|enrich(' src/ui/components/analytics_v2/tabs.py 2>/dev/null || echo "NOT_FOUND"

echo "--- Searching for LIMIT / OFFSET / pagination in tabs.py ---"
grep -ni 'limit\|offset\|pagina\|page_size\|page_num\|_page' src/ui/components/analytics_v2/tabs.py 2>/dev/null || echo "NOT_FOUND"

echo "--- Lines count ---"
wc -l src/ui/components/analytics_v2/tabs.py

echo "--- Check annotation_state_service for load_current_annotation_states ---"
grep -n 'def load_current_annotation_states' src/services/annotation_state_service.py 2>/dev/null || echo "NOT_FOUND"

echo "--- tabs.py: show how workset is built (search for crm_procurements / SQL) ---"
grep -n 'crm_procurements\|SELECT.*procurement\|execute_query' src/ui/components/analytics_v2/tabs.py 2>/dev/null | head -20

echo "--- Show first 80 lines of tabs.py ---"
head -80 src/ui/components/analytics_v2/tabs.py

echo "PHASE_8_DISCOVERY=DONE"
