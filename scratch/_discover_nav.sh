#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== DISCOVER APP PAGES ==="

echo "--- app.py content ---"
head -60 app.py

echo "--- Check for streamlit pages directory ---"
ls -la pages/ 2>/dev/null || echo "NO_PAGES_DIR"

echo "--- Check for st.navigation / page_link / switch_page ---"
grep -rn 'st\.navigation\|st\.page_link\|st\.switch_page\|st_pages\|Page(' app.py 2>/dev/null | head -10
grep -rn 'st\.navigation\|switch_page\|Page(' src/ui/ 2>/dev/null | head -20

echo "--- Check sidebar structure ---"
grep -n 'sidebar\|st\.radio\|st\.selectbox' app.py | head -20

echo "--- Check multipage routing in app.py ---"
cat app.py
