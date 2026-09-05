#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASE 15: COMMIT RESCUE ==="

# Normalize all CRLF
find . -name '*.py' -not -path './.venv*' -exec sed -i 's/\r$//' {} + 2>/dev/null || true

git add -A
echo "--- STATUS ---"
git status --short | head -40

echo "--- DIFF STAT ---"
git diff --cached --stat | tail -20

git commit -m "rescue: batch subcategory fix, SQL-level annotation counts, page-only enrichment

Phase 6: Replace N+1 load_subcategories_for_categories with single ANY() batch query.
         Fix load_subcategories to use category_id JOIN (category_code column does not exist).
Phase 4: Port autonomous learning backend (5 files) from donor af45f27.
Phase 9: Replace full-workset load_current_annotation_states with:
         - SQL-level count_annotation_states_sql for global filter counts
         - Page-only annotation_states load (max 25 IDs)
Phase 6F: Add regression test for staged import path.

WIP=CRM-V3-S13-LOCAL-GOOD-BASE-PRODUCTION-RESCUE-1"

echo "RESCUE_HEAD=$(git rev-parse HEAD)"
echo "RESCUE_GIT_DIRTY=$(git status --porcelain | wc -l)"

echo "--- Push ---"
git push origin CRM-V3-S13-LOCAL-GOOD-BASE-PRODUCTION-RESCUE-1 2>&1

echo "PHASE_15=DONE"
